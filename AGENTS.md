# AGENTS.md — the_frame_v2

> Entry point for coding agents and contributors. **Read this first, trust it, and update it in the same change
> as the code it describes** (rules: `docs/PLAN.md` §3). Keep it under ~300 lines; link to `docs/` for details.

## Purpose & status

Self-hosted web app to prepare pictures for a 4K art-mode TV (Samsung The Frame, 3840×2160): phone uploads in
full quality over the LAN, pixel-perfect framing/compositions, collections, export/import.

- **Current state (2026-09-23): Phases 0–9 done** — foundations, device auth &
  pairing, resumable uploads, LocalSend receiver, ingest, Photos + Inbox UI, phone upload page; artwork
  document + geometry (Python/TS mirrored), pyvips renderer, built-in styles/layouts, artworks API;
  **editor** (Konva canvas, crop/placement/locks with the constraint solver, colour tools, alternatives,
  loupe, TV preview, undo/autosave, review queue) and **multi-photo compositions** (slots panel with
  z-order, photo picker, free-form move/resize/rotate with smart guides, multi-selection +
  align/distribute, caption editing).
- **Phase 7 (`docs/simple-editor.md`)**: parametric compositions — the optional `composition`
  block, the pure mirrored **solver**, the 17-entry recipe catalogue (`GET /recipes`), **server
  authority** (`composition.apply` writes §3.7's table, `PUT document` re-solves on every save),
  the **Simple panel**, and the `[Simple] [Advanced ᴮᴱᵀᴬ]` switch with `detached`.
- **Phase 8 (`docs/templates.md`)**: templates rebuilt around recipes — **a layout is a recipe +
  parameters** (migration `0004` dropped the absolute-rect code); full CRUD for both kinds,
  "Save as" from an artwork, `.tf*.json` files, a Templates page, `apply-template` with the
  origin/outdated badge, and **push update** (dry run + `pre_template_update` snapshots).
  `restyle`/`relayout` are pure and mirrored (`conformance/geometry/templates.json`).
- **Phase 9 (2026-09-23, `docs/organization.md`)**: organization — the **filter AST**
  (`domain/filters.py` validates, `services/library.py` compiles) shared by the filter bar,
  `POST /artworks/query` and smart collections; **collections** as a tree (REAL `position`,
  recursive-CTE subtree, cycle + depth checks, manual item order, DnD everywhere); the **tag
  manager** (rename/recolour/merge/delete with per-kind counts); **FTS search** kept in sync by
  `services/search.py` and rebuilt when empty; the **trash** (batch soft delete, a cascade dialog
  choosing between trashing the artworks and emptying their slots, restore by batch, daily +
  manual purge that frees originals and render caches); Favorites view, the heart in the grid and
  the editor (`f`), and read-only mobile browsing at `/m/browse`. Migration `0005` adds the
  indexes those queries lean on; `scripts/seed_library.py` fills a 10k-item library.
- **Next: Phase 10** (`docs/PLAN.md` §14): export / import — archive writer and reader, dry-run
  report with conflict policies, rendered-image export, published JSON Schemas.
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
| Seed a big library (Phase 9 AC) | `cd backend && uv run python ../scripts/seed_library.py --data-dir /tmp/seed --artworks 10000` |
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
| `…/api/` | Thin routers + `schemas.py` (Pydantic API models = OpenAPI source) + `deps.py` (auth deps); `templates.py` = styles/layouts CRUD, usage, push update, template files; `library.py` = tags + collections + `POST /filters/validate`; `trash.py` = preview/trash/restore/purge |
| `…/auth/` | `principal.py` (cookie/localhost → role), `middleware.py` (Host/CSRF/headers), `ratelimit.py` |
| `…/services/` | Use cases: `devices`, `uploads`, `ingest`, `photo_copies` (merge copies), `localsend`, `photos`, `tags`, `geocode`, `artworks` (create/save/snapshots), `render` (cache, jobs, region), `templates` (presets, CRUD, template files, artwork defaults; the artwork-writing half — apply/push update — is in `artworks`), `recipes` (the bundled composition catalogue, no DB), `colors` (photo palette, swatches, curated presets), `library` (the filter compiler + the artwork listing), `collections` (tree, items, smart filters), `tags` (rename/merge/delete), `search` (FTS index), `trash` (soft delete, cascade, restore, purge) |
| `…/domain/` | PURE: `document` (artwork document v1 + the `composition` block + reference checks), `geometry`, `quality` (tiers), `placement`, `constraints` (editor solver §7.3), `alternatives` (§7.6), `arrange` (align/distribute/new slot, §7.7), `composition` (recipe trees, the parametric solver and `apply` = what it writes into a document, `docs/simple-editor.md` §3), `templates` (style/layout docs, `restyle`/`relayout`/save-as, `build_composition_document`), `filters` (the library filter AST, `docs/data-model.md` §5.2) |
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
| `frontend/src/editor/core/` | PURE TS mirror of `domain/` (`geometry`, `quality`, `placement`, `constraints`, `alternatives`, `arrange`, `composition`, `templates`) + `snapping.ts` and `bounds.ts` (client-only) and `document.ts` (the document with every optional field filled in); relative imports with `.ts` extension (run by Node in `scripts/conformance.ts`) |
| `frontend/src/editor/` | `EditorPage.tsx` (layout, shortcuts, review queue), `store.ts` (working document, undo/redo on Immer patches, autosave + conflicts), `operations.ts` (pure document mutations: how a change propagates), `actions.ts` (what the UI calls), `TvPreview.tsx` |
| `…/editor/canvas/` | `EditorStage.tsx` (Konva stage, one pointer pipeline for every gesture, overlays), `SlotNode.tsx` (bands, photo, shadows), `CaptionNode.tsx`, `SelectionOverlay.tsx` (outlines + transform handles), `hit.ts` (rotation-aware hit tests, handle maths), `texture.ts`, `fonts.ts`, `useOrientedImage.ts` |
| `…/editor/panels/` | `SimplePanel` (the parametric editor, §6.2) + `RecipePicker` (schemas drawn by the solver), `SlotsPanel` (z-order, add/remove, photos), `PhotoPicker`, `ArrangePanel` (align/distribute), `CaptionsPanel`, `FramingPanel`, `StylePanel`, `ColorField` (picker + swatches + palette + presets), `AlternativesPanel`, `Loupe`, `QualityBadge`, `InfoSheet`, `ShadowFields` (shared with the template editor), `Controls` |
| `frontend/src/features/` | `upload/` (queue engine `uploadStore.ts`, tray, drop zone), `photos/` (grid, selection, drawer; "Create artworks" from any photo), `inbox/`, `artworks/` (page, grid, viewer, create dialog), `templates/` (page, editors, push update, `.tf*.json` files), `library/` (the filter AST + chip bar), `collections/` (page, tree, create/edit dialog), `trash/` (page + the cascade dialog), `tags/` (picker + manager page), `devices/`, `auth/`, `mobile/` (upload + read-only browse), `settings/`, `localsend/` (the editor lives in `src/editor/`, not here) |
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
`docs/simple-editor.md` (Phase 7: compositions, recipes, the solver) · `docs/templates.md` (Phase 8) ·
`docs/organization.md` (Phase 9: tags, collections, filters, search, trash) ·
`docs/geometry-and-quality.md` · `docs/rendering-spec.md` · `docs/security.md` · `docs/archive-format.md` ·
`docs/schemas/` (generated) · `docs/adr/` · `docs/research/` · `NOTICE.md` (asset licenses)

## Gotchas

- TypeScript is pinned to `~6.0` (typescript-eslint does not support 7.x yet).
- TanStack Virtual triggers the React Compiler lint `incompatible-library`: suppressed in `PhotoGrid.tsx` on purpose.
- Registering commands with unstable dependencies used to cause a render loop; `useRegisterCommands` now keys
  on ids/shortcuts and calls the latest `run` via a ref — keep it that way.
- Resuming an upload without `meta` must keep the metadata of the original session (regression-tested).
- `Settings.allowed_hosts` must include the test host (`testserver`) in tests; production adds LAN IP/hostname.
- Android (any browser picker) zeroes GPS bytes in place, and the photo picker renames files to MediaStore
  ids (`1000125423.jpg`): never expect `gps_lat` from a phone web upload. A later copy with GPS/name is
  merged into the existing photo by content fingerprint (`docs/data-model.md`).
- LocalSend app: files without a token are hidden from its transfer list, and a `prepare-upload` accepting
  no file (204) shows nothing at all; 403/409/429 show fixed texts, other statuses an "Error ⓘ" — we avoid
  all of them for already-sent photos (`docs/localsend.md` "Already-sent photos").
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
- Radix layers see `Escape` in the **capture** phase on the document while tinykeys listens on `window`
  (bubble): a layer must `stopPropagation` in `onEscapeKeyDown`, or `Escape` closes the popover *and* runs
  the page's own `Escape` command.
- Konva does not put a `Text` node's `y` on the line top (it translates by `(ascent − descent) / 2 +
  lineHeight / 2`, draws `alphabetic`, and its font shorthand includes the weight): caption placement goes
  through `editor/canvas/fonts.ts`, which replicates both (`docs/research/render-parity.md`).
- **Verifying in a browser is expected but never blocking** (`docs/PLAN.md` §13.6): the Chrome-extension
  harness cannot drive this app (the SSE stream keeps the page from ever going idle, so `executeScript`,
  screenshots and `--dump-dom` time out). CDP works: headless `chromium --remote-debugging-port` +
  `Runtime.evaluate` against the production build on trusted localhost. Read results back through the
  **API**, not off the screen — a Konva canvas can capture black although its pixels are correct. No
  harness ⇒ verify what you can and write in `docs/progress.md` what was not driven in a browser.
- The composition solver rounds **edges**, never sizes: a 3:2 cell can come out 2387×1592, and a cell's
  aspect is only exact to `1 + r` px of width. Assert `|w − a·h| ≤ 1 + a`, not `≤ 1`.
- The solver's over-constrained recovery is a **fixed ladder** (gutters ×10/10…0/10, then `outer`), not
  a bisection: both languages must agree bit for bit, and `i/10` gives the same doubles. Keep the recipe
  catalogue the *one* source both read (`conformance.ts` loads `presets/recipes.json` off disk).
- **An edit detaches a composition exactly when `apply` would overwrite it** (§3.7's table): slot geometry,
  bands, lock, crop ratio, margins, placement and a caption's position do; the shadow, the mat and a
  caption's typography do not. Orienting a photo, re-ordering slots and changing the photo count
  **re-solve**. Put any new editor action on one of those three lists.
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
- A crop with width **and** height rounded independently can fall just outside `aspect_consistent`
  (the tolerance is exactly two roundings' budget). `refit_crop` derives the height from the width and
  the target ratio: the server must never re-solve a document into one it would reject (invariant 11).
- `composition.apply` (↔ `applyComposition`) is the **only** writer of `docs/simple-editor.md` §3.7:
  the server calls it on every save, the editor will call it to preview. Change it in both languages
  and add a `composition_apply` conformance case — those fixtures compare whole documents, so a field
  the two sides disagree on shows up there rather than in the browser.
- **Every new artwork is parametric** (Phase 8): a `layout_id` names a saved *recipe + parameters* and is
  recorded as `origin_layout_id`; fewer photos than cells leaves placeholders, more is `layout_slot_count`.
  The hand-placed creation path is gone — a document without a block only comes from detaching.
  `settings.artwork_defaults` is `{style_id, recipe_id, format}` (the last two nullable).
- **A template is copied on apply**; only a push update changes an existing artwork, snapshotting each
  one (`pre_template_update`) first — that snapshot *is* the undo. `restyle`/`relayout` are mirrored, so
  editor and server apply the same template and a drift shows up as a fixture diff.
- **The style's band and the layout's border are the same field** (`composition.border`, since the
  block owns `bands`): applying both applies the *layout first*, so the style wins, and
  `build_composition_document` lets the style's band fill in a border the composition does not name.
  A layout whose `border` is `null` means *no border*, not *unspecified*.
- **`restyle` never writes the style's `margins`**: under a block the margins are derived (§3.7) and
  re-dressing must not move a photo the user placed. A style's margins only matter to a hand-built
  document and to its own card preview.
- **A ratio format carries its orientation**: `4:3` and `3:4` are different formats and the cells
  take the ratio as written. Only `auto` (the 1-cell recipe) turns the landscape form the photo's
  way. The recipes' `landscape`/`portrait` cell kinds are inert as a result.
- `composition.cell_formats` overrides the format cell by cell (`null` inherits, `original` = the photo's
  own aspect, never `fill`). `format: "original"` works at **any** photo count.
- `zoom_crop` derives the crop's height from its width and the **rect's** aspect: scaling the sides on
  their own drifts, and a drifted crop makes `resize_crop` resize the *slot* ("zoom out and the frame
  changes size"). Both halves matter — the mirrored rule, and the editor routing the **wheel** through
  the same bounded 1×–8× scale as the slider.
- An in-app HTML drag must stamp itself (`shared/dnd.ts`): dragging a photo chip is dragging an
  `<img>`, which Chrome also offers to the page as a *file*, so the window-wide upload overlay lit
  up on every cell swap. `hasFiles` ignores a drag carrying one of our MIME types.
- A recipe cell of kind `auto` means *the format turned the photo's way* (portrait photo + `3:2` → a 2:3
  cell), **not** the photo's own aspect — that is what the `original` format is for. Reading §3.5 the
  other way makes every ratio chip a no-op for a single photo.
- `make format` runs prettier over the whole frontend, but `make lint` only runs ESLint: a lot of editor
  files have never been prettier-formatted, so `make format` rewrites ~20 files you did not touch. Format
  your own files, then `git checkout --` the rest.
- Under `fit_in_mat` + `native` the margins **are** the crop, in both directions: deriving the crop only
  when it overflowed made margins one-way, the photo never growing back (`docs/geometry-and-quality.md` §7.4).
- Editor number fields keep the typed text while focused (`panels/Controls.tsx`) and never snap it — the §7.5
  tolerance is 8 *screen* px, which swallowed typed margins. Sliders still snap.
- Radix focuses the first tabbable element of a dialog, which is the close cross: a dialog whose `Enter`
  should confirm passes `onOpenAutoFocus` and focuses its submit button (`CreateArtworksDialog`).
- Query results are new objects on every render: never feed them straight into a store (`openArtwork` writes
  `sizes` only when a photo id is actually new, or the editor re-renders in a loop).
- The React Compiler lint forbids `setState` in an effect body: derive the value during render instead (the
  stage view falls back to `fit()`, image/texture hooks read a module cache and only `setState` in the async
  callback).
- The editor's canvas gestures all go through **one** pointer pipeline in `EditorStage` (mode in a ref,
  flushed per animation frame). Handles are drawn by `SelectionOverlay` but hit-tested in `hit.ts` — they
  are not listening Konva nodes.
- Konva binds its mouse listeners **below** the container div, so a synthetic event must go to the
  `<canvas>` (or Konva's content div), never the outer `[data-tool]` element — and tinykeys drops a
  `KeyboardEvent` without a `code`, so synthetic shortcuts need `{ key, code }`. Both cost an E2E session.
- A slot without a photo is a placeholder: `quality_lock = free`, crop = its rect. Filling it takes
  `no_upscale` back, or an emptied slot would silently allow upscaling.
- "Same size" fits each slot *inside* the reference box: the solver's `resize_slot` has **cover** semantics
  (§7.3), so asking for the reference size directly makes the other slots bigger than it.
- A **shadow** is edited in three places through one `ShadowFields`, and in Simple it dresses **every**
  slot (`setShadowEverywhere`): the block never writes `shadow` (§3.7), so it neither detaches nor
  re-solves. A preview needs a real filter (an offset rect hides under the band, and inner/drop then
  look identical); SVG `filter`/gradient ids are document-wide, so prefix them with `useId`.
- **A filter is a value**: the chip bar, a smart collection's stored AST and `POST /artworks/query`
  carry the same object. `domain/filters.py` says what a filter may *mean*, `services/library.py`
  is the only place that knows how it reaches the schema — add a field to both, never to one.
  `taken_at` and `place` are the only clauses that leave the `artworks` table (EXISTS over
  `artwork_photos`): an artwork is "from Kyoto" when one of its photos is.
- The FTS index is written **inside the transaction that changed the row** (`services/search.py`):
  any new writer of a title, a tag link, a place or a collection name calls `index_*`, or search
  goes quietly stale. It stays disposable — `reindex_all` rebuilds it and startup does that when
  the table is empty. User text never reaches FTS5 raw: `match_query` keeps tokens only.
- **What is deleted together is restored together**: one `trash_batch_id` per gesture. Trashing a
  photo takes a cascade — `trash_artworks` (same batch) or `empty_slots`, which re-saves each
  document through `artworks.validated` so an attached composition re-solves, snapshots it
  `pre_trash`, and leaves the placeholder a new artwork would have (`quality_lock = free`).
- A collection's `position` is a REAL among its siblings (and a manual item's among the
  collection's items): insert at the midpoint, renumber the whole list only when the gap falls
  under `1e-9`. Cycles, depth (8) and self-referencing smart filters are refused by the *server* —
  the tree never tries to guess.
- A **bare letter and a chord starting with it** (`c` vs `g c`) are two `tinykeys` instances that
  each match on their own, so both used to fire. `app/commands.ts` keeps one capture-phase listener
  that arms on a chord prefix; single-key bindings stand down for the next keystroke. Register any
  new single-key shortcut through the registry and it is covered. A **modal** also has to take the
  page's keys away while it is open (the viewer passes `undefined` shortcuts, `ArtworksPage.key()`).
- Manual order (`position`) belongs to **one** collection: `manual` sort + `include_nested` is a
  422 (`manual_sort_nested`), never a silent fallback, and `nested_count` counts *distinct*
  artworks. A drop in the grid inserts before the target going backwards and **after** it going
  forwards, or dragging a card right asks for the place it already has.
- A collection is scoped through **`_in_collections`** — manual membership unioned with the filters
  of the smart collections among the ids — never a bare `collection_items IN (…)`, or a smart
  *sub*-collection contributes nothing (its artworks are matches, not rows). Smart membership is
  derived and read-only: `smart_collection_ids` is reported apart from `collection_ids`.
- Every grid of artworks takes its keyboard from **`useArtworkGridCommands`** so the three pages
  cannot drift; a page adds a key by passing a handler (the collection page's `Backspace`).
- A `<select>` left transparent gets a native popup Chrome paints from the *control's* colours —
  light popup, near-white options, visible only on hover. `styles.css` sets `select`/`option`
  colours at element level as the floor; utilities on a specific select still win.
- Driving this app over CDP: each open tab holds an SSE connection, so **six tabs exhaust the
  per-origin pool** and the next one renders an empty page — close tabs between runs;
  openapi-fetch binds `globalThis.fetch` at `createClient` time, so patching `window.fetch` later
  intercepts nothing (read results back through the API); and dispatch a synthetic key **once**, on
  the focused element — dispatching on `body` *and* `window` makes tinykeys see every key twice.
- Dev over the Vite proxy is **not** trusted as localhost (`xfwd` adds `X-Forwarded-For`, invariant 5): the
  first load asks for the setup code printed in the server log. Point Vite at another backend with
  `THE_FRAME_V2_BACKEND=http://127.0.0.1:<port>`.
