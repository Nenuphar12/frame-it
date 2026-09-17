# AGENTS.md — the_frame_v2

> Entry point for coding agents and contributors. **Read this first, trust it, and update it in the same change
> as the code it describes** (rules: `docs/PLAN.md` §3). Keep it under ~300 lines; link to `docs/` for details.

## Purpose & status

Self-hosted web app to prepare pictures for a 4K art-mode TV (Samsung The Frame, 3840×2160): phone uploads in
full quality over the LAN, pixel-perfect framing/compositions, collections, export/import.

- **Current state (2026-09-17): Phases 0–4 done** — foundations, device auth & pairing, resumable uploads,
  LocalSend receiver, ingest, Photos + Inbox UI, phone upload page; artwork document + geometry (Python/TS
  mirrored), pyvips renderer, built-in styles/layouts, artworks API, Artworks page + viewer (review aid).
  See `docs/progress.md`.
- **Next: Phase 5** (Konva editor, crop/placement/locks, undo/autosave, review flow) — follow the canvas rules in
  `docs/research/render-parity.md`. Plan: `docs/PLAN.md` §14.
- Verified by the user on real hardware (2026-09-17): Android uploads (both pickers keep full quality but
  Android zeroes GPS → no place; see `docs/research/phone-uploads.md`), Docker image build/run/persistence.

## Quick commands

| Task | Command |
|---|---|
| Install | `make install` (uv + pnpm) |
| Dev (API :8765 + Vite :5173) | `make dev` — open http://localhost:5173 |
| Everything that must pass | `make check` (ruff, ESLint, mypy strict, tsc, i18n keys, geometry conformance, pytest) |
| Geometry fixtures | `make conformance` (TS); regenerate from Python: `cd backend && CONFORMANCE_UPDATE=1 uv run pytest tests/unit/test_conformance.py` |
| Golden images | `make golden-update` after an intended pixel change (review PNGs, bump `RENDERER_VERSION`) |
| Render budgets | `cd backend && uv run python ../scripts/bench_render.py` |
| Backend tests only | `cd backend && uv run pytest` (add `-k name`) |
| Regenerate API types + `docs/schemas/` (after any API/document schema change) | `make gen-api` |
| Production build + serve | `make serve` (frontend built into `backend/src/the_frame_v2/static`) |
| CLI | `uv run the_frame_v2 --help` (`serve`, `doctor`, `setup-code`, `openapi`, `db upgrade`, `cache clear`) |
| New migration | edit `db/models.py`, then `cd backend && uv run python -m the_frame_v2.db.migrate "message"`, rename to `NNNN_message.py`, replace custom types by `sa.String` |
| Docker | `make docker`; `docker/compose.yaml` (set `THE_FRAME_V2_PUBLIC_URL`) |

NixOS without nix-ld: the uv-installed `ruff` binary cannot run → `make lint RUFF=ruff` with a Nix ruff.

## Repo map

| Path | Responsibility |
|---|---|
| `backend/src/the_frame_v2/app.py` | App factory: context, routers, SPA serving, lifespan (jobs, setup code) |
| `…/config.py` | Settings (env `THE_FRAME_V2_*` > `<data_dir>/config.toml` > defaults), LAN IP, allowed hosts |
| `…/context.py` | `AppContext` service container (`app.state.ctx`) |
| `…/api/` | Thin routers + `schemas.py` (Pydantic API models = OpenAPI source) + `deps.py` (auth deps) |
| `…/auth/` | `principal.py` (cookie/localhost → role), `middleware.py` (Host/CSRF/headers), `ratelimit.py` |
| `…/services/` | Use cases: `devices`, `uploads`, `ingest`, `photo_copies` (merge copies), `localsend`, `photos`, `tags`, `geocode`, `artworks` (create/save/snapshots), `render` (cache, jobs, region), `templates` (presets) |
| `…/domain/` | PURE: `document` (artwork document v1 + reference checks), `geometry`, `quality` (tiers), `placement`, `templates` (style/layout docs, `build_document`) |
| `…/imaging/` | `sniff` (magic bytes), `decode` (the only pixel access), `metadata` (EXIF/ICC), `fingerprint` (hash ignoring EXIF), `capabilities`, `render` (the renderer), `assets` (fonts/textures catalog) |
| `…/assets/` | `geonames/`, `fonts/` (OFL, `scripts/build_fonts.py`), `textures/` (CC0, `scripts/generate_textures.py`), `presets/` (built-in styles/layouts JSON) |
| `…/localsend/` | LocalSend v2 receiver: `app.py` (protocol routes, own TLS port), `discovery.py` (multicast), `identity.py` (cert/fingerprint), `runner.py` (lifespan); logic in `services/localsend.py`, admin API `api/localsend.py` |
| `…/jobs/` | `queue.py` persistent in-process job queue (lanes, retries, coalescing); `gate.py` render concurrency |
| `…/events.py` | Thread-safe SSE broker (`/api/v1/events`) |
| `…/db/` | `models.py`, `session.py` (WAL), `migrate.py`, `migrations/versions/` |
| `…/storage.py` | Data-dir layout (originals, cache, uploads) |
| `…/assets/geonames/` | Offline place dataset (built by `scripts/build_geonames.py`, CC BY 4.0) |
| `backend/tests/` | `unit/`, `api/`, `golden/` (reference PNGs in `refs/`); fixtures & helpers in `conftest.py` (`make_jpeg`, `pair`, `upload_bytes`) |
| `conformance/geometry/` | Shared JSON fixtures: Python domain ↔ `frontend/src/editor/core` |
| `scripts/` | `build_geonames.py`, `build_fonts.py`, `generate_textures.py`, `bench_render.py`, `render_parity/` (S3 page) |
| `frontend/src/api/` | `client.ts` (openapi-fetch + `ApiError`), `queries.ts` (TanStack Query hooks), `events.ts` (SSE), generated `schema.d.ts` |
| `frontend/src/app/` | `router.tsx`, `AuthGate.tsx` (role routing), `Shell.tsx` (sidebar), `commands.ts` (shortcuts/palette registry), `theme.ts` |
| `frontend/src/editor/core/` | PURE TS mirror of `domain/` (`geometry.ts`, `quality.ts`, `placement.ts`); relative imports with `.ts` extension (run by Node in `scripts/conformance.ts`) |
| `frontend/src/features/` | `upload/` (queue engine `uploadStore.ts`, tray, drop zone), `photos/` (grid, selection, drawer; "Create artworks" from any photo), `inbox/`, `artworks/` (page, viewer, create dialog), `devices/`, `auth/`, `mobile/`, `settings/`, `tags/`, `localsend/` |
| `frontend/src/shared/` | UI primitives (`ui/`), `format.ts`, `cn.ts` |
| `frontend/src/i18n/` | i18next setup; strings in `locales/en/common.json` |
| `docs/` | Plan, specs, ADRs (`adr/`), research findings (`research/`), progress |

## Architecture essentials

- Layers: `api` (HTTP only) → `services` (transactions, rules) → `domain` (pure) / `imaging` / `db`. Jobs call services.
- Artwork flow: `POST /artworks` (photos + style + layout → `build_document`) or `PUT /artworks/{id}/document`
  (`If-Match: <document_version>`) → validate (structure + references) → derived columns + `artwork_photos` →
  commit → coalesced `render` job → `cache/renders/<id>/<render_hash>.png` → SSE `artwork.rendered`. Render
  endpoints render on demand; URLs carry `?v=<render_hash>` for immutable caching.
- `db.session()` is a transactional context manager (commit/rollback). Routers get a request-scoped session via
  `DbSession`; long work runs in jobs or `run_in_threadpool`.
- LocalSend flow (`docs/localsend.md`): multicast discovery → `prepare-upload` (unknown device → admin approval
  via SSE `localsend.request`) → `upload` streamed → `UploadSession(state=processing)` → same `ingest` job.
- Ingest flow: `POST /uploads` → `PATCH` chunks (`Upload-Offset`) → SHA-256 verified → `ingest` job → photo in
  inbox → SSE `photo.ingested` (or `photo.ingest_failed` with a problem code).
- Frontend: server state only in TanStack Query; SSE invalidates `["photos"]`; upload queue is a Zustand store
  outside React (hash → open/resume → chunks with retry → wait for SSE, polling fallback).

## Invariants (never break)

1. Originals are never modified; path = `originals/<sha[:2]>/<sha256>.<ext>`. Only exception: a copy with the
   same content fingerprint and a GPS location replaces a redacted original (`services/photo_copies.py`).
2. `cache/` is always deletable (derivatives regenerate on demand).
3. All pixel decoding goes through `imaging/decode.py`; formats detected by magic bytes, never by extension.
4. Every mutating `/api/` request needs header `X-TF-Client: 1` (the frontend client adds it).
5. Localhost trust only for loopback peers **without** proxy headers and without `trusted_proxies`.
6. API schema change ⇒ `make gen-api` in the same change; DB change ⇒ Alembic migration.
7. All user-facing strings via i18n (`t("…")`); errors carry a stable `code` translated as `errors.<code>`.
8. No secure-context-only browser APIs (crypto.subtle, randomUUID, clipboard write, service worker, wake lock)
   without a fallback: the app runs over plain HTTP on the LAN.
9. `taken_at` is floating camera-local time: never timezone-convert it (display with `timeZone: "UTC"`).
10. Shortcuts are registered through `useRegisterCommands` (they appear in the palette and cheat sheet).

## Conventions

- Python: ruff (line 100), mypy strict, `from __future__ import annotations`, pure functions where possible.
- Errors: raise `ProblemError(status, code, title, detail, extra)` → RFC 9457 JSON with `code`.
- IDs: UUIDv7 (`ids.new_id`); times: aware UTC (`ids.utcnow`), stored as ISO strings.
- Tests: API tests use `local` (trusted localhost client) and `pair(local, role)` for LAN devices; jobs run
  synchronously with `ctx_of(client).jobs.run_pending_sync()`.
- TypeScript: strict, no `any`, `@/` alias to `src/`, one component per file when it exports hooks.
- Commits: Conventional Commits.

## Where specs live

`docs/PLAN.md` (scope, phases, DoD) · `docs/data-model.md` · `docs/localsend.md` · `docs/artwork-document.md` ·
`docs/geometry-and-quality.md` · `docs/rendering-spec.md` · `docs/security.md` · `docs/archive-format.md` ·
`docs/schemas/` (generated) · `docs/adr/` · `docs/research/` · `NOTICE.md` (asset licenses)

## Gotchas

- TypeScript is pinned to `~6.0` (typescript-eslint does not support 7.x yet).
- TanStack Virtual triggers the React Compiler lint `incompatible-library`: suppressed in `PhotoGrid.tsx` on purpose.
- Registering commands with unstable dependencies used to cause a render loop; `useRegisterCommands` now keys
  on ids/shortcuts and calls the latest `run` via a ref — keep it that way.
- Resuming an upload without `meta` must keep the metadata of the original session (regression-tested).
- `Settings.allowed_hosts` must include the test host (`testserver`) in tests; production adds LAN IP/hostname.
- Android (any browser picker) zeroes GPS bytes in place: never expect `gps_lat` from phone web uploads; the
  photo picker also renames files to MediaStore ids (`1000125423.jpg`). A later copy with GPS/name (USB,
  LocalSend, desktop drop) is merged into the existing photo by content fingerprint (`docs/data-model.md`).
- The LocalSend certificate (`<data_dir>/localsend/`) is pinned by phones: never regenerate it casually.
  Tests never bind 53317 (`start_workers=False`; runner tests use a free port and `localsend_discovery=False`).
- Alembic autogenerate proposes dropping the FTS5 `search_index*` tables: delete those lines by hand.
- Geometry change ⇒ change Python **and** TS, add a case to `CASES` in `tests/unit/test_conformance.py`,
  regenerate fixtures, check the new expected values by hand.
- Any renderer pixel change ⇒ bump `RENDERER_VERSION` (render hash) and `make golden-update`; asset file changes ⇒
  bump the manifest `version`. Golden sources are PNG (JPEG encoders differ between libvips builds).
- libvips gotchas: trigonometric ops use **degrees**; `gaussblur` default `min_ampl=0.2` clips (use 0.005);
  `Image.text` is cropped to ink (offsets in `xoffset`/`yoffset`); `affine` pixel centres need the ±0.5
  `idx/odx` offsets (see `_rotate`); `find_load` is not exposed by pyvips (sniff instead).
- A render holds all decoded originals of the document in memory (parallel decode); `render_workers` bounds it.
- `ArtworkDocument.schema_version` is serialized as `"schema"` (alias): dump with `canonical()`.
- `pkill -f "the_frame_v2 serve"` also matches your own shell command line: use `pkill -f "[t]he_frame_v2 serve"`.
