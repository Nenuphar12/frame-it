# Codebase guide

> The parts of [`AGENTS.md`](../AGENTS.md) a task needs only when it reaches that area: what each area
> is and must respect, the map of every module, the flows end to end, the rarer commands.
> `AGENTS.md` links here; keep both current in the same change as the code (`docs/PLAN.md` §3).
> Pitfalls by subsystem are in [`gotchas.md`](gotchas.md).

## Areas

The areas, where they are specified, and what a change there must respect. Read the entry for the
area you are working in before you change it.

- **Uploads & ingest** (`docs/localsend.md`, `docs/research/phone-uploads.md`): resumable uploads, the
  LocalSend receiver, the phone upload page.
- **Artwork document, geometry, renderer** (`docs/artwork-document.md`, `docs/geometry-and-quality.md`,
  `docs/rendering-spec.md`): the render hash reads `render_identity()`, so a schema addition moves no
  cache, TV or outdated badge.
- **Editor** (`docs/simple-editor.md`): Konva canvas; **Simple** edits the optional `composition` block
  (a recipe + parameters, `weights` included) that the mirrored solver turns into slots, and the server
  re-solves on every save; **Advanced** is free-form and sets `detached`. Recipes: `GET /recipes`.
  A straightened photo (`source.straighten`) is a smaller photo to every crop rule: the crop lives
  in `straightened_size` (`slotSource` / `SourceSpec.bounds`), only the renderer and canvas turn it.
- **Templates** (`docs/templates.md`): a layout is a recipe + parameters; styles and layouts have CRUD,
  "Save as", `.tf*.json` files, apply-template with the outdated badge, and push update (dry run +
  `pre_template_update` snapshots). `restyle`/`relayout` are pure and mirrored.
- **Organization** (`docs/organization.md`): one filter AST (`domain/filters.py` validates,
  `services/library.py` compiles) behind the filter bar, `POST /artworks/query` and smart collections;
  collections as a tree; FTS search; tags with categories, and an artwork **carries its photos' tags**
  (read, never copied); `place near` on the photos' GPS; Places and Timeline (year → month) tabs
  derived from photo metadata; the trash acts, then offers Undo. A photo leaves
  the inbox only when an artwork using it is marked **ready** (one-way).
- **Export / import** (`docs/archive-format.md`): the `.tfarchive` is a ZIP of JSON + JSON Lines + the
  originals; staging → dry-run report → apply under `keep_mine | take_theirs | keep_both`; the CLI does
  the same without a browser.
- **Hardening** (`docs/user-guide.md`, `docs/security.md`): `MAX_RENDER_PIXELS` (320 Mpx of distinct
  sources), AA in both themes, `/activity` for failed jobs, `frame-it service install`. Licence MIT.
- **Name**: Frame It (package `frame_it`, command `frame-it`, env `FRAME_IT_*`) since 2026-10-06; the
  placeholder `the_frame_v2` is no longer read anywhere (env, data dir, archives: removed 2026-11-17).
- **TV** (`docs/tv-display.md`, measurements in `docs/research/tv-display.md`): the Frame's slideshow
  cannot be scoped to a subset, so a push **mirrors** the set (`keep_ours` spares our earlier
  uploads); a push is stop → select → start, uploads go in reverse (the TV lists newest first), and
  "Don't change" (`slideshow_minutes = 0`) rotates and deletes nothing. A TV is followed by MAC when
  its address changes. `FRAME_IT_FAKE_TV=1` drives it all without a TV. The art channel waits for
  `ms.channel.ready` (`art_channel_class`): the library's own `open()` failed on the TV's client
  announcements.
- **i18n**: English and French catalogs; server data (built-in style names, place names) stays as stored.

## Repo map

| Path | Responsibility |
|---|---|
| `backend/src/frame_it/app.py` | App factory: context, routers, SPA serving, lifespan (jobs, setup code) |
| `…/config.py` | Settings (env `FRAME_IT_*` > `<data_dir>/config.toml` > defaults), LAN IP, allowed hosts |
| `…/context.py` | `AppContext` service container (`app.state.ctx`) |
| `…/api/` | Thin routers, one per area + `schemas.py` (Pydantic API models = the OpenAPI source) + `deps.py` (auth dependencies); `jobs.py` is the activity centre |
| `…/auth/` | `principal.py` (cookie/localhost → role), `middleware.py` (Host/CSRF/headers), `ratelimit.py` |
| `…/services/` | Use cases, one module per area (each docstring says what it owns): `uploads` → `ingest` → `photos`, `photo_copies` (merge copies), `localsend`, `devices`; `artworks` (create/save/snapshots, and the artwork-writing half of templates: apply, push update), `templates` (presets, CRUD, files, defaults), `recipes` (bundled catalogue, no DB), `render` (cache, jobs, region), `colors`; `library` (filter compiler + listing), `collections`, `tags`, `places`, `timeline`, `geocode`, `search` (FTS, `INDEX_VERSION`), `trash`; `archive_export`, `archive_import`, `archive_apply` (id maps); `display` (TV targets, the push); `jobs_admin` (failures, retry, pruning) |
| `…/domain/` | PURE: `document` (document v1, the `composition` block, reference checks), `geometry`, `quality`, `placement`, `constraints` (editor solver), `alternatives`, `arrange`, `composition` (recipe trees, the solver, `apply`), `templates` (`restyle`/`relayout`, `build_composition_document`), `filters` (library filter AST), `geo`, `archive` (records, file layout, member-name safety) |
| `…/imaging/` | `sniff` (magic bytes), `decode` (the only pixel access), `metadata` (EXIF/ICC), `fingerprint` (hash ignoring EXIF), `capabilities`, `render` (the renderer), `palette` (OKLab k-means), `assets` (fonts/textures catalog) |
| `…/assets/` | `geonames/`, `fonts/` (OFL, `scripts/build_fonts.py`), `textures/` (CC0, `scripts/generate_textures.py`), `presets/` (built-in styles/layouts + `recipes.json`) |
| `…/tv/` | `client.py` (`TvClient`, `SamsungTvClient` over `samsungtvws`, pairing), `discovery.py` (SSDP + /24 sweep, `find_by_mac`), `fake.py` (`FakeTv`: the firmware's quirks, for tests and `FRAME_IT_FAKE_TV`). The push itself: `services/display.py` |
| `…/localsend/` | LocalSend v2 receiver: `app.py` (protocol routes, own TLS port), `discovery.py` (multicast), `identity.py` (cert/fingerprint), `client.py` (outgoing TLS), `runner.py` (lifespan); logic in `services/localsend.py`, admin API `api/localsend.py` |
| `…/jobs/` | `queue.py` persistent in-process job queue (lanes, retries, coalescing); `gate.py` render concurrency |
| `…/events.py` | Thread-safe SSE broker (`/api/v1/events`) |
| `…/db/` | `models.py`, `session.py` (WAL), `migrate.py`, `migrations/versions/` |
| `…/storage.py` | Data-dir layout (originals, cache, uploads) |
| `…/service.py` | Generates this machine's systemd unit / launchd plist (`frame-it service`) |
| `…/assets/geonames/` | Offline place dataset (built by `scripts/build_geonames.py`, CC BY 4.0) |
| `backend/tests/` | `unit/`, `api/`, `golden/` (reference PNGs in `refs/`); fixtures & helpers in `conftest.py` (`make_jpeg`, `pair`, `upload_bytes`) |
| `conformance/geometry/` | Shared JSON fixtures: Python domain ↔ `frontend/src/editor/core` (`render.json`: the two renderer constants the canvas mirrors) |
| `scripts/` | `check_generated.py` (`make generated`), asset builders (`build_geonames`, `build_fonts`, `generate_textures`), benches (`bench_render`: time **and** peak RSS, `bench_library`), `seed_library.py`, spikes (`render_parity/`, `tv_probe.py --fake`) |
| `frontend/src/api/` | `client.ts` (openapi-fetch + `ApiError`), `queries.ts` (TanStack Query hooks), `events.ts` (SSE), generated `schema.d.ts` |
| `frontend/src/app/` | `router.tsx`, `AuthGate.tsx` (role routing), `Shell.tsx` (sidebar), `commands.ts` (shortcuts/palette registry), `theme.ts` |
| `frontend/src/editor/core/` | PURE TS mirror of `domain/` (same module names, plus `bevel`); client-only `snapping`, `bounds`, `splits`, `document` (every optional field filled in). Relative imports with `.ts`: Node runs them in `frontend/scripts/conformance.ts` |
| `frontend/src/editor/` | `EditorPage.tsx` (layout, shortcuts, review queue), `store.ts` (working document, undo/redo on Immer patches, autosave + conflicts), `operations.ts` (pure document mutations: how a change propagates; its rules pinned in `operations.test.ts`), `actions.ts` (what the UI calls), `TvPreview.tsx` |
| `…/editor/canvas/` | `EditorStage.tsx` (Konva stage, one pointer pipeline for every gesture), `SlotNode.tsx`, `CaptionNode.tsx`, `SelectionOverlay.tsx`, `StraightenGuides.tsx`, `hit.ts` (rotation-aware hit tests), `texture.ts`, `fonts.ts`, `useOrientedImage.ts` |
| `…/editor/panels/` | `SimplePanel` (the parametric editor) + `RecipePicker`, `SlotsPanel`, `PhotoPicker`, `ArrangePanel`, `CaptionsPanel`, `FramingPanel`, `StylePanel`, `AlternativesPanel`, `Loupe`, `QualityBadge`, `InfoSheet`; shared with the template editor: `ColorField`, `ShadowFields`, `Controls` (every slider has a typed twin) |
| `frontend/src/features/` | One folder per page or flow: `display/`, `activity/`, `archive/`, `upload/` (queue engine `uploadStore.ts`), `photos/`, `inbox/`, `artworks/`, `templates/`, `library/` (filter AST + chip bar), `collections/`, `trash/` (`useTrashWithUndo`), `tags/` (`TagMenu`, `PlacesView`), `devices/`, `auth/`, `mobile/`, `settings/`, `localsend/`. The editor lives in `src/editor/`, not here |
| `frontend/src/shared/` | UI primitives (`ui/`, incl. `Toaster.tsx`), `toast.ts` (the store, outside React), `problem.ts` (`problemMessage`), `format.ts`, `cn.ts`, `dnd.ts` (the MIME types our own drags carry) |
| `frontend/src/i18n/` | i18next setup (Settings choice, else the browser's language); strings in `locales/en/common.json` and `locales/fr/common.json` |
| `.github/workflows/check.yml` | CI: `make check` on pushes to master and pull requests (uv and pnpm pinned like Docker) |
| `docs/` | Plan, specs, ADRs (`adr/`), research findings (`research/`), progress |

## Flows

- Artwork flow: `POST /artworks` (photos + style + a layout or a composition → `build_composition_document`) or `PUT /artworks/{id}/document`
  (`If-Match: <document_version>`) → validate (structure + references) → derived columns + `artwork_photos` →
  commit → coalesced `render` job → `cache/renders/<id>/<render_hash>.png` → SSE `artwork.rendered`. Render
  endpoints render on demand; URLs carry `?v=<render_hash>` for immutable caching.
- LocalSend flow (`docs/localsend.md`): multicast discovery → `prepare-upload` (unknown device → admin approval
  via SSE `localsend.request`) → `upload` streamed → `UploadSession(state=processing)` → same `ingest` job.
  Already-sent files are not transferred again (no token; when nothing is new, the smallest one is transferred
  and dropped so the app still shows a transfer), and the web tray (`localsend.*` events) tells what happened.
- Ingest flow: `POST /uploads` → `PATCH` chunks (`Upload-Offset`) → SHA-256 verified → `ingest` job → photo in
  inbox → SSE `photo.ingested` (or `photo.ingest_failed` with a problem code).
- Export/import flow (`docs/archive-format.md`): `POST /exports` → job → `exports/<job_id>/<name>.tfarchive`
  → `GET /exports/{job_id}/download`; `POST /imports` + `PATCH` chunks → staging job (validate, then classify
  every row against the library) → `GET /imports/{id}/report` → `POST /imports/{id}/apply`, which writes
  everything in one transaction through the id maps. Both staging areas are swept by `archive.sweep`.
- Frontend: server state only in TanStack Query; SSE events invalidate their keys, and a `resync` (the
  broker dropped what a slow client could not take) or a reconnection refetches everything; upload queue is a
  Zustand store outside React (hash → open/resume → chunks with retry → wait for SSE, polling fallback).
- Compositions (Phase 7, `docs/simple-editor.md`): an optional `composition` block holds a recipe id
  plus parameters (balance, outer, gutter, format, border, caption). `domain/composition.solve` turns it
  into cells — **footprints** (photo rect + border) so `gutter`/`outer` describe what the eye sees, then
  deflated by the border into the slot rects. The block is the source of truth while `detached = false`:
  `services/artworks.validated()` parses, checks references, then **re-solves** (`composition.apply`),
  so no client can persist a rect the composition does not imply. `POST /artworks` is always
  parametric: a `layout_id` supplies a saved recipe + parameters (recorded as the origin layout),
  otherwise the catalogue and the Settings defaults do.
- Editor selection: `selectedSlotIds` (Shift/Ctrl-click adds; the **last** id is the *primary* one the
  property panels edit) and `selectedCaptionId` are exclusive. Nothing selected is a normal state
  with several photos (the mat, `Escape`): panels must cope with no primary slot. Framing and cropping act on the primary slot,
  locks/decorations on every selected slot, arranging on the selection (`editor/operations.ts`).
- Editor flow: `EditorPage` loads the artwork + its photos' sizes → `openArtwork` puts the working document in
  the Zustand store (outside React) → a control calls `editor/actions` → `editor/operations` mutates an Immer
  draft → `store.edit()` records patches (undo/redo, grouped per gesture) and debounces a `PUT document` with
  `If-Match`. Only `operations.ts` knows how a change propagates (margins re-place the slot, a crop edit under
  `native` pushes into the margins…), so the rules stay testable and replayable.

## More commands

| Task | Command |
|---|---|
| Golden images | `make golden-update` after an intended pixel change (review PNGs, bump `RENDERER_VERSION`) |
| Render budgets + peak RSS | `cd backend && uv run python ../scripts/bench_render.py` |
| Library budgets (seeded 10k) | `cd backend && uv run python ../scripts/bench_library.py --data-dir /tmp/seed` |
| Dependency audit | `cd frontend && pnpm audit`; backend: `uv export --no-emit-project --no-dev --format requirements.txt -o /tmp/r.txt && uv run --with pip-audit pip-audit -r /tmp/r.txt` |
| Run at login | `uv run frame-it service install` (`--show` prints the unit; `status`, `uninstall`) |
| Seed a big library (Phase 9 AC) | `cd backend && uv run python ../scripts/seed_library.py --data-dir /tmp/seed --artworks 10000` |
| Export / import a library | `uv run frame-it export -o lib.tfarchive` · `uv run frame-it import lib.tfarchive --dry-run` |
| Editor E2E against a copy of the library | `cp -r .dev-data /tmp/e2e && cd backend && FRAME_IT_DATA_DIR=/tmp/e2e FRAME_IT_PORT=8799 uv run frame-it serve`, then `cd frontend && FRAME_IT_BACKEND=http://127.0.0.1:8799 pnpm dev --port 5199` |
| TV pages without a TV | `FRAME_IT_FAKE_TV=1 uv run frame-it serve` (one in-memory `FakeTv`; never reaches a real TV) · `uv run frame-it tv scan` lists the TVs on the LAN |
| Docker | `make docker`; `docker/compose.yaml` (set `FRAME_IT_PUBLIC_URL`) |
