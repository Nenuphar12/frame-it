# AGENTS.md — Frame It

> Entry point for coding agents and contributors. **Read this first, trust it, and update it in the same change
> as the code it describes** (rules: `docs/PLAN.md` §3). Keep it under ~300 lines; link to `docs/` for
> details — the subsystem gotchas live in [`docs/gotchas.md`](docs/gotchas.md).

## Purpose & status

Self-hosted web app to prepare pictures for a 4K art-mode TV (Samsung The Frame, 3840×2160): phone uploads in
full quality over the LAN, pixel-perfect framing/compositions, collections, export/import.

- **Status (2026-10-06): Phases 0–12 done, plus their follow-ups. Next: nothing planned**
  (`docs/PLAN.md` §16 keeps the open questions). What each phase added, with its measurements and
  migrations: `docs/progress.md`. The areas, where they are specified, and what a change there must respect:
  - **Uploads & ingest** (`docs/localsend.md`, `docs/research/phone-uploads.md`): resumable uploads, the
    LocalSend receiver, the phone upload page.
  - **Artwork document, geometry, renderer** (`docs/artwork-document.md`, `docs/geometry-and-quality.md`,
    `docs/rendering-spec.md`): the render hash reads `render_identity()`, so a schema addition moves no
    cache, TV or outdated badge. Frame styles carry `edge_shadow` (drawn last) and `bevel`.
  - **Editor** (`docs/simple-editor.md`): Konva canvas; **Simple** edits the optional `composition` block
    (a recipe + parameters, `weights` included) that the mirrored solver turns into slots, and the server
    re-solves on every save; **Advanced** is free-form and sets `detached`. 17 recipes at `GET /recipes`.
  - **Templates** (`docs/templates.md`): a layout is a recipe + parameters; styles and layouts have CRUD,
    "Save as", `.tf*.json` files, apply-template with the outdated badge, and push update (dry run +
    `pre_template_update` snapshots). `restyle`/`relayout` are pure and mirrored.
  - **Organization** (`docs/organization.md`): one filter AST (`domain/filters.py` validates,
    `services/library.py` compiles) behind the filter bar, `POST /artworks/query` and smart collections;
    collections as a tree; FTS search; tags with categories, and an artwork **carries its photos' tags**
    (read, never copied); `place near` on the photos' GPS; the trash acts, then offers Undo. A photo leaves
    the inbox only when an artwork using it is marked **ready** (one-way).
  - **Export / import** (`docs/archive-format.md`): the `.tfarchive` is a ZIP of JSON + JSON Lines + the
    originals; staging → dry-run report → apply under `keep_mine | take_theirs | keep_both`; the CLI does
    the same without a browser.
  - **Hardening** (`docs/user-guide.md`, `docs/security.md`): `MAX_RENDER_PIXELS` (320 Mpx of distinct
    sources), AA in both themes, `/activity` for failed jobs, `frame-it service install`. Licence MIT.
  - **Name**: Frame It (package `frame_it`, command `frame-it`, env `FRAME_IT_*`) since 2026-10-06; the
    placeholder `the_frame_v2` is still **read** — `THE_FRAME_V2_*` env, its data dir, its archive
    format (`config.py`, `domain/archive.LEGACY_FORMATS`). Never write the old name anywhere new.
  - **TV** (`docs/tv-display.md`, measurements in `docs/research/tv-display.md`): the Frame's slideshow
    cannot be scoped to a subset, so a push **mirrors** the set (`keep_ours` spares our earlier
    uploads); a push is stop → select → start, uploads go in reverse (the TV lists newest first), and
    "Don't change" (`slideshow_minutes = 0`) rotates and deletes nothing. A TV is followed by MAC when its address changes. `FRAME_IT_FAKE_TV=1` drives it
    all without a TV.
  - **i18n**: English and French catalogs; server data (built-in style names, place names) stays as stored.
- **Not yet verified on hardware**: deleting foreign photos, whether the pairing token survives a TV power
  cut (hence "pair again" in the UI), discovery on the real LAN, following a TV that moved, a "Don't
  change" push. **Verified by the user** (2026-09-17): Android uploads (both pickers keep full quality, but
  Android zeroes GPS → no place), Docker image build/run/persistence.
- **Written with AI, and said so** (`README.md` *Written with AI*, `CONTRIBUTING.md`): keep the README's
  "checked on real hardware" list in step with the one above.

## Quick commands

| Task | Command |
|---|---|
| Install | `make install` (uv + pnpm) |
| Dev (API :8765 + Vite :5173) | `make dev` — open http://localhost:5173 |
| Everything that must pass | `make check` (ruff, ESLint, mypy strict, tsc, i18n keys, geometry conformance, pytest) |
| Geometry fixtures | `make conformance` (TS); regenerate from Python: `cd backend && CONFORMANCE_UPDATE=1 uv run pytest tests/unit/test_conformance.py` |
| Golden images | `make golden-update` after an intended pixel change (review PNGs, bump `RENDERER_VERSION`) |
| Render budgets + peak RSS | `cd backend && uv run python ../scripts/bench_render.py` |
| Library budgets (seeded 10k) | `cd backend && uv run python ../scripts/bench_library.py --data-dir /tmp/seed` |
| Dependency audit | `cd frontend && pnpm audit`; backend: `uv export --no-emit-project --no-dev --format requirements.txt -o /tmp/r.txt && uv run --with pip-audit pip-audit -r /tmp/r.txt` |
| Run at login | `uv run frame-it service install` (`--show` prints the unit; `status`, `uninstall`) |
| Seed a big library (Phase 9 AC) | `cd backend && uv run python ../scripts/seed_library.py --data-dir /tmp/seed --artworks 10000` |
| Export / import a library | `uv run frame-it export -o lib.tfarchive` · `uv run frame-it import lib.tfarchive --dry-run` |
| Editor E2E against a copy of the library | `cp -r .dev-data /tmp/e2e && cd backend && FRAME_IT_DATA_DIR=/tmp/e2e FRAME_IT_PORT=8799 uv run frame-it serve`, then `cd frontend && FRAME_IT_BACKEND=http://127.0.0.1:8799 pnpm dev --port 5199` |
| Backend tests only | `cd backend && uv run pytest` (add `-k name`) |
| TV pages without a TV | `FRAME_IT_FAKE_TV=1 uv run frame-it serve` (one in-memory `FakeTv`; never reaches a real TV) · `uv run frame-it tv scan` lists the TVs on the LAN |
| Regenerate API types + `docs/schemas/` (after any API/document schema change) | `make gen-api` |
| Production build + serve | `make serve` (frontend built into `backend/src/frame_it/static`) |
| CLI | `uv run frame-it --help` (`serve`, `doctor`, `setup-code`, `openapi`, `schemas`, `db upgrade`, `cache clear`, `service`, `export`, `import`, `tv`, `version`) |
| New migration | edit `db/models.py`, then `cd backend && uv run python -m frame_it.db.migrate "message"`, rename to `NNNN_message.py`, replace custom types by `sa.String` |
| Docker | `make docker`; `docker/compose.yaml` (set `FRAME_IT_PUBLIC_URL`) |

NixOS without nix-ld: the uv-installed `ruff` binary cannot run → `make lint RUFF=ruff` with a Nix ruff.

## Repo map

| Path | Responsibility |
|---|---|
| `backend/src/frame_it/app.py` | App factory: context, routers, SPA serving, lifespan (jobs, setup code) |
| `…/config.py` | Settings (env `FRAME_IT_*` > `<data_dir>/config.toml` > defaults), LAN IP, allowed hosts |
| `…/context.py` | `AppContext` service container (`app.state.ctx`) |
| `…/api/` | Thin routers + `schemas.py` (Pydantic API models = OpenAPI source) + `deps.py` (auth deps); `templates.py` = styles/layouts CRUD, usage, push update, template files; `library.py` = tags + collections + `POST /filters/validate`; `trash.py` = preview/trash/restore/purge; `archive.py` = exports + imports; `jobs.py` = the activity centre (list/retry/dismiss) |
| `…/auth/` | `principal.py` (cookie/localhost → role), `middleware.py` (Host/CSRF/headers), `ratelimit.py` |
| `…/services/` | Use cases: `devices`, `uploads`, `ingest`, `photo_copies` (merge copies), `localsend`, `photos` (incl. the batch meta of an upload, duplicates too; `around` = taken the same days or at the same spot), `tags` (bulk tagging, categories, unused, the own/inherited counts), `places` (the derived country → region → place view, the `place near` picker's search), `geocode` (reverse at ingest, search by name), `artworks` (create/save/snapshots), `render` (cache, jobs, region), `templates` (presets, CRUD, template files, artwork defaults; the artwork-writing half — apply/push update — is in `artworks`), `recipes` (the bundled composition catalogue, no DB), `colors` (photo palette, swatches, curated presets), `library` (the filter compiler + the artwork listing), `collections` (tree, items, smart filters), `search` (FTS index, versioned: `INDEX_VERSION`), `trash` (soft delete, cascade, restore, purge), `archive_export` (the `.tfarchive` writer + the rendered-image ZIP), `archive_import` (receive, validate, classify), `archive_apply` (the import transaction and its id maps), `display` (display targets: pair, status, and the push that mirrors a set onto a TV), `jobs_admin` (what failed, and running it again) |
| `…/domain/` | PURE: `document` (artwork document v1 + the `composition` block + reference checks), `geometry`, `quality` (tiers), `placement`, `constraints` (editor solver §7.3), `alternatives` (§7.6), `arrange` (align/distribute/new slot, §7.7), `composition` (recipe trees, the parametric solver and `apply` = what it writes into a document, `docs/simple-editor.md` §3), `templates` (style/layout docs, `restyle`/`relayout`/save-as, `build_composition_document`), `filters` (the library filter AST, `docs/data-model.md` §5.2), `geo` (great-circle distance, the `place near` bounding box), `archive` (the archive's records, file layout and member-name safety, `docs/archive-format.md`) |
| `…/imaging/` | `sniff` (magic bytes), `decode` (the only pixel access), `metadata` (EXIF/ICC), `fingerprint` (hash ignoring EXIF), `capabilities`, `render` (the renderer), `palette` (OKLab k-means), `assets` (fonts/textures catalog) |
| `…/assets/` | `geonames/`, `fonts/` (OFL, `scripts/build_fonts.py`), `textures/` (CC0, `scripts/generate_textures.py`), `presets/` (built-in styles/layouts + `recipes.json`) |
| `…/tv/` | Samsung Frame art channel: `client.py` (`TvClient` + `SamsungTvClient` over `samsungtvws`, pairing, `SLIDESHOW_MINUTES`, `normalize_mac`), `discovery.py` (SSDP + /24 sweep of `:8001/api/v2/`, `subnet_prefix`, `find_by_mac`), `fake.py` (`FakeTv` — the firmware's quirks, used by every test and by `FRAME_IT_FAKE_TV`). The push itself is `services/display.py` (`plan_push` pure, `push`, `plan`, `_with_tv` = follow by MAC) |
| `…/localsend/` | LocalSend v2 receiver: `app.py` (protocol routes, own TLS port), `discovery.py` (multicast), `identity.py` (cert/fingerprint), `client.py` (outgoing TLS), `runner.py` (lifespan); logic in `services/localsend.py`, admin API `api/localsend.py` |
| `…/jobs/` | `queue.py` persistent in-process job queue (lanes, retries, coalescing); `gate.py` render concurrency |
| `…/events.py` | Thread-safe SSE broker (`/api/v1/events`) |
| `…/db/` | `models.py`, `session.py` (WAL), `migrate.py`, `migrations/versions/` |
| `…/storage.py` | Data-dir layout (originals, cache, uploads) |
| `…/service.py` | Generates this machine's systemd unit / launchd plist (`frame-it service`) |
| `…/assets/geonames/` | Offline place dataset (built by `scripts/build_geonames.py`, CC BY 4.0) |
| `backend/tests/` | `unit/`, `api/`, `golden/` (reference PNGs in `refs/`); fixtures & helpers in `conftest.py` (`make_jpeg`, `pair`, `upload_bytes`) |
| `conformance/geometry/` | Shared JSON fixtures: Python domain ↔ `frontend/src/editor/core` (`render.json`: the two renderer constants the canvas mirrors) |
| `scripts/` | `build_geonames.py`, `build_fonts.py`, `generate_textures.py`, `bench_render.py` (time **and** peak RSS), `bench_library.py` (§8.6 budgets), `seed_library.py`, `render_parity/` (S3 page), `tv_probe.py` (S5 spike: probes the Frame's art channel, `--fake` self-tests it without hardware — `docs/research/tv-display.md`) |
| `frontend/src/api/` | `client.ts` (openapi-fetch + `ApiError`), `queries.ts` (TanStack Query hooks), `events.ts` (SSE), generated `schema.d.ts` |
| `frontend/src/app/` | `router.tsx`, `AuthGate.tsx` (role routing), `Shell.tsx` (sidebar), `commands.ts` (shortcuts/palette registry), `theme.ts` |
| `frontend/src/editor/core/` | PURE TS mirror of `domain/` (`geometry`, `quality`, `placement`, `constraints`, `alternatives`, `arrange`, `composition`, `templates`, `bevel` = the renderer's bevel shades) + `snapping.ts`, `bounds.ts` and `splits.ts` (client-only: the gaps of a Fill layout, a drag in shares, a cell's row/column) and `document.ts` (the document with every optional field filled in); relative imports with `.ts` extension (run by Node in `frontend/scripts/conformance.ts`) |
| `frontend/src/editor/` | `EditorPage.tsx` (layout, shortcuts, review queue), `store.ts` (working document, undo/redo on Immer patches, autosave + conflicts), `operations.ts` (pure document mutations: how a change propagates), `actions.ts` (what the UI calls), `TvPreview.tsx` |
| `…/editor/canvas/` | `EditorStage.tsx` (Konva stage, one pointer pipeline for every gesture, overlays), `SlotNode.tsx` (bands, photo, shadows), `CaptionNode.tsx`, `SelectionOverlay.tsx` (outlines + transform handles), `hit.ts` (rotation-aware hit tests, handle maths), `texture.ts`, `fonts.ts`, `useOrientedImage.ts` |
| `…/editor/panels/` | `SimplePanel` (the parametric editor, §6.2) + `RecipePicker` (schemas drawn by the solver), `SlotsPanel` (z-order, add/remove, photos), `PhotoPicker`, `ArrangePanel` (align/distribute), `CaptionsPanel` + `CaptionTypography` (shared with Simple), `FramingPanel`, `StylePanel`, `ColorField` (picker + swatches + palette + presets), `AlternativesPanel`, `Loupe`, `QualityBadge`, `InfoSheet`, `ShadowFields` (shared with the template editor), `Controls` (`NumberField`, `PercentField`: every slider has a typed twin) |
| `frontend/src/features/` | `display/` (the TV page + "Show on the TV"), `activity/` (failed jobs + retry), `archive/` (export dialog, import report + policies), `upload/` (queue engine `uploadStore.ts`, tray, drop zone), `photos/` (grid, selection, drawer; "Create artworks" from any photo), `inbox/`, `artworks/` (page, grid, viewer, create dialog), `templates/` (page, editors, push update, `.tf*.json` files), `library/` (the filter AST + chip bar, `PlacePicker`), `collections/` (page, tree, create/edit dialog), `trash/` (page, the cascade dialog, `useTrashWithUndo` / `useDeletePhotos`), `tags/` (picker, the tri-state `TagMenu`, category grouping, the manager page + `PlacesView`), `devices/`, `auth/`, `mobile/` (upload + read-only browse), `settings/`, `localsend/` (the editor lives in `src/editor/`, not here) |
| `…/features/display/` | `DisplayPage` (TV cards, scanning Add-TV dialog, Send = dry run then confirm), `ShowOnTvDialog` (dry-run numbers, collapsed rotation, drafts, the remove-previous and foreign checkboxes only when there are some), `SlideshowSettings` (interval incl. "Don't change", *In order \| Shuffle*), `PushTray` (sidebar progress + summary toast), `pushStore.ts` (`display.progress` outside React), `summary.ts` (result/phase sentences) |
| `frontend/src/shared/` | UI primitives (`ui/`, incl. `Toaster.tsx`), `toast.ts` (the store, outside React), `problem.ts` (`problemMessage`), `format.ts`, `cn.ts`, `dnd.ts` (the MIME types our own drags carry) |
| `frontend/src/i18n/` | i18next setup (Settings choice, else the browser's language); strings in `locales/en/common.json` and `locales/fr/common.json` |
| `docs/` | Plan, specs, ADRs (`adr/`), research findings (`research/`), progress |

## Architecture essentials

- Layers: `api` (HTTP only) → `services` (transactions, rules) → `domain` (pure) / `imaging` / `db`. Jobs call services.
- Artwork flow: `POST /artworks` (photos + style + a layout or a composition → `build_composition_document`) or `PUT /artworks/{id}/document`
  (`If-Match: <document_version>`) → validate (structure + references) → derived columns + `artwork_photos` →
  commit → coalesced `render` job → `cache/renders/<id>/<render_hash>.png` → SSE `artwork.rendered`. Render
  endpoints render on demand; URLs carry `?v=<render_hash>` for immutable caching.
- `db.session()` is a transactional context manager (commit/rollback). Routers get a request-scoped session via
  `DbSession`; long work runs in jobs or `run_in_threadpool`.
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
- Frontend: server state only in TanStack Query; SSE invalidates `["photos"]`; upload queue is a Zustand store
  outside React (hash → open/resume → chunks with retry → wait for SSE, polling fallback).
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
`docs/gotchas.md` (the subsystem-specific ones) · `CONTRIBUTING.md` · `LICENSE` (MIT)

## Gotchas

**The subsystem-specific ones live in [`docs/gotchas.md`](docs/gotchas.md) — read the section for
whatever you are touching before you touch it.** These few bite whatever you are working on:

- Geometry change ⇒ change Python **and** TS, add a case to `CASES` in `tests/unit/test_conformance.py`,
  regenerate fixtures, check the new expected values by hand.
- The **same document** rendering to different pixels ⇒ bump `RENDERER_VERSION` (render hash) and
  `make golden-update`; asset file changes ⇒ bump the manifest `version`. Golden sources are PNG.
- A **new optional document field** ⇒ no bump, but list it in `_LATER_DEFAULTS` (`domain/document.py`)
  or every artwork's render hash changes: caches dropped, the whole set re-uploaded to the TV.
- Alembic autogenerate proposes dropping the FTS5 `search_index*` tables: delete those lines by hand.
- **Editor performance is a correctness issue**: one React render + canvas redraw per mouse event makes the tab
  unresponsive for tens of seconds (the event queue outruns the renderer). Crop dragging, stage panning and the
  loupe's pointer all batch into `requestAnimationFrame` in `EditorStage`; keep any new gesture that way.
- **Verifying in a browser is expected but never blocking** (`docs/PLAN.md` §13.6): the Chrome-extension
  harness cannot drive this app (the SSE stream keeps the page from ever going idle, so `executeScript`,
  screenshots and `--dump-dom` time out). CDP works: headless `chromium --remote-debugging-port` +
  `Runtime.evaluate` against the production build on trusted localhost. Read results back through the
  **API**, not off the screen — a Konva canvas can capture black although its pixels are correct. No
  harness ⇒ verify what you can and write in `docs/progress.md` what was not driven in a browser.
- `make format` runs prettier over the whole frontend, but `make lint` only runs ESLint: a lot of editor
  files have never been prettier-formatted, so `make format` rewrites ~20 files you did not touch. Format
  your own files, then `git checkout --` the rest.
- `make check` neither lints nor runs `scripts/` (ruff covers `backend/src` and `backend/tests` only), so a
  broken script goes unnoticed: run a script you changed.
- Dev over the Vite proxy is **not** trusted as localhost (`xfwd` adds `X-Forwarded-For`, invariant 5): the
  first load asks for the setup code printed in the server log. Point Vite at another backend with
  `FRAME_IT_BACKEND=http://127.0.0.1:<port>`.
- `pkill -f "frame-it serve"` also matches your own shell command line: use `pkill -f "[t]he_frame_v2 serve"`.
- TypeScript stays on major 6 (`^6.0.3` in `frontend/package.json`) because typescript-eslint did not support
  7.x when this was written: check its support before moving to 7.
