# Archive (export/import) format

> Extracted from `PLAN.md` §12 (Phase 1). This file is now the maintained spec.

### 12.1 Library archive (`.tfarchive`, ZIP; originals stored uncompressed)

```
manifest.json          { "format": "the_frame_v2.archive", "format_version": 1, "app_version": "…",
                         "created_at": "…", "scope": "full" | "partial", "document_schema": 1,
                         "counts": {…}, "includes_renders": false }
data/photos.jsonl  artworks.jsonl  artwork_tags.jsonl  photo_tags.jsonl  tags.jsonl
     collections.jsonl  collection_items.jsonl  frame_styles.jsonl  layouts.jsonl
     swatches.jsonl  settings.json
originals/<sha256>.<ext>
renders/<artwork_id>.png         (optional)
checksums.sha256                 (every file except itself)
```

- Each JSONL entity has a JSON Schema in `docs/schemas/archive/`. Excluded: devices, tokens, codes, upload sessions,
  jobs, snapshots, cache.
- **Partial export**: selection = collections (optionally nested) and/or artworks → includes those artworks, their
  photos, referenced tags, selected collections subtree (parents outside selection dropped → roots on import),
  optionally referenced templates.
- Export is a job; archive streamed to `exports/` then downloadable; CLI writes directly to a path.

### 12.2 Import

1. Receive archive (chunked upload or CLI path) → staging dir; validate paths, sizes, checksums, manifest, migrate
   `format_version`/`document_schema` if older; refuse newer.
2. **Dry run report** per kind: `new`, `identical` (same id, same canonical content excluding timestamps),
   `conflicting` (same id, different content), plus remaps:
   - Photos: matched by **sha256** (different ids ⇒ remap references). Trashed local photo ⇒ restore.
   - Tags: matched by **name** (case-insensitive) ⇒ remap.
3. User picks per-kind default policy `keep_mine | take_theirs | keep_both` and optional per-item overrides.
   `keep_both` ⇒ new UUIDs, names suffixed " (imported)", references remapped.
4. Apply: copy originals (idempotent by hash) → single DB transaction for entities → snapshots of overwritten
   artworks (`pre_import`) → enqueue thumbs/renders.

### 12.3 Other exports

- **Rendered images**: ZIP (streamed) or CLI folder: `<Collection>/<Sub>/<title or id>.<jpg|png>`; artworks in
  several collections duplicated; uncollected in `Unsorted/`; option: selection / collection / all.
- **Template files**: `*.tfstyle.json` / `*.tflayout.json` = `{ format, format_version, kind, name, document }`;
  references only bundled fonts/textures.
