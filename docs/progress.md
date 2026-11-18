# Progress log

Newest first. Phases 0–12 and everything before the beta (2026-10-06):
[`progress-before-beta.md`](progress-before-beta.md).

## 2026-11-18 — Timeline, photos by place, removing a date, aligned tags, lighter AGENTS.md

- **A Timeline tab beside Places** (Tags page): year → month, the most recent first, with photo and
  artwork counts per level and the number of undated photos. Years fold open on their months (the
  latest starts open). `GET /timeline` (`services/timeline.py`) groups on the `taken_at` prefix —
  floating time, never converted. Each row links to the **photos** taken then — a new
  `GET /photos?taken=2024|2024-03` filter, shown on the Photos page as a "Taken in …" chip kept in
  the URL — and to the **artworks** made of one (`/artworks?taken=` → a `taken_at` "between" chip).
  `test_timeline_counts_per_year_and_month_and_links_to_both_grids` (boundaries: the last second
  of a month, a bad period → 422), `shared/period.test.ts` (month lengths, leap years).
- **The Places view opens photos too**: each row's photo count links to the photo grid
  (`/photos?place_country=…&place_admin1=…&place_name=…`), every level of the row matched exactly
  so the grid holds what the row counts — unlike the artworks link, which keeps the `place`
  clause's "contains". The chip names the row ("Neuilly-sur-Seine, France").
- **A photo's date can be removed** (*Remove the date* in its details, then Undo): a painting shot
  in a museum no longer sits in the Timeline under the visit's year. `PATCH /photos/{id}` with
  `taken_at` — `null` removes it, a value sets it back as written, left out it does not change
  (the other fields' `null` keeps meaning "unchanged"). The original keeps its EXIF.
  `test_a_photo_date_can_be_removed_and_set_back`; the Places test now follows every row's link.
- **The TV updated itself to One UI Tizen 10: read-only checks.** The pairing survived, the art
  API went 5.0.1.0 → 6.0.0.0 and answers the same 14 of 16 read requests, My Photos holds exactly
  the 42 items the app recorded, the slideshow settings were kept. One regression: the REST answer
  now leaves `name` and `modelName` empty, so the scan listed `? — ?`. Discovery and `tv status`
  take them from the TV's UPnP description instead (`fetch_description`, `with_description`;
  `test_a_tizen_10_answer_takes_its_name_and_model_from_the_description`) — re-run against the TV:
  `55" The Frame — TQ55LS03FAUXXC`. Not re-checked, because it writes to the TV: a push. The new
  date badge on slideshow transitions cannot be switched off through the art API (the same five
  settings as before), nor, by Samsung's forum, on the TV; leads in `docs/research/tv-display.md`
  §2c.
- **A tag's photo count opens its photos** (Tags tab), as its artwork count opens its artworks:
  `/photos?tag=<id>`. The Photos page's tag filter moved from component state into the URL, like
  the period and the place — the select writes it, a reload keeps it. Driven in a browser:
  *Famille* → 160 photos with the select on *Famille (160)*, the API count; the × and picking
  another tag both rewrite the URL.
- **Agent context, lighter**: `AGENTS.md` 26.0 → 12.1 kB, loaded into every session. It keeps
  what most tasks need (status, the main commands, a map by directory, the layers, the invariants
  word for word, conventions, the cross-cutting gotchas); each area's rules, the module-by-module
  map, the flows and the rarer commands moved verbatim to `docs/codebase.md`, seven subsystem
  gotchas to `docs/gotchas.md`. The hardware lists moved to the README's *Written with AI*, now
  the one list of what was and was not checked on real hardware. `docs/PLAN.md` §3.2, §4.2 and §15
  follow.
- **The Tags tab's columns line up.** Each category is its own table, and the automatic layout
  sized each one to its own names: the colours, the category menu and the counts moved from one
  category to the next (measured: the colour column started anywhere from x = 433 to 717). The
  tables share one set of widths now (`COL`, `table-fixed`), the category headers put their
  colours and delete button on the same columns, a name without a colour keeps the dot's room,
  long names truncate, and one sticky row labels the columns (the two counts had no visible label).
  Checked at 1400 and 1024 px wide: every column starts at the same x in all five categories.
- **Driven in a browser** (headless Chromium over CDP, production build, a copy of `.dev-data`):
  the tab lists 2026 → 2008 with 17 undated photos; November 2026's links open 74 photos and 12
  artworks, the counts the row shows; the chip's × goes back to `/photos`. Places: France → 56
  photos, Neuilly-sur-Seine → 20, as counted. A year link and a hand-typed `?taken=2008` both
  filter (the router parses values as JSON, so `2008` arrives as a number: `router.tsx` takes it
  as text). Removing the 2008 photo's date took it off the timeline; Undo put the same value back.
  Not driven: the French labels.

## 2026-11-17 — Project review follow-ups

- **A TV that failed a status check or a pairing forgot why.** `status()` and `pair()` set
  `last_error` (and `error`) in the request's session, then raised — and the error response rolled
  that session back: the card kept saying `new`, no error. They write it in a transaction of their
  own now (`_record_failure`; a push in progress keeps `pushing`), and the TV page refetches the
  targets after every check and every failed action. `test_a_failed_status_check_is_remembered`,
  `test_a_failed_pairing_is_remembered` (both failed before).
- **Lost server events went unnoticed.** A subscriber whose queue (256) was full lost events one by
  one, counted in a field nobody read, and a reconnected stream (laptop asleep, Wi-Fi drop, server
  restart) never learned what it had missed: pages stayed stale until a reload, and a push tray
  that missed `display.pushed` spun forever. The broker now drops what waits and sends one
  `resync`; the client refetches every query on `resync` and on every `ready` after the first, and
  the push tray falls back on the targets' stored progress.
  `test_a_subscriber_too_far_behind_gets_one_resync`.
- **The `jobs` table only grew**: every render and ingest leaves a row (`.dev-data`: ~2 400 rows,
  1 903 of them finished renders, for 96 artworks). A daily `jobs.prune` deletes `done`,
  `cancelled` and `dismissed` rows older than 30 days (`HISTORY_DAYS`); failures stay until
  acknowledged, and export rows stay (the Export dialog lists them).
  `test_finished_jobs_are_pruned_after_the_history_window`.
- **A queued job could wait 5 s for nothing.** A worker that found no job went to `wait(5)`; a
  job committed while its `_claim` ran notified a condition nobody waited on yet, so it sat for the
  whole timeout — and `stop()` lost its notify the same way (the 5 s of the crash-recovery test
  were that). A per-lane flag, set and read under the condition, closes the gap.
  `test_a_job_queued_while_a_worker_looks_is_picked_up_at_once` (failed before, deterministic).
- **`scripts/` is linted** (`make lint`/`make format`): 22 ruff findings, nearly all long lines in
  the render-parity spike; `scenes.py` checked to write byte-identical output after formatting.
- **The backend suite: 4 min 42 s → about 1 min 20 s.** Where the time went, measured: each test
  built its app in ~0.35 s — FastAPI rebuilt every route twice (module router → a prefixed `api`
  router → the app) and Alembic ran every migration on a fresh database. Routers now go straight
  onto the app with the prefix (app creation 0.30 → 0.125 s, same OpenAPI), and tests copy one
  migrated template database (0.105 → 0.006 s): median setup 0.35 → 0.06 s. Then `pytest-xdist`
  (`make test` runs `-n auto`). Measured and dropped: capping libvips threads (`VIPS_CONCURRENCY`
  1 is slower, 2 no faster) and a test-only PNG level (7 % on the render-heavy files). The slowest
  tests now are the ones rendering real 3840×2160 artworks (TV pushes, archives), which is what
  they are for.
- **Stale generated files fail `make check`** (`make generated`, `scripts/check_generated.py`):
  it regenerates the OpenAPI JSON, `schema.d.ts` and `docs/schemas/` into a temporary directory and
  compares. It would have caught the `/events` description committed without `make gen-api` today.
- **The Docker image did not build since 2026-09-24**: `license-files = ["LICENSE"]` (added with
  the MIT licence) names `backend/LICENSE`, a symlink to the root file that the image never copied
  — `uv sync` stopped on "glob `LICENSE` did not match any files". The user's check of the image
  (2026-09-17) predates it. The root `LICENSE` is copied in now; image built, started, answered
  `/system/info` and served the SPA. Pinned while there: the uv image (`0.11.21`, was `latest`) and
  pnpm (`packageManager: pnpm@12.14.0`, which pnpm 12 also records, with hashes, in the lockfile).
- **No deprecation warnings left in the test run**: Starlette's `TestClient` wants `httpx2` (dev
  dependency swapped; same API), and Starlette 1.10 no longer touches anyio's deprecated
  `BlockingPortal` alias (1.6 → 1.10, allowed by FastAPI 0.141).
- **CI**: `.github/workflows/check.yml` runs `make check` on pushes to master and pull requests
  (uv 0.11.21, pnpm from `packageManager`, Node 24, `ubuntu-24.04`). Its first run failed at
  setup: `astral-sh/setup-uv` publishes no moving `v10` tag. Every action is pinned to its release
  commit now (version in a comment) — a tag can also be moved under us.
- **The built frontend went raw and was revalidated on every load**: `/assets` (Vite's hashed
  names) had no `Cache-Control`, and nothing was compressed. They are `immutable` now, and gzipped
  — that mount only, so renders, photos and the SSE stream are untouched. The main chunk on the
  production build: 1 354 kB → 408 kB on the wire, then not fetched again. The shell
  (`index.html`) keeps `no-cache`, and a missing chunk stays a 404. `tests/api/test_spa.py`.
- **The editor is its own chunk** (`lazyRouteComponent`): main chunk 1 354 → 878 kB (270 kB
  gzipped), editor 480 kB, Konva only in the latter — phones on `/m` no longer download or parse
  it. A tab left open across a rebuild asks for a chunk that is gone: TanStack's loader reloads the
  page once (per session and error) — the boundary `vite.config.ts` said this needed. **Not driven
  in a browser**: this machine's Chromium no longer starts (`GLIBC_2.43 not found` in a Nix
  library); checked in the build instead (the route imports the chunk dynamically, `index.html`
  does not preload it, no Konva in the main chunk).
- **Agent context, lighter**: `AGENTS.md` 27.8 → 25 kB (repo-map rows cut to names and the note
  that helps find one's way, the TV page's own row dropped; status dated; the old-name `pkill`
  gotcha fixed; the Glossary section `PLAN.md` §3.2 requires, added). This log kept only what
  follows the beta: 128 → 13 kB, the rest unchanged in `progress-before-beta.md`. `PLAN.md` §4.2's
  tree, stale since Phase 1, points at the repo map; the four-line `docs/architecture.md` is gone.
- **Events nobody listened to, removed**: `job.progress` (one per exported photo, to every admin —
  with `resync`, a flood a sleeping tab would answer by refetching everything), `export.ready`,
  `import.staged`, `import.failed`, `import.applied`. Those pages poll their rows, which still
  carry the progress. What is published and `ServerEvents` now list the same 16 events.
- **Dependencies brought up to date**, one commit per risky step, release notes read first:
  - FastAPI 0.141 → 0.163: its breaking changes are about forms, `Body()` parameters and
    `root_path`, none used here; the OpenAPI document is byte-identical. It now ships OpenTelemetry
    hooks (off unless configured): switched off explicitly in `create_app`, so no environment
    variable can turn exporting on.
  - SQLAlchemy 2.1: `Select[tuple[X]]` annotations become `Select[X]`; `Result.tuples()` is
    deprecated (rows unpack directly); autoflush now precedes every statement. The engine URL is
    built with `URL.create`: 2.1 decodes `%` escapes in the database part, so an f-string URL
    would have opened another file for a data dir with `%`, `?` or `#` in its path. Every listing
    endpoint answered on a copy of `.dev-data`'s database.
  - Pillow 13: security fixes in its JPEG decoder and Exif parser, which read every upload's
    metadata; the Exif of 60 random `.dev-data` originals reads the same as what was stored.
  - samsungtvws 3.0.7: its diff touches URL building only — not the `open()` and `_recv_frame`
    our art channel builds on; the TV tests and `tv_probe.py --fake` pass. **Not tried on the TV.**
  - i18next 27 / react-i18next 18: none of the breaking changes applies (`fallbackLng` and
    `escapeValue` were already set, no `<Trans>`, no empty strings, no typed resources); plurals
    checked in Node with the real catalogs, French millions included.
  - Everything else within its range (Radix 1.1 → 1.3, Konva 10.5 → 10.9, TanStack, Vite…) and
    the backend minors. `pnpm audit`: 14 advisories (6 high) → 1 moderate, in the lint toolchain.
  - Left: TypeScript 7 (typescript-eslint still requires `<6.1`) and `@types/node` 26 (the
    project supports Node 22). **Not driven in a browser** (local Chromium broken): the UI after
    the Radix and Konva updates. CI ran green on GitHub (2 min 26 s) once the actions were pinned.
- **The placeholder name is no longer read** (user's decision): `THE_FRAME_V2_*` variables, the
  `the_frame_v2` data dir and `the_frame_v2.archive` archives. The rename came with the public
  release, so only the author ever had it, and nothing on this machine used it (no old data dir,
  variable, service unit or archive).
- **The editor's rules have tests** (user's decision, "in a small form"): 20 cases in
  `frontend/src/editor/operations.test.ts`, run by Node's own runner (`pnpm test`, in `make test`
  and so in CI) — margins and native linking, the lock against rotation and stretching, quarter
  turns, mirror and straightening, the wheel's bounds, swap/replace, decorations of a new slot, a
  cell that zoom and native framing never move, balance clamping, the recipe following the photo
  count, detach / re-apply, a caption kept on attach. No new dependency: `operations.ts` imports
  `editor/core` relatively now, as `core` itself does. Three rules broken on purpose (mirror,
  straighten reset, recipe family) each made a test fail. Two first expectations were mine and
  wrong, not the code: under `no_upscale` the wheel stops where the photo would be stretched
  (2.35 here), not at 8.
- **The editor's history showed 5 lines, often the same one** (user feedback). The panel cut the
  list at 5 of the 20 kept, and identical snapshots piled up: one per opening even with nothing
  changed (two under `make dev`: StrictMode mounts the editor twice), one per restore even of the
  version already there — 50 of the library's 183 were copies of the one before. On artwork #12 of
  the TV set all five visible lines were the same document, so the version that was on the TV
  (v70, 8th) could not be reached and three restores put the document back onto itself. Now the
  server returns the latest snapshot instead of an identical one for the same reason (another
  reason keeps its own entry: "before template update" is how one finds the way back), restoring
  the current version is a no-op, and the panel lists every snapshot, scrollable, with its local
  time; the one matching the saved version reads "Current" instead of offering Restore. The
  `pre_trash` reason had no label. Existing duplicates were left in place.
  `test_an_unchanged_artwork_is_not_snapshotted_twice` (failed before). **Not driven in a
  browser** (local Chromium broken).
- **The sidebar's collection tree starts folded** (user feedback: it took too much room): only
  top-level collections show until a chevron opens one (`CollectionTree`'s `defaultCollapsed`).
  What was opened lasts while the app stays loaded, not across a reload. The Collections page
  still unfolds every level. Dropping artworks into a sub-collection from the sidebar now takes a
  click to open its parent first. **Not driven in a browser** (local Chromium broken).
- **Photos open full screen** (user feedback: "to select the one I want to keep and the ones I
  want to trash"). `PhotoViewer`, on the Photos page and the Inbox: a double-click (it opened the
  details drawer, which stays on `i` and ⓘ), `v` or the header's ⤢. ←/→ walk the grid, and the
  grid scrolls along behind it, so closing lands on the last photo shown (with the keyboard focus
  on it). `Delete` trashes the photo (Undo; the cascade dialog, over the viewer, when an artwork
  uses it) and `d` dismisses it from the Inbox; both then show the next photo, else the previous
  one. `useDeletePhotos` now tells its callback *which* photos left, so the viewer moves on from
  that photo even if the server answers late, and a second `Delete` before the answer is ignored.
  `s` toggles the photo in the grid's selection. Fitted, the viewer shows the 2560 px proxy over the
  768 px thumbnail; `z` or a click shows the original at 100% (one photo pixel per device pixel)
  around the point clicked, panned by dragging (scroll positions written straight to the element)
  or scrolling. The zoom and its spot carry over to the next photo, to compare a burst's sharpness.
  `Escape` first goes back to fit. A photo already at 100% when fitted offers no zoom: it is never
  blown up. The neighbours' proxies are fetched ahead. **Not driven in a browser** (local Chromium
  broken): type-checked, linted, and the layout and focus code read twice.
- **…and it never showed a photo** (user feedback: "it keeps loading"). The viewer measured its
  area in an effect run on its first render, but Radix's `Portal` mounts the dialog's content one
  render later: no element, no `ResizeObserver`, no size — so no photo, only the spinner, forever.
  The observer now starts when the element mounts (a callback ref into state). The server was never
  the problem (proxy 10–25 ms, a 42 MB original 0.1 s on localhost). Two more found by driving it:
  - **Undo was hidden behind the viewer**: toasts sat at `z-50` like the dialogs, under the one
    opened last. They are above dialogs now (`z-[60]`), and a click on one no longer closes the
    dialog under it (`isInToaster`, in `Dialog`, `ArtworkViewer` and `PhotoViewer`). It asks the
    toast **card**: a modal dialog judges a press "outside" only at the `click`, and *Undo* has
    removed its toast by then — detached from the toaster, the button is still in its card.
  - **Closing left the photo 8 px out of view**: the grid's top padding was CSS, unknown to the
    virtualizer that scrolls a row into view; it is the virtualizer's `paddingStart`/`paddingEnd`
    now (same 16 px, same layout).

  **Driven in headless Chromium** (CDP, on a copy of `.dev-data`): the proxy shows 240 ms after the
  double-click; `z` centres the 3840 px original; a drag pans without un-zooming; → keeps the same
  spot on the next photo; a click at (¼, ¼) of the photo keeps that point under the pointer;
  `Escape` un-zooms first; `s` selects; `v` opens the focused tile; `Delete` moves on, shows Undo,
  and twice fast trashes one photo; on a photo an artwork uses, the cascade opens over the viewer
  and ← waits; *Undo* restores and the viewer stays (the artwork viewer too); closing focuses the
  last photo, in view. The "local Chromium broken" of the entries above was the shell's
  `LD_LIBRARY_PATH` (see `AGENTS.md`).

## 2026-11-16 — Bevel hole, TV handshake, sub-collections, picker selection, straightening

- **The "hole" in a bevelled mat** (renderer 4). Not stretching: `_bevel` gave a band pixel to the
  top face when the top edge was nearer than the *sides*, without asking about the bottom edge. In
  a slot over twice as wide as tall, the middle of the bottom face is nearer the top edge than
  either side, so it took the top's dark shade — a trapezoid under every wide photo of a
  Bevelled-mat artwork. `RENDERER_VERSION` 4: every hash moves, the next push re-uploads the set.
  `test_a_wide_bevel_keeps_its_bottom_face_whole`.
- **TV pushes failing at random.** The job history held the evidence: `tv_art_unavailable` coming
  back in 0.1–1.5 s, then the same push succeeding a minute later (2026-10-17, 11-12, 11-15). The
  library's art `open()` demands that the frame right after `ms.channel.connect` be
  `ms.channel.ready`, and the TV first announces each client joining — `ms.channel.clientConnect`,
  for *our own* connection (the frame in the old report carries our name, base64). The 2026-10-02
  reading — "another connection of ours, TV out of art mode" — took a race for a sleeping TV.
  `art_channel_class()` waits up to 10 s for `ready` and lets announcements go by; only a TV that
  never says it is `tv_art_unavailable`, and the message lists the event names it saw. Every push
  now logs one line (host, duration, what it did, or the code it failed with).
  **Not verified on the TV** (it was off): the next pushes will say.
- **Sub-collections** (user feedback): a "+" on each manual row of the tree and a *Sub-collection*
  button in the header open the dialog with that parent; *Inside* is a tree picker that reads as a
  path when closed (`ParentPicker`), never offering a smart collection or the edited one's subtree.
- **Selecting in pickers** (user feedback): `useSelection` gains a picker mode (a click toggles)
  and skips disabled items. *Add artworks* has Shift-click ranges, Ctrl/Cmd+A (also from the empty
  search box; with text in it, Ctrl+A selects the text), *Pick all* / *Clear*, and loads more on
  scroll; the Trash has ranges and Ctrl+A too. The page grid gives up its keys while the picker is
  open. The range anchor is an id now, not an index: the Inbox changes between two clicks, which
  is the likely cause of "Shift-click works in Photos, not in the Inbox".
- **Straightening** (user feedback: "small rotate to adjust the horizon"). `source.straighten`
  (±45°, 0.1°), a *Straighten* slider (±15°) + field in the Simple and Advanced panels. Design:
  the crop lives in `straightened_size` — the largest centred rect of the photo's aspect inside the
  turned photo — so every crop rule, the solver and the server's refit work unchanged
  (`slotSource` / `SourceSpec.bounds`); only the renderer (`_straightened_photo`: read the region
  under the crop, Lanczos shrink, one bicubic affine) and the canvas (`StraightenedPhoto`) turn
  anything. A slider gesture derives each step from where it started, so 0 → 4° → 0 restores the
  framing. The angle follows its photo on swap, resets on replace, negates on mirror. In
  `_LATER_DEFAULTS`: checked on `.dev-data`, all 79 artworks rendered under renderer 3 keep their
  hash with the new schema (10 older ones were already stale since September).

**Verified**: `make check`; conformance (straightened sizes, `restraighten_crop`, a straightened
composition apply); a render test levels a 5° horizon. Not driven in a browser: the tree "+", the
picker's keyboard, the straighten slider on the canvas. On the TV: one clean push after the
handshake fix (the failures were intermittent, so one is a start, not a proof).

**Drag to reorder collections** (user feedback: "how are collections sorted in the sidebar?" — by
creation, and nothing could change it: the tree's comment promised drops *between* rows, but only
drops *onto* a row existed). Rows have drop bands above / into / below; a line shows the landing
spot; the sidebar's tree reorders too; the top-level zone shows only during a drag. The placement is
`tree.moveFor` (pure: self, own subtree and no-op drops offer nothing); the server's `before_id`
path, untested until now, has `test_drag_to_reorder_collections`. Not driven in a browser (HTML
drag and drop cannot be scripted through CDP the way clicks are); the drop rules were run by hand
on a sample tree (17 cases).

**Straightening guides** (user feedback, same day): while the *Straighten* slider is held — and
for a moment after it is let go, a value typed or an arrow key — a light grid (square cells, six
across the short side, a line through the centre each way) covers the photo, in the slot's frame,
for lining a horizon up. UI state only (`editor/guides.ts`), never in the document or the undo
history; the grid toggles once per gesture, not per event.

## 2026-10-06 — Open source: Frame It, beta, roadmap

- **Name**: the placeholder `the_frame_v2` becomes **Frame It** — package `frame_it`, command and
  distribution `frame-it`, env prefix `FRAME_IT_`, data dir `frame-it`, Docker image `frame-it`,
  service `frame-it`, error and schema URLs `https://frame-it/…`, archive format
  `frame_it.archive`. The name the TV, LocalSend and the TLS certificate see is "Frame It".
  Checked before choosing: no live "FRAME IT" trademark for software turned up (US, quick search,
  not legal advice); fastlane's `frameit` and several app-store "Frame It" apps exist, and
  `frameit` is taken on PyPI and npm (PLAN §16).
- **What a library already had keeps working**: `THE_FRAME_V2_*` variables are copied to their
  `FRAME_IT_*` names unless set (`config.adopt_legacy_env`), the old data dir is used while no new
  one exists (`default_data_dir`), and an archive saying `the_frame_v2.archive` imports
  (`archive.LEGACY_FORMATS`). Pinned by `test_settings_read_the_placeholder_names` and
  `test_an_archive_written_before_the_rename_is_read`. Not carried over: a service installed under
  the old name (reinstall it), and possibly the TV's pairing — the TV may treat "Frame It" as a
  new device and ask again (not tried on hardware; *Pair again* covers it).
- **Beta**: said in the README (banner + badge), on the sidebar next to the name (a *Beta* badge
  whose tooltip says to keep a copy of the photos), and as the `Development Status :: 4 - Beta`
  classifier.
- **Public resources**: a Samsung non-affiliation and trademark notice in the README and
  `NOTICE.md`; the comments and docs that cited the private `remarks.md` (and a local folder of
  reference photos) now say "user feedback". Checked and clean: no secret, token, key or home
  path in the tracked files or the history (the GPS in tests is city centres); the screenshots
  carry no metadata.
- **Roadmap**: `docs/PLAN.md` §17 — HEIC from iPhones (spike on a real iPhone first, then a decoder
  superseding ADR-0006), then an installation without a toolchain (CI releases, a published Docker
  image, executables per OS or a PyPI package). The README has the short version; the user guide
  now names the iPhone setting that gives JPEG.

**Verified**: `make check`, and the changed scripts' `--help`. Not driven in a
browser: the sidebar badge (type-checked only).
