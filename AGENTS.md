# AGENTS.md — the_frame_v2

> Entry point for coding agents and contributors. **Read this first, trust it, and update it in the same change
> as the code it describes** (rules: `docs/PLAN.md` §3). Keep it under ~300 lines; link to `docs/` for details.

## Purpose & status

Self-hosted web app to prepare pictures for a 4K art-mode TV (Samsung The Frame, 3840×2160): phone uploads in
full quality over the LAN, pixel-perfect framing/compositions, collections, export/import.

- **Current state (2026-09-22): Phases 0–7 done** — foundations, device auth &
  pairing, resumable uploads, LocalSend receiver, ingest, Photos + Inbox UI, phone upload page; artwork
  document + geometry (Python/TS mirrored), pyvips renderer, built-in styles/layouts, artworks API;
  **editor** (Konva canvas, crop/placement/locks with the constraint solver, colour tools, alternatives,
  loupe, TV preview, undo/autosave, review queue) and **multi-photo compositions** (slots panel with
  z-order, photo picker, free-form move/resize/rotate with smart guides, multi-selection +
  align/distribute, caption editing).
- **Phase 7 (2026-09-21/22, `docs/simple-editor.md`)**: parametric compositions end to end — the
  optional `composition` block, the pure mirrored **solver**, the 17-entry recipe catalogue and
  `GET /recipes`; **server authority** (`composition.apply` writes §3.7's table, `PUT document`
  re-solves on every save, `POST /artworks` takes a composition and is parametric by default); the
  **Simple panel** (picker drawn by the solver, Balance, format chips, bounded Outer/Gap sliders,
  reframe/zoom, swap, background, border, caption); and the **`[Simple] [Advanced ᴮᴱᵀᴬ]` switch**
  with `detached` and a confirmed, undoable **Re-apply layout**.
- **Next: Phase 8** (`docs/PLAN.md` §14): templates rebuilt around recipes — a saved layout becomes
  recipe + parameters, and `settings.artwork_defaults` should name a style + recipe + format
  instead of a style + layout. The create dialog still sends a `layout_id`, so artworks made from
  the Photos page are hand-built until a layout is picked in the editor; that moves with it.
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
| Editor E2E against a copy of the library | `cp -r .dev-data /tmp/e2e && cd backend && THE_FRAME_V2_DATA_DIR=/tmp/e2e THE_FRAME_V2_PORT=8799 uv run the_frame_v2 serve`, then `cd frontend && THE_FRAME_V2_BACKEND=http://127.0.0.1:8799 pnpm dev --port 5199` |
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
| `…/services/` | Use cases: `devices`, `uploads`, `ingest`, `photo_copies` (merge copies), `localsend`, `photos`, `tags`, `geocode`, `artworks` (create/save/snapshots), `render` (cache, jobs, region), `templates` (presets, artwork defaults), `recipes` (the bundled composition catalogue, no DB), `colors` (photo palette, swatches, curated presets) |
| `…/domain/` | PURE: `document` (artwork document v1 + the `composition` block + reference checks), `geometry`, `quality` (tiers), `placement`, `constraints` (editor solver §7.3), `alternatives` (§7.6), `arrange` (align/distribute/new slot, §7.7), `composition` (recipe trees, the parametric solver and `apply` = what it writes into a document, `docs/simple-editor.md` §3), `templates` (style/layout docs, `build_document`) |
| `…/imaging/` | `sniff` (magic bytes), `decode` (the only pixel access), `metadata` (EXIF/ICC), `fingerprint` (hash ignoring EXIF), `capabilities`, `render` (the renderer), `palette` (OKLab k-means), `assets` (fonts/textures catalog) |
| `…/assets/` | `geonames/`, `fonts/` (OFL, `scripts/build_fonts.py`), `textures/` (CC0, `scripts/generate_textures.py`), `presets/` (built-in styles/layouts + `recipes.json`) |
| `…/localsend/` | LocalSend v2 receiver: `app.py` (protocol routes, own TLS port), `discovery.py` (multicast), `identity.py` (cert/fingerprint), `client.py` (outgoing TLS), `runner.py` (lifespan); logic in `services/localsend.py`, admin API `api/localsend.py` |
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
| `frontend/src/editor/core/` | PURE TS mirror of `domain/` (`geometry`, `quality`, `placement`, `constraints`, `alternatives`, `arrange`, `composition`) + `snapping.ts` and `bounds.ts` (client-only) and `document.ts` (the document with every optional field filled in); relative imports with `.ts` extension (run by Node in `scripts/conformance.ts`) |
| `frontend/src/editor/` | `EditorPage.tsx` (layout, shortcuts, review queue), `store.ts` (working document, undo/redo on Immer patches, autosave + conflicts), `operations.ts` (pure document mutations: how a change propagates), `actions.ts` (what the UI calls), `TvPreview.tsx` |
| `…/editor/canvas/` | `EditorStage.tsx` (Konva stage, one pointer pipeline for every gesture, overlays), `SlotNode.tsx` (bands, photo, shadows), `CaptionNode.tsx`, `SelectionOverlay.tsx` (outlines + transform handles), `hit.ts` (rotation-aware hit tests, handle maths), `texture.ts`, `fonts.ts`, `useOrientedImage.ts` |
| `…/editor/panels/` | `SimplePanel` (the parametric editor, §6.2) + `RecipePicker` (schemas drawn by the solver), `SlotsPanel` (z-order, add/remove, photos), `PhotoPicker`, `ArrangePanel` (align/distribute), `CaptionsPanel`, `FramingPanel`, `StylePanel`, `ColorField` (picker + swatches + palette + presets), `AlternativesPanel`, `Loupe`, `QualityBadge`, `InfoSheet`, `Controls` |
| `frontend/src/features/` | `upload/` (queue engine `uploadStore.ts`, tray, drop zone), `photos/` (grid, selection, drawer; "Create artworks" from any photo), `inbox/`, `artworks/` (page, viewer, create dialog), `devices/`, `auth/`, `mobile/`, `settings/`, `tags/`, `localsend/` (the editor lives in `src/editor/`, not here) |
| `frontend/src/shared/` | UI primitives (`ui/`), `format.ts`, `cn.ts`, `dnd.ts` (the MIME types our own drags carry) |
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
  Already-sent files are not transferred again (no token; when nothing is new, the smallest one is transferred
  and dropped so the app still shows a transfer), and the web tray (`localsend.*` events) tells what happened.
- Ingest flow: `POST /uploads` → `PATCH` chunks (`Upload-Offset`) → SHA-256 verified → `ingest` job → photo in
  inbox → SSE `photo.ingested` (or `photo.ingest_failed` with a problem code).
- Frontend: server state only in TanStack Query; SSE invalidates `["photos"]`; upload queue is a Zustand store
  outside React (hash → open/resume → chunks with retry → wait for SSE, polling fallback).
- Compositions (Phase 7, `docs/simple-editor.md`): an optional `composition` block holds a recipe id
  plus parameters (balance, outer, gutter, format, border, caption). `domain/composition.solve` turns it
  into cells — **footprints** (photo rect + border) so `gutter`/`outer` describe what the eye sees, then
  deflated by the border into the slot rects. The block is the source of truth while `detached = false`:
  `services/artworks.validated()` parses, checks references, then **re-solves** (`composition.apply`),
  so no client can persist a rect the composition does not imply. `POST /artworks` without a
  `layout_id` is parametric; with one it builds a Phase 6 document carrying no block.
- Editor selection: `selectedSlotIds` (Shift/Ctrl-click adds; the **last** id is the *primary* one the
  property panels edit) and `selectedCaptionId` are exclusive. Framing and cropping act on the primary slot,
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
7. All user-facing strings via i18n (`t("…")`); errors carry a stable `code` translated as `errors.<code>`.
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
`docs/simple-editor.md` (Phase 7: compositions, recipes, the solver) ·
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
- LocalSend app: files without a token are hidden from its transfer list, and a `prepare-upload` accepting no
  file at all (204) shows nothing — no transfer screen, straight back to its home screen; 403/409/429 show fixed texts and other statuses an "Error ⓘ" (we avoid all of them for
  already-sent photos: the transfer must look normal — `docs/localsend.md` "Already-sent photos").
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
- **Editor performance is a correctness issue**: one React render + canvas redraw per mouse event makes the tab
  unresponsive for tens of seconds (the event queue outruns the renderer). Crop dragging, stage panning and the
  loupe's pointer all batch into `requestAnimationFrame` in `EditorStage`; keep any new gesture that way.
- Canvas shadows allocate a surface covering the shape **and** its shadow: never draw the inner-shadow ring far
  away (S3's trick froze the tab). It is drawn around the layer and clipped — `docs/rendering-spec.md` §8.2.
- Radix layers (dialog, popover) see `Escape` in the **capture** phase on the document while the command
  registry (tinykeys) listens on `window` (bubble): a layer must `stopPropagation` in `onEscapeKeyDown`, or
  `Escape` closes the popover *and* runs the page's own `Escape` command (it used to leave the editor).
- Konva does not put a `Text` node's `y` on the line top (it translates by `(ascent − descent) / 2 +
  lineHeight / 2` and draws `alphabetic`), and its font shorthand includes the weight: caption placement and
  measurement go through `editor/canvas/fonts.ts`, which replicates both — the renderer's baseline rule does
  **not** apply on the canvas (`docs/research/render-parity.md`).
- **Verifying in a browser is expected but never blocking** (`docs/PLAN.md` §13.6): the Chrome-extension
  harness can no longer drive this app (the SSE stream keeps the page from ever going idle, so `executeScript`,
  screenshots and `--dump-dom` all time out). CDP works: headless `chromium --remote-debugging-port` +
  `Runtime.evaluate` against the production build served by the backend on trusted localhost. Check the saved
  document through the API rather than screenshots — a Konva canvas can capture **black** although its pixels
  are correct. No harness ⇒ verify what you can (`make check`, conformance, API, render endpoints) and say in
  `docs/progress.md` what was not driven in a browser.
- The composition solver rounds **edges**, never sizes: a 3:2 cell can come out 2387×1592 rather than
  ×1591, and a cell's aspect is only exact to `1 + r` px of width (two rounded edges per side). Assert
  `|w − a·h| ≤ 1 + a`, not `≤ 1`.
- The solver's over-constrained recovery is a **fixed ladder** (gutters ×10/10…0/10, then `outer`), not a
  bisection: the two solvers have to agree bit for bit, and `i/10` gives the same doubles in both
  languages. Keep it that way — and keep the recipe catalogue the *one* source both read
  (`conformance.ts` loads `backend/…/presets/recipes.json` straight off disk).
- **An edit detaches a composition exactly when `apply` would overwrite it** (§3.7's table): slot
  geometry, bands, lock, crop ratio, margins, placement and a caption's position do; the shadow,
  the mat and a caption's typography do not. Orienting a photo, re-ordering slots and changing the
  photo count **re-solve** instead. Put any new editor action on one of those three lists, or it
  will either eat the user's edit on the next save or drop the layout link for nothing.
- A caption's text belongs to the block: an edit on the canvas writes `composition.caption.text`,
  not just the caption, or the next solve takes it back.
- The Simple panel's sliders bisect on **`solve_strict`**, never on `solve`: the relaxation ladder
  answers "roomy" for an over-constrained value by laying the block out with *other* gutters, so a
  bisection on `solve` silently returns a bound that does not hold.
- A reframe inside a cell must zoom with the quality lock **off** (`relock` puts §3.7's lock back):
  under `no_upscale` the constraint solver shrinks the *slot* as soon as the crop gets smaller than
  it (§7.3), which fights the composition for ownership of the rect.
- Attaching a composition to a hand-built artwork moves its caption's text into the block: from
  then on the block owns `captions` (§3.7), so anything left behind is deleted by the next solve.
  Same reflex for any new field the block starts owning.
- Adding or removing a slot while a block is attached must re-pick the recipe
  (`recipeFollowsPhotoCount`) or the save fails with `recipe_slot_count`: the count comes from the
  photos, and past 6 photos the block detaches.
- A crop whose width **and** height are rounded independently can fall just outside
  `aspect_consistent` — the tolerance is exactly the budget of two roundings. `refit_crop` derives
  the height from the width and the target ratio for that reason: the server must never re-solve a
  document into one it would itself reject (invariant 11).
- `composition.apply` (↔ `applyComposition`) is the **only** writer of `docs/simple-editor.md` §3.7:
  the server calls it on every save, the editor will call it to preview. Change it in both languages
  and add a `composition_apply` conformance case — those fixtures compare whole documents, so a field
  the two sides disagree on shows up there rather than in the browser.
- `POST /artworks` **without** `layout_id` is now parametric (a recipe, no `origin_layout_id`); an
  explicit `layout_id` keeps the Phase 6 path. `settings.artwork_defaults.layout_id` no longer
  decides anything for a new composition artwork (Phase 8 moves it to a recipe).
- **A ratio format carries its orientation**: `4:3` and `3:4` are different formats and the cells
  take the ratio as written. Only `auto` (the 1-cell recipe) turns the landscape form the photo's
  way. The recipes' `landscape`/`portrait` cell kinds are inert as a result.
- `composition.cell_formats` overrides the format cell by cell (`null` inherits, `original` = the
  photo's own aspect, never `fill` — which has no per-cell aspect at all). `format: "original"`
  itself works at **any** photo count: each cell takes its own photo's aspect.
- `zoom_crop` derives the crop's height from its width and the **rect's** aspect. Scaling the two
  sides on their own drifts, and so does re-reading the aspect off the rounded crop each step —
  once it has drifted, `resize_crop` resizes the *slot* to match. That is the whole "zoom out and
  the frame changes size" bug, and it needs both halves: the mirrored rule here, and the editor
  routing the **wheel** through the same bounded 1×–8× scale as the slider, so a scroll can never
  take the crop somewhere the slider cannot.
- An in-app HTML drag must stamp itself (`shared/dnd.ts`): dragging a photo chip is dragging an
  `<img>`, which Chrome also offers to the page as a *file*, so the window-wide upload overlay lit
  up on every cell swap. `hasFiles` ignores a drag carrying one of our MIME types.
- A recipe cell of kind `auto` means *the format turned the photo's way* (portrait photo + `3:2` → a 2:3
  cell), **not** the photo's own aspect — that is what the `original` format is for. Reading §3.5 the
  other way makes every ratio chip a no-op for a single photo.
- `make format` runs prettier over the whole frontend, but `make lint` only runs ESLint: a lot of editor
  files have never been prettier-formatted, so `make format` rewrites ~20 files you did not touch. Format
  your own files, then `git checkout --` the rest.
- Under `fit_in_mat` + `native` the margins **are** the crop: `fit_in_mat` re-derives the crop from the
  available area on every margin edit (both directions), and a crop edit re-derives the margins. Deriving it
  only when the crop overflowed made margins one-way (the photo never grew back — `docs/geometry-and-quality.md`
  §7.4).
- Editor number fields keep the typed text while focused (`panels/Controls.tsx`) and never snap it: the §7.5
  tolerance is 8 *screen* px, so a typed margin was swallowed by the nearest stop. Sliders still snap.
- Radix focuses the first tabbable element of a dialog, which is the close cross: a dialog whose `Enter`
  should confirm passes `onOpenAutoFocus` and focuses its submit button (`CreateArtworksDialog`).
- Query results are new objects on every render: never feed them straight into a store (`openArtwork` only
  writes `sizes` when a photo id is actually new, or the editor re-renders in a loop).
- The React Compiler lint forbids `setState` in an effect body: derive the value during render instead (the
  stage view falls back to `fit()`, image/texture hooks read a module cache and only `setState` in the async
  callback).
- The editor's canvas gestures all go through **one** pointer pipeline in `EditorStage` (mode in a ref, flushed
  per animation frame): panning, cropping, moving/resizing/rotating a slot, moving a caption. Handles are drawn
  by `SelectionOverlay` but hit-tested in `hit.ts` — they are not listening Konva nodes.
- Konva binds its mouse listeners **below** the container div, so a synthetic event must be dispatched on the
  `<canvas>` (or Konva's content div), never on the outer `[data-tool]` element — and tinykeys drops any
  `KeyboardEvent` without a `code`, so synthetic shortcuts need `{ key, code }`. Both cost an E2E session.
  The dev server is not the place for this: over the Vite proxy the app is not trusted as localhost (below).
- A slot without a photo is a placeholder: `quality_lock = free` and a crop the size of its rect. Filling it
  takes `no_upscale` back, or an emptied slot would silently allow upscaling afterwards.
- "Same size" fits each slot *inside* the reference box: the solver's `resize_slot` has **cover** semantics
  (§7.3), so asking for the reference size directly makes the other slots bigger than it.
- Dev over the Vite proxy is **not** trusted as localhost (`xfwd` adds `X-Forwarded-For`, invariant 5): the
  first load asks for the setup code printed in the server log. Point Vite at another backend with
  `THE_FRAME_V2_BACKEND=http://127.0.0.1:<port>`.
