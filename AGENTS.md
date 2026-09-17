# AGENTS.md — the_frame_v2

> Entry point for coding agents and contributors. **Read this first, trust it, and update it in the same change
> as the code it describes** (rules: `docs/PLAN.md` §3). Keep it under ~300 lines; link to `docs/` for details.

## Purpose & status

Self-hosted web app to prepare pictures for a 4K art-mode TV (Samsung The Frame, 3840×2160): phone uploads in
full quality over the LAN, pixel-perfect framing/compositions, collections, export/import.

- **Current state (2026-09-16): Phases 0–3 done** — foundations, device auth & pairing, resumable uploads,
  ingest pipeline (decode, colour, EXIF, offline place names, thumbnails/proxies), Photos + Inbox UI, phone
  upload page. Since 2026-09-17: LocalSend receiver, merge of photo copies by content fingerprint.
  See `docs/progress.md`.
- **Next: Phase 4** (artwork document, geometry, pyvips renderer) — start with spike S3
  (`docs/research/render-parity.md`). Plan: `docs/PLAN.md` §14.
- Verified by the user on real hardware (2026-09-17): Android uploads (both pickers keep full quality but
  Android zeroes GPS → no place; see `docs/research/phone-uploads.md`), Docker image build/run/persistence.

## Quick commands

| Task | Command |
|---|---|
| Install | `make install` (uv + pnpm) |
| Dev (API :8765 + Vite :5173) | `make dev` — open http://localhost:5173 |
| Everything that must pass | `make check` (ruff, ESLint, mypy strict, tsc, i18n keys, pytest) |
| Backend tests only | `cd backend && uv run pytest` (add `-k name`) |
| Regenerate API types (after any API schema change) | `make gen-api` |
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
| `…/services/` | Use cases: `devices`, `uploads`, `ingest`, `photo_copies` (merge copies), `localsend`, `photos`, `tags`, `geocode` |
| `…/imaging/` | `sniff` (magic bytes), `decode` (the only pixel access), `metadata` (EXIF/ICC), `fingerprint` (hash ignoring EXIF), `capabilities` |
| `…/localsend/` | LocalSend v2 receiver: `app.py` (protocol routes, own TLS port), `discovery.py` (multicast), `identity.py` (cert/fingerprint), `runner.py` (lifespan); logic in `services/localsend.py`, admin API `api/localsend.py` |
| `…/jobs/queue.py` | Persistent in-process job queue with lanes, retries, coalescing |
| `…/events.py` | Thread-safe SSE broker (`/api/v1/events`) |
| `…/db/` | `models.py`, `session.py` (WAL), `migrate.py`, `migrations/versions/` |
| `…/storage.py` | Data-dir layout (originals, cache, uploads) |
| `…/assets/geonames/` | Offline place dataset (built by `scripts/build_geonames.py`, CC BY 4.0) |
| `backend/tests/` | `unit/`, `api/`; fixtures & helpers in `conftest.py` (`make_jpeg`, `pair`, `upload_bytes`) |
| `frontend/src/api/` | `client.ts` (openapi-fetch + `ApiError`), `queries.ts` (TanStack Query hooks), `events.ts` (SSE), generated `schema.d.ts` |
| `frontend/src/app/` | `router.tsx`, `AuthGate.tsx` (role routing), `Shell.tsx` (sidebar), `commands.ts` (shortcuts/palette registry), `theme.ts` |
| `frontend/src/features/` | `upload/` (queue engine `uploadStore.ts`, tray, drop zone), `photos/`, `inbox/`, `devices/`, `auth/`, `mobile/`, `settings/`, `tags/` |
| `frontend/src/shared/` | UI primitives (`ui/`), `format.ts`, `cn.ts` |
| `frontend/src/i18n/` | i18next setup; strings in `locales/en/common.json` |
| `docs/` | Plan, specs, ADRs (`adr/`), research findings (`research/`), progress |

## Architecture essentials

- Layers: `api` (HTTP only) → `services` (transactions, rules) → `imaging` / `db`. Jobs call services.
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
`docs/adr/` · `docs/research/`

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
- `pkill -f "the_frame_v2 serve"` also matches your own shell command line: use `pkill -f "[t]he_frame_v2 serve"`.
