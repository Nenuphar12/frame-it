# Data model

> Extracted from `PLAN.md` §5 (Phase 1). This file is now the maintained spec.

IDs: **UUIDv7** strings (Python 3.14 `uuid.uuid7()`), merge-friendly for import. Timestamps: UTC ISO-8601.
Soft delete via `deleted_at` (+ `trash_batch_id` to restore related items together).

### 5.1 Tables

| Table | Columns (main) | Notes |
|---|---|---|
| `photos` | id, sha256 (unique), content_fingerprint (unique, SHA-256 ignoring JPEG EXIF), ext, mime, original_filename, file_size, width, height (post-EXIF-orientation), exif_orientation, bit_depth, icc_description, is_wide_gamut, has_gain_map, taken_at, camera_make, camera_model, lens, gps_lat, gps_lon, place_name, place_admin1, place_country, uploaded_by_device_id, imported_at, inbox_state (`inbox`/`processed`/`dismissed`), quality_warnings (JSON), deleted_at, trash_batch_id | `taken_at` is a **floating wall-clock time** (camera local time, stored with a `Z` marker, never converted; display with `timeZone: UTC`). `quality_warnings` codes: `metadata_missing`, `location_removed`, `possibly_downscaled`, `below_tv_resolution`, `high_bit_depth_reduced` |
| `photo_tags` | photo_id, tag_id | |
| `photo_pending_meta` | photo_id, collection_ids (JSON), favorite | Set at phone upload; applied when artworks are created from the photo |
| `tags` | id, name (unique, NOCASE), color, created_at | |
| `artworks` | id, title, status (`draft`/`ready`), document (JSON), document_version (int, optimistic concurrency), schema_version, favorite, worst_tier, min_scale, max_scale, photo_count, is_incomplete, origin_style_id, origin_style_revision, origin_layout_id, origin_layout_revision, render_hash, rendered_at, created_at, updated_at, deleted_at, trash_batch_id | Derived columns recomputed on every document save |
| `photo_hash_aliases` | sha256 (PK), photo_id | SHA-256 of other copies merged into a photo (see *Photo copies*); used by dedupe |
| `localsend_devices` | id, fingerprint (unique), alias, device_model, device_type, status (`pending`/`approved`/`blocked`), last_ip, created_at, last_seen_at, decided_at | LocalSend senders (`docs/localsend.md`); their uploads use `upload_sessions.device_key = localsend:<id>` |
| `artwork_photos` | artwork_id, slot_id, photo_id | Derived index for usage queries |
| `artwork_tags` | artwork_id, tag_id | |
| `artwork_snapshots` | id, artwork_id, document, document_version, reason (`opened`/`pre_template_update`/`pre_import`), created_at | Keep last 20 per artwork |
| `collections` | id, parent_id, name, description, date_start, date_end, cover_artwork_id, kind (`manual`/`smart`), filter (JSON AST, smart only), position (REAL, among siblings), created_at, updated_at | Cycle prevention on move; deletion is not trashed (artworks unaffected) |
| `collection_items` | collection_id, artwork_id, position (REAL) | Manual collections only; renormalize when gaps < 1e-9 |
| `frame_styles` | id, name, revision, document (JSON), builtin, created_at, updated_at | |
| `layouts` | id, name, revision, document (JSON), slot_count, builtin, created_at, updated_at | |
| `swatches` | id, color, name, position | |
| `devices` | id, name, role (`uploader`/`admin`), token_hash, user_agent, created_at, last_seen_at, revoked_at | |
| `pairing_codes` | code_hash, role, expires_at, used_at | single use, 5 min |
| `setup_codes` | code_hash, expires_at, used_at | generated at startup when no admin device exists |
| `upload_sessions` | id, device_key (device id or `localhost`), sha256, size, filename, mime, received_bytes, pending_meta (JSON), state (`open`/`processing`/`failed`), error, job_id, created_at, expires_at | Resumable; looked up by (device_key, sha256, size) while open. Temp file: `uploads/tmp/<id>.part`. Deleted after successful ingest |
| `jobs` | id, kind, lane (`ingest`/`render`), coalesce_key, payload (JSON), state (`queued`/`running`/`done`/`failed`/`cancelled`), attempts, progress, error, created_at, started_at, finished_at | Lanes bound concurrency per kind of work; queued jobs with the same coalesce_key are cancelled when a new one is enqueued |
| `settings` | key, value (JSON) | UI prefs, default style/layout ids |
| FTS5 `search_index` | entity_type, entity_id, text | titles, tag names, place names, filenames, collection names |

### Photo copies (merge by content fingerprint)

Android browsers upload GPS-redacted files, and the Android photo picker renames them (`1000125423.jpg`). Copies
of one photo therefore differ by SHA-256 but share `content_fingerprint` (`imaging/fingerprint.py`: SHA-256 of
the JPEG without its EXIF APP1 segments; other formats: file SHA-256). At ingest (`services/photo_copies.py`):

- known SHA-256 (photo or alias) → duplicate;
- same fingerprint, the copy has GPS and the photo has none → the copy **replaces the original file** (same
  image data, richer EXIF), place and warnings are updated, cached derivatives are moved, the old SHA-256
  becomes an alias; photo id, tags, inbox state and future artwork references are unchanged;
- same fingerprint otherwise → the copy's SHA-256 becomes an alias;
- in both cases a real file name replaces a generated one.

The upload is reported as a duplicate with `merged: ["location", "filename"]` in the `photo.ingested` event.
Photos imported before migration 0002 get fingerprints from the `fingerprint_backfill` startup job; copies
that were already imported twice keep a NULL fingerprint (no automatic merge of existing photos).

### 5.2 Smart-collection / library filter AST

One structure powers the library filter bar **and** smart collections:

```jsonc
{ "op": "and", "clauses": [
  { "field": "tag",        "op": "has_any", "value": ["<tag_id>"] },
  { "field": "favorite",   "op": "eq",      "value": true },
  { "field": "collection", "op": "in",      "value": "<id>", "include_nested": true },
  { "field": "taken_at",   "op": "between", "value": ["2026-04-01", "2026-04-30"] },
  { "field": "place",      "op": "contains","value": "Kyoto" },
  { "field": "worst_tier", "op": "in",      "value": ["native", "downscaled"] },
  { "field": "status",     "op": "eq",      "value": "ready" },
  { "field": "text",       "op": "match",   "value": "temple" }
]}
```

Compiled to SQL in `domain/filters.py` (validation) + `services/library.py` (SQLAlchemy). Nested collection
membership via recursive CTE. Smart collections may not reference themselves (cycle check).

### 5.3 Data directory

```
<data_dir>/
├── library.db (+ -wal, -shm)
├── config.toml
├── originals/ab/ab12…<sha256>.<ext>
├── uploads/tmp/<upload_id>.part
├── cache/                               # disposable
│   ├── thumbs/<sha>/{256,768}.webp
│   ├── proxies/<sha>/2560.jpg
│   ├── palettes/<sha>.json
│   └── renders/<artwork_id>/<render_hash>.{png,jpg}
└── exports/ imports/                    # temporary staging, auto-cleaned
```
