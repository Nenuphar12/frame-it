# AGENTS.md — Frame It

> Entry point for coding agents and contributors. **Read this first, trust it, and update it in the same change
> as the code it describes** (rules: `docs/PLAN.md` §3). It keeps what most tasks need; the rest is one link
> away: [`docs/codebase.md`](docs/codebase.md) (each area's rules, the full repo map, the flows, more commands)
> and [`docs/gotchas.md`](docs/gotchas.md) (pitfalls by subsystem — read the section before you touch it).

## Purpose & status

Self-hosted web app to prepare pictures for a 4K art-mode TV (Samsung The Frame, 3840×2160): phone uploads in
full quality over the LAN, pixel-perfect framing/compositions, collections, export/import.

- **Status (2026-11-17): beta, open source since 2026-10-06. Phases 0–12 done, plus their follow-ups.
  Next: the roadmap, `docs/PLAN.md` §17** — HEIC from iPhones, then an installation without a
  toolchain (CI runs `make check`; releases and executables to come). What each phase added:
  `docs/progress.md` (before the beta: `docs/progress-before-beta.md`).
- **Areas** — uploads, the artwork document and renderer, the editor, templates, organization, export/import,
  hardening, the TV, i18n: what each is, its spec, and what a change there must respect are in
  [`docs/codebase.md` §Areas](docs/codebase.md#areas). Read that entry before working in an area.
- **Written with AI, and said so** (`README.md` *Written with AI*, `CONTRIBUTING.md`). That README section
  is also the one list of what is and is not checked on real hardware: update it when that changes.

## Quick commands

| Task | Command |
|---|---|
| Install | `make install` (uv + pnpm) |
| Dev (API :8765 + Vite :5173) | `make dev` — open http://localhost:5173 |
| Everything that must pass | `make check` (ruff, ESLint, mypy strict, tsc, i18n keys, geometry conformance, generated files, pytest, editor rules) |
| Backend tests only | `cd backend && uv run pytest -n auto` (~1 min 20 s on 16 cores); one file or `-k name` without `-n` |
| Editor rules only | `cd frontend && pnpm test` (`src/**/*.test.ts`, Node's own runner) |
| Regenerate API types + `docs/schemas/` (after any API/document schema change) | `make gen-api` |
| Geometry fixtures | `make conformance` (TS); regenerate from Python: `cd backend && CONFORMANCE_UPDATE=1 uv run pytest tests/unit/test_conformance.py` |
| New migration | edit `db/models.py`, then `cd backend && uv run python -m frame_it.db.migrate "message"`, rename to `NNNN_message.py`, replace custom types by `sa.String`; never batch-rebuild a table others cascade from (`docs/gotchas.md`) |
| Production build + serve | `make serve` (frontend built into `backend/src/frame_it/static`) |
| CLI | `uv run frame-it --help` (`serve`, `doctor`, `setup-code`, `openapi`, `schemas`, `db upgrade`, `cache clear`, `service`, `export`, `import`, `tv`, `version`) |

Benches, seeding, golden images, Docker, the fake TV, the E2E setup, the dependency audit:
[`docs/codebase.md` §More commands](docs/codebase.md#more-commands).

## Repo map

| Path | Responsibility |
|---|---|
| `backend/src/frame_it/` | `app.py` (factory, lifespan), `config.py` (env `FRAME_IT_*` > `<data_dir>/config.toml` > defaults), `context.py` (`AppContext`), `events.py` (SSE broker), `storage.py` (data-dir layout) |
| `…/api/` | Thin routers, one per area; `schemas.py` (Pydantic API models = the OpenAPI source); `deps.py` (auth) |
| `…/services/` | Use cases and transactions, one module per area — each docstring says what it owns |
| `…/domain/` | PURE: the document, geometry, quality, constraints (editor solver), composition, templates, filters, archive |
| `…/imaging/` | `decode` (the only pixel access), `sniff` (magic bytes), `metadata`, `render` (the renderer) |
| `…/tv/` · `…/localsend/` · `…/jobs/` · `…/db/` · `…/auth/` | TV client, discovery, `FakeTv` · LocalSend receiver · job queue · models + migrations · principal, middleware |
| `backend/tests/` | `unit/`, `api/`, `golden/`; helpers in `conftest.py` (`make_jpeg`, `pair`, `upload_bytes`) |
| `conformance/geometry/` | Shared JSON fixtures: Python `domain/` ↔ `frontend/src/editor/core` |
| `frontend/src/api/` | `client.ts`, `queries.ts` (TanStack Query hooks), `events.ts` (SSE), generated `schema.d.ts` |
| `frontend/src/app/` | `router.tsx`, `AuthGate.tsx`, `Shell.tsx`, `commands.ts` (shortcuts registry) |
| `frontend/src/editor/` | `core/` (PURE TS mirror of `domain/`), `store.ts`, `operations.ts` (how a change propagates), `actions.ts`, `canvas/`, `panels/` |
| `frontend/src/features/` · `shared/` · `i18n/` | One folder per page or flow · UI primitives, `toast.ts`, `format.ts` · `locales/{en,fr}/common.json` |
| `scripts/` · `docs/` | Asset builders, benches, seeding · specs, ADRs, research, progress |

One line per module: [`docs/codebase.md` §Repo map](docs/codebase.md#repo-map).

## Architecture essentials

- Layers: `api` (HTTP only) → `services` (transactions, rules) → `domain` (pure) / `imaging` / `db`. Jobs call services.
- `db.session()` is a transactional context manager (commit/rollback). Routers get a request-scoped session via
  `DbSession`; long work runs in jobs or `run_in_threadpool`.
- Frontend: server state only in TanStack Query; SSE events invalidate their keys, and a `resync` or a
  reconnection refetches everything. Client state lives in Zustand stores outside React (upload queue, editor).
- Editor: a control calls `editor/actions` → `editor/operations` mutates an Immer draft → `store.edit()` records
  patches (undo/redo) and debounces a `PUT document` with `If-Match`. Only `operations.ts` knows how a change
  propagates.
- The flows end to end — artwork save → render, ingest, LocalSend, export/import, compositions, editor
  selection: [`docs/codebase.md` §Flows](docs/codebase.md#flows).

## Invariants (never break)

1. Originals are never modified; path = `originals/<sha[:2]>/<sha256>.<ext>`. Only exception: a copy with the
   same content fingerprint and a GPS location replaces a redacted original (`services/photo_copies.py`).
   Receiving a photo again (any source, duplicate included) puts it back in the inbox (`receive_again`).
2. `cache/` is always deletable (derivatives regenerate on demand).
3. All pixel decoding goes through `imaging/decode.py`; formats detected by magic bytes, never by extension.
4. Every mutating `/api/` request needs header `X-TF-Client: 1` (the frontend client adds it).
5. Localhost trust only for loopback peers **without** proxy headers and without `trusted_proxies`.
6. API schema change ⇒ `make gen-api` in the same change; DB change ⇒ Alembic migration.
7. All user-facing strings via i18n (`t("…")`), in **every** catalog (English, French — `make i18n` fails
   on a key or a `{{placeholder}}` one of them lacks); errors carry a stable `code` translated as `errors.<code>`.
8. No secure-context-only browser APIs (crypto.subtle, randomUUID, clipboard write, service worker, wake lock)
   without a fallback: the app runs over plain HTTP on the LAN.
9. `taken_at` is floating camera-local time: never timezone-convert it (display with `timeZone: "UTC"`).
10. Shortcuts are registered through `useRegisterCommands` (they appear in the palette and cheat sheet).
11. The editor never writes a document the server would reject: every geometry change goes through
    `domain/constraints` ↔ `editor/core/constraints.ts` (aspect consistency + the quality lock).
12. Pointer gestures never drive React state per event: accumulate and flush once per animation frame
    (§8.5 budget — and a per-event render freezes the tab, see Gotchas).
13. A photo the editor has not loaded (`sizes`) must not reach a geometry operation: `ensurePhotoSize` first,
    or the slot is built as if it were empty (crop = the slot's shape instead of the photo's).
14. A failure is never silent: a mutation either renders its own (`meta: { silentError: true }`) or the
    `MutationCache` in `main.tsx` raises a toast. A job that fails reaches `/activity` through `jobs.code`.
15. A TV only loses what the user agreed to lose: the app deletes a `content_id` it did not
    upload **only** when the caller passed `allow_delete_foreign`, because the art channel cannot
    give an image back (`docs/tv-display.md`). What makes "did not upload" true: **a
    `display_target_items` row lives exactly as long as its upload is on the TV** — written in its
    own transaction as soon as the TV accepts the upload, removed only once the TV no longer holds
    it, never because the set changed. "Don't change" (`slideshow_minutes = 0`) deletes nothing.
16. Colour is a token, never a literal, and a new pair must pass AA (4.5:1 for text, 3:1 for a control's
    boundary — `--color-border-strong`) in **both** themes.

## Glossary

Photo, artwork, draft, slot, mat, margins, band, quality tier and lock, placement, frame style, layout,
recipe, composition, proxy, render hash: [`docs/PLAN.md` §2](docs/PLAN.md#2-glossary). A display
target is a TV the app pushes to (`docs/tv-display.md`).

## Conventions

- Python: ruff (line 100), mypy strict, `from __future__ import annotations`, pure functions where possible.
- Errors: raise `ProblemError(status, code, title, detail, extra)` → RFC 9457 JSON with `code`.
- IDs: UUIDv7 (`ids.new_id`); times: aware UTC (`ids.utcnow`), stored as ISO strings.
- Tests: API tests use `local` (trusted localhost client) and `pair(local, role)` for LAN devices; jobs run
  synchronously with `ctx_of(client).jobs.run_pending_sync()`.
- TypeScript: strict, no `any`, `@/` alias to `src/`, one component per file when it exports hooks.
- Commits: Conventional Commits, and **no `Co-Authored-By:` trailer** — how the project was made
  is said once, in the README (*Written with AI*), not on every commit.

## Where specs live

`docs/PLAN.md` (scope, phases, DoD) · `docs/data-model.md` · `docs/localsend.md` · `docs/artwork-document.md` ·
`docs/simple-editor.md` (Phase 7: compositions, recipes, the solver) · `docs/templates.md` (Phase 8) ·
`docs/organization.md` (Phase 9: tags, collections, filters, search, trash) ·
`docs/geometry-and-quality.md` · `docs/rendering-spec.md` · `docs/security.md` ·
`docs/archive-format.md` (Phase 10: the archive, the dry run, the policies) ·
`docs/user-guide.md` (phase 11: install, pairing, tiers, troubleshooting, settings) ·
`docs/tv-display.md` (Phase 12: the TV, what it allows, and how a push works) ·
`docs/schemas/` (generated) · `docs/adr/` · `docs/research/` · `NOTICE.md` (third-party notices) ·
`docs/gotchas.md` (the subsystem-specific ones) · `docs/codebase.md` (areas, full repo map, flows, more commands) · `CONTRIBUTING.md` · `LICENSE` (MIT)

## Gotchas

**The subsystem-specific ones live in [`docs/gotchas.md`](docs/gotchas.md) — read the section for
whatever you are touching before you touch it.** These bite whatever you are working on:

- A change that implies another: geometry ⇒ Python **and** TS, a case in `CASES`
  (`tests/unit/test_conformance.py`), regenerated fixtures checked by hand · the same document rendering
  to different pixels ⇒ bump `RENDERER_VERSION` + `make golden-update` (asset files ⇒ the manifest
  `version`) · a new optional document field ⇒ `_LATER_DEFAULTS` (`domain/document.py`), or every render
  hash moves and the whole set is re-uploaded to the TV.
- **Verify in a browser when you can, never blocking** (`docs/PLAN.md` §13.6): the Chrome extension
  cannot drive this app; headless Chromium over CDP against the production build can. Read results back
  through the API. How, and what bites: `docs/gotchas.md` §Driving the app in a browser.
- `make format` runs prettier over the whole frontend and rewrites ~20 files you did not touch: format
  your own files, then `git checkout --` the rest.
- Dev over the Vite proxy is **not** trusted as localhost (`xfwd` adds `X-Forwarded-For`, invariant 5): the
  first load asks for the setup code printed in the server log. Point Vite at another backend with
  `FRAME_IT_BACKEND=http://127.0.0.1:<port>`.
- `pkill -f "frame-it serve"` also matches your own shell command line: use `pkill -f "[f]rame-it serve"`.
