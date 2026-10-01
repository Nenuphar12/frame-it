# Progress log

## 2026-10-01 — Two older bugs, found while checking the merge

**Every tile of the Trash page was a broken image.** Both thumbnail routes looked their row up
through the library's getters, which refuse trashed rows by design, so the trash could list what it
held but not show it: on a copy of the dev library, 16 artworks and 5 photos, 21 × 404. The
thumbnail routes (and only them) now accept a trashed row until the purge; a trashed artwork is
rendered with the photos that went to the trash with it, which reproduces the render it had — same
hash — instead of empty slots. Renders, proxies and originals of trashed items stay refused
(`test_the_trash_shows_thumbnails_until_the_purge`, which fails on the previous code). Measured
after the fix: 21 of 21 thumbnails load, no failed request, with the render cache cleared first.

**The Collections page asked for a collection named "none".** With nothing selected it still ran
its artwork query, with `collection_id: "none"` as a placeholder, and the server answered 404 on
every visit. `useArtworks` takes `enabled` now and the page sends nothing until a collection is
picked; measured: no failed request on `/collections`.

## 2026-10-01 — TV follow-ups (remarks.md TV-1…6, "ready" on the wall)

Spec: `docs/tv-display.md` (rewritten). Migration `0010` (`32545e54fd09`).

**Finding the TV.** `tv/discovery.py` runs SSDP and a sweep of the /24 together (the probe's
`--scan`, made a module); the /24 is the LAN's — `tv_scan_subnet`, else the public URL's address,
else this host's, because inside Docker the host's own address is the bridge network. The Add-TV
dialog scans as it opens and pre-selects the first Frame not yet added; the MAC it stores lets
`_with_tv` find the TV again when DHCP moves it (the address is updated and the operation retried
once, and the result says so).

**"Don't change"** (`slideshow_minutes = 0`) shows the first artwork, stops the slideshow and
**deletes nothing** — neither foreign photos nor our earlier uploads. It is what a single artwork
starts with (viewer, editor command), and it is the reason the map had to change: "ours" can no
longer mean "in the current set". `position` became nullable, and **a row now lives exactly as long
as its upload is on the TV** (invariant 15). Building that exposed two existing bugs in the mirror
push, both of which turned our own uploads into "photos this app did not send" — counted, warned
about, offered for irreversible deletion: reordering a set deleted the old row when it re-uploaded,
and a push failing half way rolled back the rows of the uploads that had reached the TV. Each upload
is now recorded in its own transaction the moment the TV accepts it.

**Order was wrong too.** Re-uploading one changed artwork in the middle of a set made it the
TV's newest item, so it played first. `plan_push` now reuses only a *tail* of the set (each kept
upload newer than the one after it) and re-uploads everything before the first position it cannot
serve; uploads are dated past the target's `image_clock`, so two quick pushes never interleave.

**Saying what will happen, then what happened.** `POST /display/targets/{id}/plan` is the same
planner, executed nowhere: to send / already there / ours leaving or staying / foreign / drafts.
"Show on the TV" asks it twice (the app's memory, instantly; then the TV) and shows *Also remove the
N photos this app did not send* only when N ≥ 1, and only for a slideshow. The TV page's *Send*
runs it first, so the foreign-photo confirmation no longer depends on having pressed *Check the TV*
(it silently kept them before). The push publishes `display.progress` (throttled), shown in a
sidebar tray on every page; `display.pushed` becomes a summary toast, and the result is kept on the
target. The rotation (interval incl. "Don't change", *In order | Shuffle*) sits in a collapsed row
of the dialog and is saved with the push. *Leave out N drafts* gives "ready" a job: ticked for a
collection or filter, unticked for a hand-picked selection (`status: "ready"` now filters explicit
lists too). A query over 200 artworks is refused rather than cut.

Found while verifying: a push failing *before* the TV (an empty set) left the `queued` progress
stored, so the tray would have waited forever after a reload — every failure path now clears it.

**Verified in a browser** (headless Chromium over CDP, production build, `THE_FRAME_V2_FAKE_TV=1`,
a copy of the dev library; results read back through the API), 55 checks: add a TV from the scan
(recommended, pre-selected, MAC and model stored) and by address; pair; rotation saved; Show on the
TV from a collection — dry-run numbers, the collapsed row, *Leave out 1 draft* (3 vs 4 artworks),
the foreign checkbox with its count and gone in "Don't change"; a push whose tray went
`Waiting → Preparing 1–3 of 3 → Sending 1–2 of 3` with a bar that only moved forward, then the
summary toast; the TV page asking about the 3 foreign photos with no *Check the TV* first, and a
re-push sending nothing; "Don't change" on one artwork from the viewer (1 sent, 3 of ours and 3
foreign left on the TV, nothing deleted); a slideshow push back to the collection removing that one
and, on request, the 3 foreign photos; after which the checkbox no longer appears.

**Not verified on hardware**: discovery on the real LAN (SSDP and the sweep), following a TV that
moved, a "Don't change" push (`select_image` + stop), and deleting foreign photos.

## 2026-10-01 — Tags, the inbox and "ready" (remarks: tags #1/#2/#3/#5/#12, ready #13, inbox #17/#23, trash #22)

**An artwork now carries its photos' tags** — read at query time, never copied, the reading
`taken_at` and `place` already had. The `tag` clause compiles to "own **or** through a live
photo", so smart collections and `nested_count` follow with no code of their own; the artwork's
FTS text holds its photos' tag names, and every write that changes a photo's tags re-indexes the
artworks made of it (single, bulk, rename/merge/delete, ingest, duplicate upload, archive import).
The index is now versioned (`search.INDEX_VERSION = 2`, a `meta` marker row): on the dev library the
first start logged *search index rebuilt (127 entries)*, and `test-photos` went from 1 artwork
(own) to 6 (own or inherited) — the five others carry it through their photos, which is exactly what
the user expected a tag to mean. The API reports both (`tags` own, `inherited_tags` the rest), and
the counts distinguish what the filter returns (`artwork_count`) from what a deletion detaches
(`own_artwork_count`).

**Categories** (migration `0011`): `tag_categories` seeded People / Events / Themes, and
`tags.category_id` (`ON DELETE SET NULL`: deleting a category keeps its tags, as "Other") +
`last_used_at` (the picker's "recent" order). The migration adds the columns with a plain
`ALTER TABLE … ADD COLUMN`, deliberately not a batch rebuild: `photo_tags` and `artwork_tags`
cascade from `tags`, and dropping the table with foreign keys on would delete every link in the
library — `tests/unit/test_migrations.py` pins that a link survives. It applied cleanly to a copy
of the dev library. Categories travel in the archive (`tag_categories.jsonl`, matched by name
like tags, so the seeded three never double) within format version 1 — the file and the field are
optional both ways, and an archive without them still imports (tested by stripping them).
No "Places" category: a read-only **Places** tab derives country → region → place from the photos'
metadata (`GET /places`), and a row opens `/artworks?place=…`.

**The inbox rule changed**: creating an artwork no longer takes its photos out — only marking one
**ready** does, one-way (back to draft, trash and restore never put a photo back; a dismissed photo
stays dismissed). A draft shows as a badge on its photo's inbox tile that opens it. **Existing data
was not changed retroactively**: photos already `processed` with only draft artworks stay out of
the inbox (*Back to inbox* on the Photos page brings any of them back by hand).

**Bulk tagging** is additive (`POST /photos/tags`, `POST /artworks/tags`), behind one tri-state
`TagMenu` on every selection (`t`) and *Tag these N photos…* in the upload tray. A duplicate upload
used to drop the phone page's tags/collections/favourite on the floor (`open_session` returned
`exists` before reading them); every upload path now goes through `photos.apply_upload_meta`.

**The trash acts, then offers Undo** (restoring the batch). The cascade dialog stays only when
artworks use the photos — `useDeletePhotos` asks for the preview first — and it opens focused on
*Move to trash*, so `Enter` or a second `Delete` confirms (it used to focus the close cross: Enter
cancelled). After an `empty_slots` cascade no Undo is offered, since restoring the photo would not
refill the slots; the toast says the artworks' history can. Remark #3 (the viewer's tag row could
never be closed) is fixed: *Done*, `Esc` (handled in the viewer's `onEscapeKeyDown`, because Radix
hears Escape in the capture phase before any input could) and moving to another artwork all close it.

Found on the way: the Tags page, the Photos tag filter and the filter bar's tag chip asked
`GET /tags` with the autocomplete's limit of 20 — a library with more tags could not filter by the
rest. They use `useAllTags()` (alphabetical, up to 500) now.

**Verified in a browser** (headless Chromium over CDP, production build, a copy of the dev library,
results read back through the API): 29 of 30 scripted checks passed first time, then 3 more
(Enter on a radio confirms the cascade dialog; `empty_slots` keeps the artwork, incomplete and
draft; its toast has no Undo) — no console error, no 4xx/5xx in 744 requests. Driven: the Tags page
grouped by category and a tag moved between categories; Places → `/artworks?place=Cantagallo` with
the chip and the 7 expected artworks; `t` + a new tag on two photos, then the artwork made of one
of them carrying it (viewer, dashed) and found by search; the viewer's tag editor closed by `Esc`
(viewer stays open), *Done* and navigation; `Delete` on the grid → Undo; deleting an unused photo
(no dialog) → Undo; deleting a used one → dialog focused on *Move to trash* → `Delete` again →
Undo restoring photo and artworks as one batch; the inbox Draft badge opening the editor; *Back to
inbox*; the inbox's `t`, *Delete* and *Dismiss*; a synthetic drop of one new photo and one
duplicate → *Tag these 2 photos…* tagging both; `t` on two artworks. The one failure: marking
ready **through the API ~1 s after the inbox page loaded** did not refresh it — the app's
EventSource was not connected yet, and events are not replayed. With the page settled (a probe 3 s
after load) the tile left the inbox on the `photo.updated` event as designed. Not driven: the
phone page's upload (the duplicate path is covered by an API test) and LocalSend batches (the tray
treats them like any other item).

## 2026-10-01 — Two bugs from the remarks review (#4, #19)

**The TV preview opened, flickered and closed (#4).** `EditorPage` passes `onClose` as an inline
arrow, and `TvPreview`'s fullscreen effect listed it as a dependency, so every re-render of the
editor (an autosave, the `artwork.rendered` that follows an edit) re-ran the effect: the cleanup
left fullscreen, and the new effect's `fullscreenchange` listener read that as the user leaving.
`TvPreview` now reads the latest `onClose` through a ref and enters fullscreen once per mount.
Reproduced first on the previous build over CDP (P → open and fullscreen; an external
`PATCH /artworks/{id}` → the editor refetches → closed), then fixed on the new one (still open
and fullscreen after the same re-render; leaving fullscreen, `Escape` and `P` still close it).

**A smart collection's count lagged behind its artworks (#19).** Artwork mutations and the SSE
`entity.changed {artwork}` only refreshed the artwork lists; the tree's counts (`["collections"]`)
and the tag counts (`["tags"]`) waited for their 30 s staleness. Both now refresh on any artwork
change — at once for one's own action, at most once per second for SSE bursts (the editor saves
every 800 ms while a slider moves) — and on tag changes and trash events. Measured on a copy of
the dev library: adding the tag a smart collection filters on moved its sidebar count 13 → 14
within a second (one `GET /collections`), and back to 13 on removal; before the fix, no request
and the count stayed at 13.

## 2026-09-24 — Phase 11 (hardening & polish)

**The performance pass found one thing, and it was worth the whole exercise.** `scripts/bench_library.py`
times the requests the three grids actually make, through the real app, against a 10k-artwork library.
The first run said every case was inside the 67 ms budget — and that was true, but it hid the shape of
the problem: `EXPLAIN QUERY PLAN` showed `USE TEMP B-TREE FOR ORDER BY` on *every* page of the grid.
Each listing filters `deleted_at IS NULL` and then orders, and with `deleted_at` alone in a
single-column index SQLite was reading the matching rows and sorting all 10 000 of them, per page.
13 ms for the default order, **64 ms for `created_asc`** — one scroll gesture away from missing the
budget on its own. Migration `0008` leads each composite with `deleted_at` (and adds one for the
Favorites view): 0.5 ms, no sort, and the old single-column index is dropped rather than kept beside
them because every query it served is served by the composites. Through the API: artworks page
21.9 → 11.6 ms, the sidebar's collections tree 41.1 → 24.5 ms, search 28.3 → 17.0 ms, worst p95
45.2 → 28.7 ms.

One attempted optimization was **reverted**: restructuring `collections.counts` to avoid loading
artwork ids for leaf collections made the tree *five times slower* (41 → 220 ms), because it added a
second query without removing the first. The index does the job instead. Measuring before and after
is the only reason that is a paragraph here rather than a regression in the tree.

**Memory turned out to be the binding constraint on renders, not time.** `bench_render.py` now reports
peak RSS beside each duration (it was also quietly broken since Phase 8 — it still called the removed
`build_document`, and nothing in `make check` runs `scripts/`). A 6-slot collage of 24 MP sources peaks
at 1.6 GB; nine slots at **2.3 GB**. pyvips builds a lazy pipeline, so every decoded original stays
resident until the image is written — the 512 MB LRU bounds what is kept *between* renders, not what
one holds. A document may carry 32 slots, which at 48 MP each asks for roughly 14 GB: an
out-of-memory kill of the server, taking the job queue with it, from a document a paired uploader can
save. `MAX_RENDER_PIXELS` (320 Mpx of *distinct* sources, counted from the file headers so nothing is
decoded first) now refuses that as `render_too_large`.

**Error UX: a failure is no longer allowed to be silent.** Three pieces. `shared/toast.ts` is a store
outside React that carries a **problem code, not a sentence**, so the same failure reads the same
wherever it is raised; `problemMessage` replaces the
`t("errors." + code, { defaultValue: e.message })` expression that was copy-pasted into eight
components and missing from everywhere else; and a `MutationCache` in `main.tsx` reports any mutation
that does not render its own failure (`meta: { silentError: true }` opts out). Two inline error lines
were *removed* in the process — the artwork viewer's and the tag manager's — because the action they
belonged to is triggered from places with no footer to put the message in, and a toast is better
placed than a line the user has already scrolled past.

Then the **activity centre**: `GET /jobs`, retry, dismiss, at `/activity`, with the failed count as a
red badge in the sidebar and a toast on SSE `job.failed` offering *View*. A retry is a **new job**
rather than a reset of the old row, so the history of what failed is never rewritten; the failed row
becomes `dismissed`. Two things had to be right underneath: `jobs.code` is a **column** (migration
`0007`) rather than a prefix parsed back out of the error text — the first implementation did parse
it, and `"RuntimeError: boom"` is indistinguishable in shape from `"render_failed: no pixels"`, so a
traceback claimed the code `RuntimeError` — and `retry_job` **commits before enqueuing**, because
`JobQueue.enqueue` opens its own session and SQLite has one writer (the first version deadlocked with
"database is locked").

**Accessibility.** Contrast was computed rather than eyeballed: dark passes AA everywhere, light had
three pairs under 4.5:1 on `panel-2` (`accent` 4.24, `warning` 3.93), now 5.07 and 4.68. Separately,
no control had a 3:1 boundary — `--color-border` is 1.45:1 against the page, which is right for a
separator and wrong for the edge of a field, and it is spelled `border border-border` at ~90 call
sites. `--color-border-strong` (6a6a76 / 7d7970, ≥ 3:1 on every surface) now dresses buttons and form
controls; the controls get it through an **attribute selector** in `styles.css` (0,1,1), which
outranks a single Tailwind utility (0,1,0) without touching any of those call sites. Plus a skip
link, `prefers-reduced-motion`, and `role="status"` + `aria-live` on the toasts. An audit of all 188
buttons found **no** icon-only button without an accessible name, and every `<img>` already carried
an `alt` — that part of the codebase was already right.

**Service installers.** `the_frame_v2 service install|status|uninstall` generates the unit for *this*
machine — the absolute path of this interpreter's console script and the data directory the user
chose, neither of which is guessable from a shipped file — and prints the commands that enable it
rather than running them. `systemd-analyze --user verify` passes on the generated unit. Windows gets
Task Scheduler / NSSM instructions in the user guide instead of a generated file.

**Security review.** Both dependency audits clean (`pip-audit` runtime and dev, `pnpm audit`). Five
response-header directives were missing and are now sent and pinned by a test: `form-action 'self'`
(a form's POST target is not covered by `default-src`), `object-src 'none'`,
`Cross-Origin-Resource-Policy`, `Cross-Origin-Opener-Policy` and a `Permissions-Policy` denying
camera, microphone, geolocation, payment and USB. One suspected vulnerability turned out **not** to
be one: the archive size budget adds up each member's *declared* `file_size`, which looked like the
classic zip-bomb hole — but CPython's `zipfile` stops a member at its declared length and then fails
its CRC, so understating it cannot smuggle anything through. That is a property of the standard
library rather than of the ZIP format, so `_verify_checksums` now spends the budget against the bytes
it actually streams, and both cases are pinned by tests. The rest of `docs/security.md` was walked
through and found correct; the review is written up there.

**Name and licence.** MIT (`LICENSE`, declared in both manifests). The name stays the placeholder by
the user's decision — the rename touches the package, the `THE_FRAME_V2_*` prefix, the data dir and
the error URLs, and is better as one mechanical commit than as a strand of this one.

**Docs.** `docs/user-guide.md` (install, service, pairing, the two upload routes and why Android
matters, what the three quality tiers mean, templates, organising, export, a troubleshooting table,
every setting), a rewritten README, `CONTRIBUTING.md`, and `NOTICE.md` extended with the runtime
dependencies and the ICC answer (none are bundled — libvips' built-in sRGB).

**Verified**: `make check` green. Driven in a real browser (headless Chromium over CDP against the
production build on trusted localhost), results read back through the API where the DOM would not
settle it:

- Every page renders with no CSP violation and no console error after the header changes.
- The whole error path, end to end: hiding an original on disk and duplicating the artwork makes the
  render job fail → the toast reads *"A background task failed / A photo's file is missing from the
  library. / View"* → the sidebar badge reads `Activity 1` → the page's summary reads "1 failure
  needs attention" and the row shows the translated sentence with the traceback folded behind
  *Technical details* → **Retry** takes the failed count back to 0.
- **That run found two real bugs**, both fixed and re-verified: the message was a raw
  `DecodeError` traceback carrying an absolute server path, because `render_job` converts
  `RenderError` and `ProblemError` but a `DecodeError` from the decoder escaped both (the decoded
  cache now wraps it); and the toast printed its title twice, because an uncoded failure was given a
  code whose string said the same thing as the title.
- Keyboard: one `Tab` from a fresh page lands on the skip link, which becomes 130×36 px and jumps to
  `#main`. **A false alarm here is worth recording**: measured through `element.focus()` the link
  stayed 1×1, and I replaced the Tailwind utilities with hand-written CSS to "fix" it — the real
  cause was that a headless window is not focused, so `:focus` never matched. Checking the built
  stylesheet showed Tailwind emits `focus:not-sr-only` *after* `.sr-only`, so the ordering hazard I
  had assumed was not real. The hand-written CSS was reverted.
- Tokens computed by the browser match the intended values in both themes; a secondary button and
  the form controls both report `rgb(106, 106, 118)` (the strong border), and
  `prefers-reduced-motion: reduce` takes transitions from 0.15 s to 1e-05 s.

**Not done**: the README's screenshots. The only library available here is `seed_library.py`'s
synthetic one — coloured rectangles — and a screenshot of that presented as the product would
misrepresent it. The UI itself was captured and reviewed; real screenshots need real photos.

## 2026-09-23 — Phase 10 (export / import)

**The format is deliberately boring.** A `.tfarchive` is a ZIP holding `manifest.json`, one
[JSON Lines](https://jsonlines.org/) file per entity under `data/`, the originals under their own
SHA-256, optional renders, and `checksums.sha256` in `sha256sum` format — so `unzip` +
`sha256sum -c` + `jq` read an archive with none of this app present, and every record shape is
published as a JSON Schema in `docs/schemas/archive/`. That is a property worth protecting for
something meant to outlive the code: `domain/archive.py` is the single place that says which
columns travel, and the file layout lives beside them.

**What travels, and what deliberately does not.** Devices, codes, upload sessions, jobs, snapshots,
LocalSend senders, the FTS index, `artwork_photos` and the photo hash aliases stay behind: derived,
local, or secrets. Trashed rows *do* travel (with `deleted_at`), so a round-trip restores the trash
too. **Built-in** styles and layouts are part of the app, seeded on both sides — exporting them
would only invent conflicts, and an artwork's reference to one survives by id. That last clause is
not decoration: mapping an unmapped builtin id to `None` lost the origin badge on every artwork and
made a re-import report 0 identical artworks instead of 2. The round-trip test caught it.

**Identity is meaning, not ids.** A photo *is* its bytes, so a local photo with the same SHA-256
(merged copies included) is the same photo whatever id either side gave it — references are remapped
and, per §12.2, a local copy sitting in the trash comes back. A tag is its name, case-insensitively,
so tags merge instead of duplicating. Everything else matches by id, and `identical` ignores every
timestamp, the trash batch and `document_version`: a no-op save on one side is not a conflict. The
three policies (`keep_mine` / `take_theirs` / `keep_both`) therefore only ever apply to a genuine
same-id-different-content clash — which in practice means *the same library edited in two places*.
A photo is the one exception: `take_theirs` on two different images sharing an id cannot mean
anything under content-addressed originals, so it behaves as `keep_both`.

**A row is compared *after* translation, and after migration.** Two findings, both about what
`identical` means, and the second only showed up on a real library.

The first version compared the archive's record against the local row as read, which meant an artwork whose photo had been matched by SHA-256 to a local
photo with a different id read as `conflicting` on every re-import — the classification would have
pushed people to pick policies for changes that did not exist. The fix made the translation shared
(`archive_import._translated`, `artwork_values`, `collection_values`, `remapped_document`): the
report predicts the maps an import would use (photos by hash, tags by name, everything else itself
— `keep_both` is the one policy that moves an id, and it is chosen *after* the report) and compares
the translated record, which is also exactly what apply writes. Regression-tested both ways.

Then, driving the dev library in a browser: **23 of its 30 artworks read as `conflicting` on a
re-import of their own archive**. Their stored documents predate `margins.mirror_x`/`mirror_y`, so
the row on disk has no such key while the same document read back through the schema does — the
comparison was between a raw dict and a parsed one. `archive.comparable` now runs *both* sides
through the schema (artwork documents and template documents alike), which is also the honest
reading of the question: an older schema that migrates to the same document is not a conflict. The
counts went to 30 identical, 0 conflicting, every policy control correctly disabled. Under
`keep_mine` the outcome had been right by accident; `take_theirs` would have rewritten 23 artworks
for nothing.

**One set of id maps, and passes in reference order.** Writing rows as they are read is impossible
once anything can be remapped, so the apply pass fills `IdMaps` kind by kind (tags → photos →
templates → swatches → artworks → collections → links → settings) and every reference reads it: an
artwork document's `photo_id`s, a collection's `parent_id` and `cover_artwork_id`, a **smart
collection's filter** (a filter is content that holds foreign keys — `filters.remap_ids` is the pure
half) and `artwork_defaults.style_id`. Documents are stored **verbatim** otherwise: an import is a
restore, not a client save, so the composition solver is not re-run over it (the exporting side had
already applied it, and the next editor save re-solves as usual).

**Safety is checked before anything is read.** Member names (no absolute paths, no `..`, no
backslashes, no drive letters), a bounded expanded size, `checksums.sha256` covering every member
and matching it, each `originals/<sha256>` matching its own name, the manifest's format and
versions, every record and every artwork document parsed. A newer `format_version` is refused
rather than guessed at. Six fixtures cover it, built by rewriting a real archive: a traversing
member, a tampered original, an unlisted file, a future version, a non-ZIP and a ZIP with no
manifest.

**Two decisions that keep an import from being a cliff.** A photo whose original file is missing is
left out of the *export* with a warning (a damaged library is exactly when a backup matters, and an
archive must still stand on its own — the importer refuses one whose records name a file it does not
carry); the artworks that used it still travel, and the import leaves those slots as the placeholder
a new artwork would have, which is the same rule the trash cascade uses. And a render is adopted
straight into the cache only when the manifest's `render_key` — renderer version plus asset-manifest
version, the other two thirds of the render hash — still matches; otherwise it re-renders, which
produces the same pixels anyway. On the dev library that turned 30 re-renders into 30 file copies.

**Surface.** `POST /exports` → a job in the `ingest` lane writing into `exports/<job_id>/`, then
`GET /exports/{job_id}/download`; `POST /imports` + `PATCH` chunks (the upload protocol, so a
dropped connection resumes) → staging job → `GET /imports/{id}/report` → `POST /imports/{id}/apply`.
Both staging areas are swept on a schedule (`archive.sweep`, 6 h). The UI is one page
(`/backup`, `g b`) holding the import flow and the recent exports, plus the same export dialog from
a selection on any grid of artworks and from a collection's header. The CLI does both without a
browser: `the_frame_v2 export -o lib.tfarchive`, `the_frame_v2 import lib.tfarchive [--dry-run]
[--policy …]`.

**Verified**: `make check` green — 948 backend tests (42 new), mypy strict, ESLint, tsc, i18n,
conformance. Driven in a real browser (headless Chromium over CDP against the production build on
trusted localhost, a copy of the 336 MB dev library), each result read back through the **API**
rather than off the screen:

- A full export from the dialog: 41.5 MB, `scope: full`, download link live in the UI.
- That file handed back to the import panel via `DOM.setFileInputFiles`: staging → a report reading
  `Photos 17 already here`, `Artworks 30 same`, `Tags 1 same`, `Collections 4 same`, every policy
  select correctly **disabled** (nothing conflicts) → apply → `left alone: 72`, and the 25 live
  artworks came back byte-identical, render hashes included.
- A partial export from a one-artwork selection on `/artworks`: 3.6 MB, `scope: partial`, and the
  dialog's scope line reads "1 artwork — with the photos and tags they use".
- The *Rendered images* card: JPEG/PNG offered, `the_frame_v2-renders-….zip` written.
- A real conflict: renaming an artwork locally then re-importing gives `Artworks … 1 conflicting`,
  **only that row's** policy select enabled, the button reading `Import (1 conflict)`; choosing
  *Take theirs* restored the title and left a `pre_import` snapshot — the undo, as specified.

Not driven in a browser: resuming an interrupted archive upload (the offset protocol is the photo
uploader's, regression-tested there and covered by a chunked-receive API test), and the CLI's
`--policy` combinations (covered by API tests over the same service functions).

## 2026-09-23 — Phase 9 feedback, second round (remarks.md, 6 items)

**A smart sub-collection contributed nothing to include-nested (#3).** Real bug: the listing scoped
a subtree with `collection_items IN (ids)` — manual membership only — while a smart collection's
artworks are *matches*, not rows. The filter AST already had a helper that unions the two
(`_in_collections`), so the listing, the `collection` clause and `nested_count` now all go through
it: one path for both kinds. A manual parent with a smart child went 3 cards → 7 on toggling, and
the tree's `nested_count` reads 7 to match. `counts()` resolves each smart descendant's filter once
and reuses it across the subtrees that contain it.

**Smart membership is derived, so it is reported apart (#5a).** An artwork carries `collection_ids`
(manual — rows it can leave) and `smart_collection_ids` (filters that happen to match it). The
viewer shows the latter in accent with a sparkle and never offers removal: an artwork leaves a
smart collection by ceasing to match it.

**The viewer footer (#5b).** The metadata line added last round was a full-width child of the
actions row, so the six buttons wrapped onto a third line, left-aligned and cramped. Two explicit
rows now: title, badges and all six actions right-aligned on one line (measured: 6 buttons, 1 row,
x 848 → 1556), collections and tags underneath.

**A transparent `<select>` gets a light popup (#4).** Chrome paints a select's native popup from the
*control's* colours, so the tag filter — the one select in the app using `bg-transparent` — had
`optionBg: rgba(0, 0, 0, 0)` and near-white option text, readable only under the hover highlight.
The closed control screenshotted fine in both themes, which is why measuring the *options* mattered.
`styles.css` now gives `select`/`option` an element-level colour and background (class utilities
still win, so nothing else moved), and the filter is a plain bordered select like the sort one.
After: 236,236,238 on 18,18,19 in dark, 27,27,29 on 244,243,241 in light.

**Deep links (#1).** The open collection lives in the URL (`/collections?id=…`), so a sidebar row
opens *that* collection, a reload keeps it, and the link is shareable.

**Smart collections say why they are read-only (#2).** Expected behaviour — there is no row to hold
an order — but the UI stayed silent. A line under the header explains it, and *Add artworks*, the
reorder grips, the *Manual order* option and the remove action are absent rather than inert.

**`Backspace` removes from a collection (#6).** `Delete` still trashes; taking an artwork out of a
collection is a far gentler act and deserves its own key. While adding it the grid keyboard moved
into one `useArtworkGridCommands` hook, so Artworks, Favorites and a collection's page share the
same set (`c f e Delete / Ctrl+A Esc`) and cannot drift; only the collection page passes the
`Backspace` handler. Measured: 4 items → 3 in the collection, library count unchanged at 30, and a
no-op on a smart collection.

**Verified**: `make check` green — 906 backend tests (2 new: include-nested reaching a smart child,
an artwork's smart memberships). All six driven in a real browser over CDP against the production
build, read back through the API, plus two screenshots where the question was about pixels (the
select in both themes, the footer layout).

## 2026-09-23 — Phase 9 feedback round (remarks.md, 8 items)

Three of the eight were bug reports, and all three reproduced.

**Reordering only worked one way (#6).** Dropping a card always meant "insert before the target",
so dragging a card *forward* asked for the place it already had and nothing moved — exactly the
"only to bring the second artwork first" symptom. The drop now reads the direction: backwards
lands before the target, forwards lands after it. Measured on a labelled A B C D: `ABCD` + drag A
onto C → `BCAD`; `BCAD` + drag D onto B → `BDCA`; one step forward swaps. The card under the
pointer highlights now, so a drop has a visible target.

**Include-nested did nothing (#5).** Real bug in the listing: `manual` sort joins
`collection_items` on the collection you are looking at, so every artwork living only in a *child*
was dropped and the "nested" list came back identical to the flat one. `position` cannot order a
subtree — an artwork has one per collection — so the server refuses the combination
(422 `manual_sort_nested`) rather than quietly answering something else. The page gained a sort
picker that drops *Manual order* while include-nested is on, and the toggle only appears when the
collection actually has children. 3 cards → 6 on toggling, measured. While in there,
`nested_count` summed the children's counts, so an artwork filed in two sub-collections of one
parent counted twice; it counts distinct artworks now.

**Collections could only ever go deeper (#4).** Creation passed the *selected* collection as the
parent with no way to say otherwise, and the tree only accepted drops *on* a row — which is always
another parent. The dialog now has an **Inside** picker defaulting to *Top level* (the collection's
own subtree excluded from the options), and the tree has a drop zone that re-parents to the top
level. `parent_id: null` was always accepted by the server; nothing offered it.

**The rest.** `c` adds the selection to a collection from any artwork grid and from the viewer
(#1); the menu ends with a name field that creates the collection and files the selection into it
(#2); the viewer's footer lists the collections and tags of the artwork and edits both in place
(#3, `collection_ids` on the single-artwork response only); the Photos page filters by tag (#7 —
`tag_id` had been in the API since Phase 2, nothing offered it); and *Add artworks* opens a
searchable picker over the library from inside a collection (#8).

**A conflict the audit uncovered.** Asked for "any other obvious missing shortcut", I added `f`
(favourite the selection), `e` (edit), `Delete` (trash) and `/` (search) — and found that a bare
letter and a chord starting with the same letter are two `tinykeys` instances that each match on
their own. `g c` opened the add-to-collection menu *and* failed to navigate. `app/commands.ts` now
keeps one capture-phase listener that remembers whether the previous key started a chord, and
single-key bindings stand down for the key after one. Measured before/after: `g c` → `/artworks`
with the menu open, then `/collections` with it closed; `g f` no longer flips a favourite on the
way to Favorites; and in the editor `g s` reaches Settings without also skipping the review queue —
a conflict that predated this round. The viewer, being modal, also takes `f`/`e`/`c`/`Delete` away
from the grid underneath it while it is open.

**Verified**: `make check` green — 903 backend tests (3 new: manual+nested refusal, an artwork's
collections, distinct nested counts, moving back to the top level). Every item driven in a real
browser (headless Chromium over CDP against the production build) and read back through the API:
the eight remarks, the three chord cases, and the bare keys still firing on their own. One thing
worth writing down about the harness rather than the app: dispatching a synthetic key on both
`document.body` **and** `window` makes tinykeys see every key twice, which breaks every chord —
dispatch once, on the focused element.

## 2026-09-23 — Phase 9 (organization)

Spec: `docs/organization.md`. Tags, collections, filters, search and the trash.

**One filter, three consumers.** `domain/filters.py` is a pure, validated AST and
`services/library.py` is the only thing that knows how it reaches the schema. The chips in the
filter bar, a smart collection's stored definition and what `POST /artworks/query` compiles are
the *same object*, so "save this view as a smart collection" is a copy rather than a translation.
Two clauses deliberately leave the `artworks` table — `taken_at` and `place` hold when **a photo
the artwork uses** matches, compiled as an EXISTS over `artwork_photos`, which is the only reading
a multi-photo artwork can support. Bounds are structural (64 clauses, 4 levels, 200 values), and
an empty group matches everything.

**Collections** are a tree with REAL `position` among siblings and among a manual collection's
items, so a drag-and-drop move or reorder writes one row (midpoint, renumbering only when the
doubles run out at `1e-9`). A recursive CTE answers `include_nested` for both counts and listings.
Three refusals the server owns: a cycle (`collection_cycle`), more than 8 levels, and a smart
collection referencing itself or a smart collection that references it back (`filter_cycle`).
Deleting a collection takes its subtree and leaves the artworks alone — it is not a trash
operation.

**Search** (`services/search.py`) fills the FTS5 table 0001 already created: an artwork's title,
its tags' names and the file names and places of its photos; a photo's name, place, camera and
tags; a collection's name and description. Writers update it inside the transaction that changed
the row, so it never outlives what it describes, and it stays disposable — `reindex_all` rebuilds
it and the app does that at startup when the table is empty. User text becomes a token-only prefix
query, so nothing a user types can be read as an FTS5 operator.

**Trash.** `deleted_at` + a shared `trash_batch_id`: what was deleted together is restored
together. Deleting photos an artwork uses is a *decision*, so `POST /trash/preview` lists the
affected artworks first and the cascade then picks between `trash_artworks` (they follow into the
same batch) and `empty_slots` (they stay, the photo leaves their slots, the artwork goes back to
draft and a `pre_trash` snapshot makes it undoable). The emptied document goes back through
`artworks.validated`, so an attached composition re-solves exactly as it would for a new artwork
with a missing photo. Purge is what frees disk — originals, thumbs, proxies, palettes and render
caches — and it runs daily through a new `JobQueue.schedule_every` (coalesced) as well as on
demand.

**UI.** The collection tree in the sidebar (artworks dropped on a row are filed), a chip filter
bar + search + sort + bulk actions on Artworks and Favorites, a Collections page with DnD and
manual ordering, a Tags manager, a Trash page, the cascade dialog on the Photos page (`Delete`),
`f` for the artwork's favourite in the editor, and read-only phone browsing at `/m/browse`.

Migration `0005` adds the indexes those queries lean on. `scripts/seed_library.py` fills a
10k-item library (a few dozen real originals, artworks cloned from them) for the AC.

**Verified**: `make check` green — 900 backend tests (37 new: `tests/unit/test_filters.py`,
`tests/api/test_organization.py`), mypy strict, ESLint, tsc, i18n, conformance unchanged. Driven
in a real browser (headless Chromium over CDP against the production build on trusted localhost),
every result read back from the **API**, never off the screen:

- **Filter bar**: adding a *Favorite* chip on a 300-artwork seeded library cut the grid to 28,
  and `POST /artworks/query` with the same AST returned the same 28.
- **Collections**: 7 rows in the tree; a manual collection showed 20 cards with reorder grips and
  the include-nested toggle, the smart one 18 cards with neither; creating "Driven by CDP" from
  the sidebar button filed it under the selected collection (`parent_id` set); a reorder moved the
  third item to the front and the manual sort returned the new order.
- **Smart collections**: the dialog's live count came from `POST /filters/validate` (298 with no
  clause, 0 for *Quality = upscaled*, 224 after switching to *Downscaled*); saving persisted the
  AST, re-opening it rebuilt the chips from what was stored, and the page then listed 224.
- **Tags**: rename `sea` → `ocean` and a colour click both landed in the DB (`#ef4444`); merging
  `ocean` into `winter` took it from 57 to 84 artworks and deleted the source.
- **Trash**: selecting a photo and pressing the bin listed *75 artworks use them* with both
  cascades; `empty_slots` left 75 incomplete drafts whose slot carried `photo_id: null` and
  `quality_lock: free`, each with a `pre_trash` snapshot; `trash_artworks` on another photo put
  1 photo + 75 artworks in one batch and restoring that batch brought all 76 back; emptying the
  trash from the page reported *Freed 2.3 MB* and the data dir actually shrank (3140 → 2920 KiB).
- **Favorites / mobile**: the Favorites view listed only hearted artworks and un-hearting one
  removed it live; `/m/browse` showed the tabs (Artworks, Favorites, each collection), 200 cards,
  27 favourites, and no mutating control at all.

Two things the harness, not the app, got wrong and that are worth remembering: each open tab holds
an SSE connection, so **six tabs exhaust the per-origin connection pool** and the seventh renders
an empty page (close tabs between runs); and openapi-fetch binds `globalThis.fetch` at
`createClient` time, so patching `window.fetch` afterwards intercepts nothing — read the result
through the API instead. The HTML5 drag-and-drop gestures themselves (dropping an artwork on a
collection row, dragging a collection onto another) were **not** synthesized: the endpoints behind
them were driven directly and the UI state they produce was checked, but the drag itself has not
been exercised in a browser.

One real bug the browser found: the merge dialog's description showed a raw `{{name}}` (the
interpolation argument was missing). Fixed.

## 2026-09-23 — Phase 8 (templates)

Spec: `docs/templates.md`. Templates rebuilt around Phase 7's recipes.

**A layout is a recipe and its parameters.** `LayoutDocument` is now the `composition` block minus
what belongs to one artwork (the caption's text, `detached`), so applying a layout, saving one and
creating from one are all the same code path as the Simple editor's. The absolute-rect layout code
is gone — `build_document`, `map_rect_to_area`, `LayoutSlot`, `LayoutCaption` and the `placement`
field of `POST /artworks` with it — and `assets/presets/layouts.json` was rewritten as 13
parametric built-ins. Migration `0004_parametric_layouts` deletes the old rows (all built-in: there
was no layout CRUD before), clears the artworks' `origin_layout_id` so nothing shows a bogus
*outdated* badge, and drops `artwork_defaults`, which became `{style_id, recipe_id, format}`.

**`restyle` / `relayout`, mirrored.** The editor applies a template to its working document and the
server applies the same one during a push update, so both live in `domain/templates.py` ↔
`editor/core/templates.ts` with 16 whole-document conformance cases (`templates.json`). Two rules
the fixtures pin: a style's `margins` are never applied (under a block the margins are derived, and
re-dressing must not move a photo), and the style's band **is** `composition.border` — applying a
style and a layout together applies the layout first so the style wins.

**Management.** Full CRUD for both kinds (built-ins read-only), duplicate, "Save as style/layout"
from an artwork, `.tfstyle.json` / `.tflayout.json` export/import, usage, `apply-template` (snapshot
+ origin) and **push update** with a server-side dry run. A layout skips an artwork holding another
number of photos or one whose slots were placed by hand. Every touched artwork is snapshotted
`pre_template_update` first — that snapshot is the undo the AC asks for.

**UI.** A Templates page (tabs, cards whose previews are drawn by the solver itself, editors for
both kinds, push-update dialog with per-artwork badges), *Save as style/layout* and a saved-layout
picker in the Simple panel, saved layouts in the create dialog, and the new defaults in Settings.

**Verified**: `make check` green — 863 backend tests, 362 conformance cases (both languages), mypy
strict, ESLint, tsc, i18n. Driven in a real browser (headless Chromium over CDP against the
production build on trusted localhost), each result read back from the **API**, not off the screen:

- Templates page: 6 style cards and 13 layout cards, tab switch, a built-in's *Edit* disabled,
  *Duplicate* creating "2 × 2 copy", editing that copy's gap to 220 px (stored `gutter 220/220`,
  `revision` 2), and the push-update dialog showing the dry run ("0 artwork(s) will change").
- Editor: the Simple panel offers only the saved layouts that fit the photo count (3 of 13 on a
  3-photo artwork); applying "1 + 2" stored `recipe: three-hero-left` with the hero at
  2108×1840 and recorded `origin_layout_id`; *Save as style…* created a style from the artwork.
- Push update end to end: picking that style in the editor's Background dropdown recorded
  `origin_style_id`, patching the style then pushing changed the artwork's mat and turned the
  style's 24 px band into the block's border **without** moving a rect or changing the recipe, and
  left a `pre_template_update` snapshot that restores.
- Settings: style, layout and format dropdowns, the last two defaulting to "Follow the photos".

**Follow-up the same day**: the template editors were too small to judge a preview in, so both moved
into a full-window dialog (`Dialog` gained `size="full"`) with the controls in a column and the
preview filling the rest — measured over CDP at 1552×952 for the dialog and 1110×790 for the
preview pane in a 1600×1000 window (it was ~256×144), no overflow, Save always reachable, and the
two columns stacking below `lg`.

**Second follow-up (same day, remarks.md #1 and #2)**: the template editors put their settings on
the **right**, like the artwork editor (measured over CDP: preview at x = 45 w = 1142, settings at
x = 1203 w = 352 in a 1552×831 dialog, no horizontal overflow), and the **shadow** stopped being a
setting you could see but not judge:

- The style card drew its shadow as a hard rect peeking out from behind the photo — a 6 px offset
  under a 12 px band is invisible, and recessed and raised looked identical. It is now the
  renderer's own algorithm in SVG filters (`σ = blur / 2`, cast by photo + band, the recessed one
  the blurred complement of the layer clipped back inside it). Screenshots of the same style at
  *None* / *Recessed* / *Raised*: 2.3 %, 2.6 % and 4.8 % of the preview's pixels differ by more
  than 2/255, up to 54/255 — the shadow reads at a glance now, and the two kinds read apart.
- The frame-style editor offered only the type and the opacity; it now offers the same six fields
  as the editor (`ShadowFields`, shared by the Simple panel, the Advanced Style panel and this
  dialog). Verified end to end: setting *Raised*, blur 96, opacity 70 % and offset 24 saved
  `{"type": "drop", "offset_x": 24, "blur": 96, "opacity": 0.7}` and took the style to revision 2.
- The Simple panel had no shadow control at all — the setting looked dropped rather than
  Advanced-only. It has a **Shadow** section now (sections read `Layout, Format, Margins, Photos,
  Background, Border, Shadow, Caption`), and it dresses **every** photo: clicking *Raised* and
  pulling blur to 120 on a 3-photo artwork wrote `drop / 120` into all three slots, `detached`
  stayed `false`, and the recipe and all three rects were untouched (version 77 → 78) — the block
  never writes `shadow` (§3.7), so it neither detaches nor re-solves.

**Not verified**: the batch-create AC at 40 photos (the dialog is Phase 7's, plus a saved-layout
choice), template file *import* through the file picker (a `<input type=file>` cannot be driven over
CDP without a real file dialog — the endpoint is covered by an API test), and the Templates page on
a narrow window.


## 2026-09-16 — Phases 0–3

**Phase 0 (spikes)**: S1 decoding matrix done (`research/decoding.md`); S2 protocol + heuristics done, real
Android picker verification pending a device (`research/phone-uploads.md`); S4 hashing benchmark done on
desktop; S3 moved to the start of Phase 4 (needs the renderer).

**Phase 1 (foundations)**: uv/pnpm projects, settings, SQLite + Alembic (full schema), problem+json errors,
job queue, SSE broker, CLI, SPA serving, OpenAPI → TS types, i18n, themes, command palette + shortcuts,
Makefile, Dockerfile/compose (image not built here: no Docker daemon access), AGENTS.md, ADRs 0001–0006.

**Phase 2 (security & devices)**: localhost trust, setup code, QR pairing, roles, Host allowlist, CSRF guard,
security headers, rate limiting, device management UI, optional TLS settings.

**Phase 3 (ingest & library)**: resumable chunked uploads with dedupe and hash verification, ingest job
(sniff, probe, colour-managed proxies/thumbnails, EXIF, GeoNames reverse geocoding, quality warnings),
HEIC rejection, desktop drag & drop (files and folders), phone upload page with metadata, Photos grid
(virtualized, search, details drawer with tags), Inbox (selection, dismiss).

**Verification**: 74 backend tests; ruff, mypy strict, tsc, ESLint (0 errors), i18n check green; end-to-end
run of the built app: LAN pairing via QR link, chunked upload with interruption/resume, desktop drop upload
with live inbox update, role redirects, HEIC rejection.

**Bugs found and fixed during E2E**: upload metadata wiped on resume; command registration render loop;
capture times shifted by the browser timezone; city districts ("Lyon 01") chosen as place names.

**2026-09-17 — real-device feedback**: Android zeroes GPS for browser uploads and the photo picker renames
files → `location_removed` warning and merge of later copies by content fingerprint (migration 0002,
`photo_hash_aliases`, backfill job); startup log shows the LAN URL; Docker image PATH fixed; fixed-size grid
thumbnails.

**2026-09-17 — LocalSend receiver** (ADR-0007, `docs/localsend.md`): protocol v2 receive side on TLS port 53317
with multicast discovery, admin approval of new devices (dialog + Devices section), hand-off to ingest.

## 2026-09-17 — Phase 4 (artwork domain & renderer)

**S3 spike** (`research/render-parity.md`): Canvas 2D vs pyvips in Chrome — shadows max diff 3/255 (σ = blur/2
confirmed), texture identical, rotated slots differ only on antialiased edges, caption ink boxes within ±2 px.

**Domain**: artwork document v1 (Pydantic, JSON Schemas in `docs/schemas/`, precise 422 errors, migrations
hook), geometry/quality/placement mirrored in TypeScript (`frontend/src/editor/core/`) and checked by 77 shared
fixtures (`pnpm conformance` + pytest), frame style/layout documents and `build_document`.

**Renderer** (`imaging/render.py`): mat + texture, bands, inner/drop shadows, exact rotation, captions (Pango,
bundled OFL fonts), PNG master + 4:4:4 JPEG + thumbnails, region renders, scaled renders. Parallel decoding made
the 9-slot collage 3.8 s (budget 6 s). Built-in presets: 6 frame styles, 7 layouts. Render cache + coalesced
render jobs + `artwork.rendered` SSE.

**API**: artworks CRUD-ish (create from photos + style + layout, `PUT document` with `If-Match`, patch, validate,
duplicate, trash, snapshots with restore, render/thumb endpoints), frame styles/layouts/fonts/textures (read),
`POST /render/region`.

**UI (review aid until the Phase 5 editor)**: Inbox "Create artworks" (style, layout, placement), Artworks page
(grid, filters) and full-screen viewer of the server render (favorite, ready/draft, duplicate, download, delete).

**After the user's review (2026-09-17)**: Photos page gained selection (click, Ctrl/Shift-click, `$mod+a`,
`Escape`, `i` details) and "Create artworks" (`n`, also in the details drawer) so any photo — including processed
ones — can get more artworks; Float mount preset has no band any more (seeding updates the built-in row; existing
artworks keep their document).

**Verification**: `make check` green (220 backend tests incl. 7 golden images, conformance, mypy, tsc, ESLint);
native 3840×2160 photo renders bit-identical to its decode; E2E on a copy of the dev library with real phone
photos (create 6 artworks, polaroid pile via API, viewer shortcuts, live updates).

**Known limits / follow-ups**: collections can only be listed (creation in Phase 9 — renumbered when the
simple editor became Phase 7), so the phone collection picker stays empty; trashed artworks cannot be
restored before Phase 9; no ESLint rule for literal JSX strings
yet; Docker image not rebuilt/tested with the fonts (Pango/fontconfig in the slim image); collage renders hold
all decoded originals in memory.

**LocalSend "already sent" handling (2026-09-17/18, user remark)**: re-sending a photo already in the library was
silent and confusing. Now nothing is transferred twice, the sender's app sees a plain successful transfer (no
error, no text message — both were tried and dropped as more confusing than helpful; when every offered photo is
already known the smallest one is transferred and dropped, because an app that is given no file to send shows no
transfer screen at all), and every received photo,
already sent or not, goes **back to the inbox** — the rule for all uploads, so re-sending is how you bring a
photo back (`photo_copies.receive_again`; a trashed one is restored). The web upload tray now mirrors LocalSend
transfers ("Already in your library — back in the inbox · from <device>"), including skipped and unsupported
files. Behaviour of the LocalSend app checked in its source (`docs/localsend.md` "Already-sent photos").
A photo coming back without being ingested publishes `photo.updated`, otherwise open pages only showed it after a
manual reload (user report). Verified: `make check`; TLS end-to-end runs against a live server with real photos
(including the SSE the browser receives). Not tried on a real phone.

## 2026-09-18 — Phase 5 (editor, single photo) — **partially verified, see "Open items"**

**Pure core (mirrored Python/TypeScript, 107 conformance cases, was 77)**: constraint solver
(`domain/constraints.py` ↔ `editor/core/constraints.ts`, §7.3) — slot resize with *cover* semantics and an
anchor, crop resize/pan/zoom, lock switching, crop-ratio switching; alternatives (`domain/alternatives.py` ↔
`alternatives.ts`, §7.6) returning ready-to-apply patches. Both keep the two document invariants (aspect
consistency and the quality lock) so the editor can never produce a document the server rejects — asserted for
every solver result in `tests/unit/test_constraints.py` (19 behaviour tests). Snapping (`snapping.ts`, §7.5) is
client-only (screen-pixel tolerance) but pure: the margin controls snap to the *quality point* (scale = 1).

**Backend additions**: photo palette (`imaging/palette.py`, k-means in OKLab on a 64×64 sample → dominant,
muted and complementary entries; deterministic, cached in `cache/palettes/`), swatches CRUD, curated mat
colours (`GET /presets/colors`), `GET/PUT /artwork-defaults` (default style/layout, Settings UI), font metrics
in `GET /fonts` so the editor places caption baselines exactly like the renderer. 6 new API tests.

**Editor** (`frontend/src/editor/`): Konva canvas (mat + tinted texture tile, bands, photo from the proxy in
oriented space, inner/drop shadows, zoom/pan, selection, margins guide, magenta snap guides), crop tool
(drag/wheel pan & zoom inside the slot), framing panel (placement, margins with linking, quality lock, crop
ratio, 90° turns/flip, rotation), style panel (mat colour + texture strength, bands ≤ 3, shadow), colour picker
with saved swatches/presets/photo palette, alternatives panel with per-option previews, loupe (server region
render), TV preview (fullscreen, 3 bezels, matte overlay), artwork sheet (title, tags suggested from the
photos, favourite, snapshots + "revert to when opened"), review queue (filmstrip, progress, validate & next,
skip, J/K), undo/redo on Immer patches (grouped per gesture, 200 steps), autosave (800 ms debounce, `If-Match`,
409 → keep mine / take theirs). Creating artworks from the Inbox or Photos now goes straight into the review
queue (`/editor/$artworkId?queue=…`).

**Bugs found and fixed during the browser E2E** (all three froze the tab — worth remembering):
1. *Render loop*: `openArtwork` rewrote `sizes` with a fresh object on every call while the photo query
   produced a new array on every render. Guarded, and the sizes map is now keyed on its values.
2. *One React render per mouse event*: crop dragging (and the loupe's pointer reporting) re-rendered the whole
   editor and redrew the canvas per event; the event queue outran the renderer. Both are now accumulated and
   flushed once per animation frame (`EditorStage`) — which is also what the 60 fps budget asks for.
3. *Inner shadow*: S3's "ring drawn 20 000 px away" makes the browser allocate a surface spanning the shape and
   its shadow. The ring is now drawn around the layer and clipped (`docs/research/render-parity.md` corrected).
Also: a 404 artwork left the editor spinning forever (now an error with a way back), and `Escape` in the TV
preview closed the preview *and* left the editor (the preview now captures the key).

**Verified**: `make check` green (281 backend tests, 107 conformance cases, mypy strict, ESLint, tsc, i18n).
In a real browser against a copy of the dev library (17 photos, 14 artworks): the editor opens an artwork,
margins re-place the slot live with the badge following (42 % → 32 %), lock switching applies and autosaves
(native keeps scale exactly 1 and pushes the change into the margins as §7.4 requires — the values matched a
hand-run of the pure functions), crop ratio 1:1 re-crops, crop dragging pans the photo, linen texture and the
recessed shadow render, and every change autosaves and is reloaded correctly.

**Open items when the session ended** — all closed on 2026-09-19, see below.

## 2026-09-19 — Phase 5 verification & sign-off

Driven in a real browser (production build served by the backend on trusted localhost, against a copy of the
dev library). Everything left open on 2026-09-18 was exercised; three bugs came out of it.

**The loupe is not broken.** The panel opens on `Z` and on the button, and the 512² server region appears
(the `POST /render/region` round trip is ~75 ms). What failed last session was the *screenshot tool*: the
Chrome extension's `Page.captureScreenshot` times out for as long as the loupe's blob image is on screen (the
page itself stays responsive — JS keeps answering), so the panel was there and invisible to the harness.
Same cause as "`computer.zoom` and fullscreen capture time out on this page": a tooling limit, not the app.
Related: a Konva canvas sometimes composites **black** in a captured screenshot while its pixels are correct
(verified by reading the canvas back with `getImageData`) — never conclude "the canvas is empty" from a
screenshot alone.

**Bugs found and fixed**:
1. *`Escape` in the colour popover left the editor.* Radix handles `Escape` in the capture phase on the
   document; the command registry (tinykeys) listens on `window` in the bubble phase, so both ran: the
   popover closed **and** the editor navigated to `/artworks`. The layers now swallow the key
   (`onEscapeKeyDown` → `stopPropagation`) in `shared/ui/Dialog`, `editor/panels/ColorField` and
   `features/artworks/ArtworkViewer`.
2. *Captions were drawn ≈ 14 TV px too high* (96 px font) and measured without their weight: the editor
   applied the renderer's baseline rule to a Konva `Text` node, which places its `y` differently
   (`(ascent − descent) / 2 + lineHeight / 2` below it, `textBaseline = "alphabetic"`).
   `editor/canvas/fonts.ts` now replicates Konva's own rule and font shorthand — details and numbers in
   `docs/research/render-parity.md`. The font metrics from `GET /fonts` are no longer needed by the canvas
   (the endpoint keeps them; the caption editor of Phase 6 will want the catalogue anyway).
3. *The Settings default style/layout were ignored* by the "Create artworks" dialog, which hardcoded
   Gallery recessed + Single. It now follows `GET /artwork-defaults` (the user's pick still wins; the
   defaults are derived during render, not copied into state when the query answers).

**Client vs server parity (Phase 5 AC)**: measured in the page on three artworks — MAE **1.05 / 1.22 / 1.52**
per channel (max 52 / 59 / 169, on antialiased edges and glyph stems), caption ink box within one canvas
pixel of the server's. Table and method: `docs/research/render-parity.md`.

**Also verified in the browser**: undo/redo (`Ctrl+Z` / `Ctrl+Shift+Z`) across an alternative being applied;
the alternatives panel (an upscaled slot offers *keep framing / shrink the photo / fit in the mat* with
previews, and applying one switches the lock and re-places the slot: 140 % → native 100 %); the colour
popover (curated presets, photo palette with dominant/muted entries, saving a swatch → `POST /swatches`);
the TV preview (fullscreen, bezel, `Escape` closes only the preview); "validate & next" through the draft
queue (progress counts down, the next draft opens); Inbox `$mod+a` → `n` → create → straight into the review
queue with the artwork built from the default style (Linen after changing it in Settings).

**Not verified**: the 40-photo keyboard-only run of the AC was done on a 11-draft queue, not 40; captions are
still read-only (Phase 6); free-form slot move/resize/rotate, multi-slot snapping and equal-gap guides are
Phase 6 as planned.

## Post-Phase-5 feedback round (2026-09-19)

Six items from the user's `remarks.md`, all driven in a real browser against a copy of the library
(`/tmp/e2e`, backend :8799 + Vite :5199):

1. *Margins could not be reduced under `native`.* `fit_in_mat` only re-derived the crop when it **overflowed**
   the available area, so growing the margins shrank the photo for good: shrinking them back left a small crop
   in a wide mat. It now re-derives on every margin edit, both ways (§7.4). Measured: top margin 280 → 700 →
   280 on a 3072×4080 photo gives crop 1175×1560 → 858×1140 → 1175×1560, i.e. an exact round-trip.
2. *A typed margin did nothing.* The number field snapped typed values with the §7.5 tolerance of 8 *screen*
   px — tens of document px on a fitted stage — so `1` next to a `0` margin came back as `0`. Snapping is now
   for dragged values only, and `NumberField` keeps the typed text while focused instead of fighting the
   caret with the re-placed document value.
3. *`?` now closes the cheat sheet* as well as opening it (`toggleCheatSheet`).
4. *`Enter` confirms the "Create artworks" dialog.* Radix focused the first tabbable element — the close
   cross — so `Enter` cancelled; the dialog now focuses its submit button (`onOpenAutoFocus`).
5. *Photo zoom is now a visible control*, not only the wheel: a slider + number field in the Photo section,
   `1×` = the whole photo at the current crop ratio, up to `8×`. Checked: `2×` on a 3072 px wide photo gives a
   1536 px crop under `native` (margins follow) and `1.5×` a 2048 px crop under `no_upscale`.
6. *Mirrored margins*: `margins.mirror_x` / `mirror_y` keep left = right / top = bottom, both when a side is
   edited and when native linking redistributes the free space. Two toggles next to "link all sides".

Schema change (`mirror_x`, `mirror_y`, defaults `false`) ⇒ `make gen-api`; geometry change ⇒ Python + TS +
four new conformance cases (`margins mirrored`, `margins mirrored on one axis`, `fit in mat native grows the
crop back`, and the mirror arguments on every `margins_for_slot` / `alternatives` case).

### Bundle size (2026-09-19)

`make serve` warned that the single JS chunk passed 800 kB. Measured by attributing generated bytes through
the sourcemap: react-dom 203 kB, **konva 181 kB + react-reconciler 126 kB** (the latter pulled in by
`react-konva`), router-core 51, i18next 61, query-core 35, virtual-core 23, qrcode 22, hash-wasm 18, app code
~90.

Done now: `qrcode` (pairing dialog) and `hash-wasm` (upload hashing) are loaded on demand — 40 kB raw / 16 kB
gzip off **every** page, the phone upload page included; main chunk 1051 → 1011 kB raw, 334 → 318 kB gzip.
`chunkSizeWarningLimit` sits just above that, so the warning still trips when a new dependency lands.

**Not** done: making the editor route lazy, which is where the real ~315 kB is (konva + reconciler +
react-colorful). Over the LAN under immutable hashed names that weight costs a few milliseconds, and the split
needs a stale-chunk error boundary first: `build.emptyOutDir` deletes the old hashed files, so a tab opened
before a rebuild would 404 on entering the editor (`/assets` is `StaticFiles`, so it is a clean 404, not
`index.html`). Worth doing when Phase 6 grows the editor further.

## 2026-09-21 — Phase 6 (multi-photo compositions)

**Pure core (mirrored Python/TypeScript, 134 conformance cases, was 107)**: `domain/arrange.py` ↔
`editor/core/arrange.ts` (§7.7) — bounding box, align on six edges, distribute with equal gaps, same size,
and where a slot the user adds lands (`new_slot_size` / `new_slot_rect`, cascading off the slots already
there). `ratio_label` gained its TypeScript mirror. Snapping (client-only, §7.5) gained the **equal-gap**
candidates promised for this phase plus `snap_rect`, which snaps a dragged slot by its left edge, centre and
right edge at once; 22 behaviour tests in `tests/unit/test_arrange.py`.

**Editor**: slots panel (front-first list = the z-order, drag to reorder, add/remove, photo picker with
search, replace, swap, empty a slot, fit/fill), free-form move/resize/rotate on the canvas (eight handles and
a rotation knob drawn by `SelectionOverlay`, hit-tested by `canvas/hit.ts`; `Shift` snaps the angle to 15°,
`Alt` disables snapping), multi-selection by Shift-click with align/distribute/same size/copy decorations,
caption editing (panel for every property, double-click on the canvas for the text, drag to move), position
and size fields for manual slots, and the shortcuts `a` (add slot), `t` (caption), `[` / `]` (z-order),
`Delete`, `$mod+a` (select every slot); the arrow keys now nudge the selected slots (or the caption), and
still the crop under the crop tool.

**Bugs found while driving it**:
1. *A slot added with a freshly picked photo was built as an empty one* — the editor only knows the sizes of
   the photos already in the document, so the crop took the slot's shape instead of the photo's (and the lock
   fell back to `free`). `store.ensurePhotoSize` now fetches the size before the operation runs (invariant 13).
2. *"Same size" made slots bigger than the reference*: the constraint solver resizes with **cover** semantics,
   so a slot whose aspect differs from the reference grew past it. It now fits *inside* the reference box.
3. *Clicking one slot of a multi-selection did not collapse the selection onto it* (the selection is kept on
   mousedown so the group can be dragged); it now collapses on mouseup when the pointer never moved.
Also fixed on the way: captions rotated around their text box on the canvas instead of their anchor point,
where the renderer pivots (`docs/research/render-parity.md`) — invisible until captions became editable.

**Verified** (production build served by the backend on trusted localhost, against a copy of the dev library):
`make check` green (332 backend tests, 134 conformance cases, mypy strict, ESLint, tsc, i18n). In the browser:
adding a slot from the picker (placement switches to `manual`, 4:3 photo → 908×684 slot, lock `no_upscale`),
dragging it (snapped its right edge to the canvas centre), resizing by the SE handle (908×684 → 1217×916 with
the crop growing to the full 4080×3072 photo, aspect consistent), rotating by the knob (38.1°, lock kept),
Shift-click multi-selection ("3 slots selected"), distribute (gaps 517/518), align top, same size (a 3:4 slot
became 511×679 inside the 900×678 reference), copy decorations, z-order by button and by `]`, nudging with the
arrows (227 → 230) with undo/redo, swapping two photos (each re-cropped to its new slot), emptying and
re-filling a slot, adding a caption and editing it inline, dropping a photo from the picker onto the mat (a new
slot lands under the pointer), and **equal-gap snapping** (dragged 20 px short of the stop, landed exactly on
it; `Alt` moved the raw 35 px instead). The server rendered every state (`render.png` 200, 5 slots + captions).

**Tooling note**: the Chrome-extension harness could not drive the app at all this time — the page never goes
idle (the SSE stream), so `executeScript`/`--dump-dom`/`--virtual-time-budget` all time out. The session used a
throwaway CDP driver instead (headless `chromium --remote-debugging-port` + `Runtime.evaluate`), which works
well; two harness gotchas are now in AGENTS.md (dispatch mouse events on the `<canvas>`, give synthetic
`KeyboardEvent`s a `code`). Because that tooling is not dependable, browser verification is now written down as
a **soft** requirement (`docs/PLAN.md` §13.6 and DoD item 5): still the preferred evidence for UI work, but a
phase is no longer held back by it — what could not be driven is recorded here instead.

**Not done / follow-ups**: no marquee (rubber-band) selection — slots are picked by click and Shift-click; the
photo picker has search but no tag/date filters; a dropped photo may land partly outside the canvas (allowed by
the document, clipped at render); the editor route is still not lazy (the bundle note of 2026-09-19 stands, and
this phase added ~15 kB of editor code).

## 2026-09-21 — Phase 7 stage 1 (composition block, solver, recipe catalogue)

The parametric foundations of `docs/simple-editor.md`. **Nothing in the UI uses them yet** — this is
the layer stages 2–4 build on.

**The document** gained an optional `composition` block (`schema` stays 1, so no migration and every
existing document stays valid): recipe id, `balance`, `outer`/`gutter` per axis, `format`, `border`,
`caption`, `detached`. The catalogue checks — the recipe exists, its cell count matches the slots,
`balance` is in range — need the catalogue, so they live in `validate_references` and surface as
`unknown_recipe` / `recipe_slot_count` / `balance_out_of_range` / `balance_not_supported`. Two rules
are structural and rejected by the model itself: `format: "original"` needs exactly one slot, and a
ratio's terms are ≤ 1000. A **detached** block may hold any slot count — the slots are the truth then,
so an artwork hand-edited in Advanced mode still round-trips.

**The solver** (`domain/composition.py` ↔ `editor/core/composition.ts`, 186 conformance cases, all
agreeing first try) implements §3: `fill` as a weighted split with exact gutters, and ratio formats
through the bottom-up affine relation `w = α·h + β` on **footprints**, fitted and centred in the
available area, then walked top-down with float edges. Plus `block_area` (the caption band),
`block_margins` (what §3.7 writes back to `margins`) and `refit_crop` (§4.1, centre + zoom kept).

**The catalogue**: `assets/presets/recipes.json`, 17 recipes — 1 single, 4 pairs, 5 triples, 5 quads,
one each for 5 and 6, seven of them declaring a `balance` range. Not a template: no DB table, no
seeding, stable ids, served read-only by `GET /api/v1/recipes` (admin) and read straight off disk by
the conformance script, so the client and both solvers share one source. Names are in i18n under
`recipes.*`.

**Two spec bugs found while implementing it**, both now fixed in `docs/simple-editor.md`:
1. *The worked example was off by one*: it rounded the block's float **height** (1591) where the
   solver rounds **edges** (284.4 … 1875.6 → 284 … 1876, so 1592). The same reason makes a cell's
   aspect exact only to `1 + r` px of width, not the 1 px §8 promised — the test asserts the honest
   bound now.
2. *§3.5 said an `auto` cell takes "the photo's own aspect"*, which is exactly what the `original`
   format already means — so every ratio chip would have been a no-op for a single photo. `auto` now
   means the format turned the photo's way (portrait photo + `3:2` → a 2:3 cell), which is what §3.1's
   "the photo's own orientation" says.

Also decided while implementing: the over-constrained recovery of §3.6 is a **fixed ladder** (gutters
scaled ×10/10…0/10, then `outer`) rather than the bisection the spec suggested — the two solvers must
agree bit for bit, and eleven divisions by ten give identical doubles in Python and JavaScript.

**Verified**: `make check` green — 674 backend tests (was 332), 320 conformance cases (was 134), mypy
strict, ESLint, tsc, i18n. 152 of the new tests are behaviour tests in `tests/unit/test_composition.py`
(tiling, aspects, centring, balance monotonicity, borders, no overlap, totality at every slider
extreme, crop preservation); 4 are API tests covering the catalogue endpoint and the composition
problem codes. **Not driven in a browser** (§13.6): stage 1 ships no UI, so there is nothing to drive —
the endpoint is covered by an API test and the solver by conformance on both sides.

**Not done** (stages 2–4): the server does not re-solve on save, `POST /artworks` still takes a
`layout_id`, and there is no Simple panel, mode switch or `Re-apply layout`. `settings.artwork_defaults`
still names a style + layout (Phase 8, §10).

## 2026-09-22 — Phase 7 stage 2 (server authority)

The composition is now the **source of truth** for the geometry, not a decoration of the document.

**The write-back** (`docs/simple-editor.md` §3.7) is one pure, mirrored function —
`composition.apply` ↔ `applyComposition` — and it is the only implementation of that table: rects
from the cells, rotation zeroed, crops re-fitted around their previous centre at their previous
zoom (§4.1), `crop_ratio` from the cell, `no_upscale` downgraded to `free` when the framing would
upscale, the border as a band, `margins` = the block's footprint insets, `placement = manual`, and
the one derived caption. 17 conformance cases run it **document in, document out**, so Python and
TypeScript agree field by field rather than on rects alone — they did, first try.

**On save**: `validated()` parses, checks the library references, then re-solves, so `PUT document`
and snapshot restore share one authority. A client bug can no longer persist a wrong rect, and an
API test proves it: half-size rects at the origin come back as the solved ones, with the reframe
intact and the lock downgraded to `free`. A **detached** block is stored verbatim (§5).

**On create**: `POST /artworks` takes `composition: {recipe?, format?, balance?, outer?, gutter?,
border?, caption?}`, all optional — and it is now the **default**: without a `layout_id` the photos
get the first recipe for their count, `original` for one photo and `fill` above. An explicit
`layout_id` still builds a Phase 6 document with no block, which is what the current create dialog
and the Advanced editor use. New codes: `unknown_recipe`, `no_recipe`, `recipe_slot_count`,
`layout_and_composition`.

**Three decisions the spec did not pin**, now written into §3.7: the caption baseline is
`1.05 × size` below its line's top (pure number, no font metrics, computed from the nominal `outer`
so a relaxed block does not drag the text with it); the composition owns the caption's *text and
side* while the document owns its *typography* (so a restyled caption survives a re-solve); and a
blank caption text derives no caption at all (the document model requires `text` ≥ 1 char).

**One bug found by reasoning about `aspect_consistent`**: `refit_crop` scaled the largest crop's
width *and* height by the zoom, rounding two independent sides. The error budget of
`aspect_consistent` is exactly `(rect.w + rect.h)(1 + k)/2` — the two roundings can reach it, so
the server could have rejected its own output. The height now comes from the width and the ratio;
the four existing fixtures were unchanged by the fix (verified by hand), and a parametrized test
re-validates an applied document for every recipe × format.

**Verified**: `make check` green — 817 backend tests (was 695), 337 conformance cases (was 320),
mypy strict, ESLint, tsc, i18n. **Not driven in a browser** (§13.6): stage 2 ships no UI. The
render path is covered anyway, since every artwork the API tests create now goes through the
composition path and renders.

**Known gap, closed by stage 4**: the Advanced editor ignores the document the server returns, so a
free-form slot move on a *composition-backed* artwork would be silently re-solved away. Nothing
reaches that state today — the create dialog always sends `layout_id`, so every artwork the UI
makes has no block — but stage 4's `detached` flag (set by the first free-form edit) is what makes
it safe, and it must land before the Simple/Advanced switch does.

## 2026-09-22 — Phase 7 stage 3 (the Simple panel)

The parametric editor is now something you can use: pick a layout, move two sliders.

**The panel** (`editor/panels/SimplePanel.tsx`) follows §6.2 top to bottom — Layout, Balance,
Format, Margins, Photos, Background, Border, Caption. Every control writes into the `composition`
block and lets `applyComposition` re-derive the geometry, so the editor previews exactly what the
server will store (the same mirrored function, stage 2). The layout picker draws its schemas by
**running the solver** at thumbnail parameters (§6.3): a new recipe in `recipes.json` appears with a
correct schema for free, and a thumbnail can never drift from the real layout.

**Slider bounds** are a bisection on `solve_strict` — a new mirrored primitive: one attempt, no
relaxation ladder. Bisecting on `solve` would have been quietly wrong, because the ladder answers
"roomy" for an over-constrained value by laying the block out with *other* gutters. The bisection
itself is client-only (`editor/core/bounds.ts`, like `snapping.ts`): the server needs no such rule,
its solver is total.

**Three rules the panel forced into the open**, now in §6.2 of the spec:
1. *Attaching a block must not eat a caption.* A hand-built artwork shows the picker alone; picking
   a layout attaches a block, which from then on owns the captions (§3.7) — so an existing caption's
   text moves into the block instead of being deleted on the next solve.
2. *Reframing turns the lock off.* Under `no_upscale` the constraint solver shrinks the **slot** as
   soon as the crop gets smaller than it (§7.3), which fights the cell. A reframe inside a cell now
   zooms with the lock off and restores §3.7's lock afterwards (`relock`), so the rect belongs to
   the composition at all times.
3. *Balance is clamped when the recipe changes.* The declared ranges differ between recipes
   (`hero-left` 0.40–0.75, `hero-right` 0.25–0.60), so carrying the value over unclamped builds a
   document the server rejects with `balance_out_of_range`. Found by reading the catalogue after
   the browser run had already set 0.7 on a hero-left; `balanceFor` clamps, and the browser now
   shows 0.75 → 60 % on the switch, stored without a 422.
4. *The photo count keeps the block valid.* A slot added or removed in the Advanced editor re-picks
   the recipe (§4.4); past the catalogue (7 photos and up) the block detaches, which is also what
   stops the server rejecting the save with `recipe_slot_count`.

**Verified in a real browser** (§13.6, headless Chromium over CDP against the production build on
trusted localhost — the harness the AGENTS.md gotcha describes):

- a 3-photo artwork created by `POST /artworks` with no layout id comes back parametric
  (`three-row`, `fill`);
- picking *Hero left* shows Balance at the recipe's 62 % default; switching the format to `3:2`
  replaces the slider with the "the format sets the proportions" hint (§4.3);
- dragging *Outer* to 320 shows `→ 373` next to it — and 373 px is exactly the margin the **server**
  stored after re-solving, which is the phase's AC: *the server-stored rects equal the ones the
  editor previewed*. The cells come out 3:2 to the rounding bound (2120×1414, 1000×667);
- a hand-built artwork shows "Pick a layout…" and attaches a block when one is picked, carrying its
  caption into it (`y = 2018`, the derived baseline);
- typing a caption switches it on *below*, dragging photo 1 onto photo 2 swaps them and re-frames
  both crops, zooming cell 2 to 3× changes only the crop (the rect stays the cell), and a 24 px
  border lands as a band on every slot.

**Verified**: `make check` green — 822 backend tests, 339 conformance cases, mypy strict, ESLint,
tsc, i18n.

**Not done** (stage 4): there is no `[Simple] [Advanced ᴮᴱᵀᴬ]` switch yet — the Simple panel sits on
top of the Advanced stack in the design tab, which is how it stays reachable for a hand-built
artwork. Free-form edits still do not set `detached`, so the gap flagged in the stage-2 note is
still open: a slot moved by hand on a composition-backed artwork is re-solved away on save. Stage 4
closes it, together with the banner and **Re-apply layout**.

## 2026-09-22 — Phase 7 stage 4 (the mode switch and `detached`) — **phase complete**

The editor now has two modes and a safe door between them.

**The switch** sits in the header (`[Simple] [Advanced ᴮᴱᵀᴬ]`, Simple default for every artwork,
registered as a palette command with no shortcut). Advanced shows the Phase 6 stack under the
warning strip. The canvas is shared but not identical: in Simple the stage runs the **crop**
gesture, so dragging reframes a photo inside its fixed cell and the transform handles are never
offered — the select/crop toggle is an Advanced control and is hidden in Simple.

**Detaching** (§5) is the interesting half. The rule the code applies is mechanical: **an edit
detaches exactly when `apply` would overwrite it**. That turned a vague list ("rotation, free
placement, per-slot decorations") into 20-odd call sites with an answer each:

- *detach*: move / resize / rotate a slot, align / distribute / same-size, fit / fill to photo,
  bands, quality lock, crop ratio, margins, placement, alternatives, a caption's position, adding
  or removing a caption;
- *do not detach*: the shadow, the mat, a caption's typography — `apply` leaves them alone, so they
  survive the next solve and must not cost the user their layout link;
- *re-solve instead*: orienting a photo (90°/flip changes the aspect an `original`/`auto` cell
  follows), re-ordering slots (the array order **is** the cell assignment, so it reads as a swap)
  and adding or removing a photo (§4.4).

A caption's text was the one field both modes write: typed on the canvas it now goes into
`composition.caption.text`, not just onto the caption, or the next solve would take it back.

**Re-apply layout** is one `store.edit()` patch behind a confirm dialog — which is exactly what
makes it safe to offer as a button: `⌘Z` puts the hand-made geometry back.

**Verified in a real browser** (CDP, production build on trusted localhost): Simple is the default
and shows the Layout panel; Advanced shows the beta strip and the old stack; an arrow-key nudge in
Advanced detaches; back in Simple the banner replaces the controls; Re-apply asks for confirmation
and restores the solved cells (`detached: false`, rects back to 120/2382 on the server); one `⌘Z`
brings the banner *and* the hand-made geometry back (`detached: true`, `x = 122` — the two nudges),
all of it round-tripping through the server. A shadow change in Advanced leaves `detached` false.

**A process note worth keeping**: the header switch silently did not land the first time — the
scripted replacement missed because prettier had reformatted the block, and that particular
substitution had no assertion. The browser run caught it immediately (the header had no switch at
all). Script every edit with an assertion, and never take "the checks are green" as evidence that a
UI change is actually *there*.

**Verified**: `make check` green — 822 backend tests, 339 conformance cases, mypy strict, ESLint,
tsc, i18n. Phase 7 is complete; `settings.artwork_defaults` still names a style + layout rather
than a style + recipe + format (§10, left to Phase 8 with the rest of the template work), and the
create dialog still sends a `layout_id`, so artworks made from the Photos page are hand-built until
the user picks a layout in the editor. Both are Phase 8's to change.

## 2026-09-22 — Phase 7 feedback round (`remarks.md`)

Seven items came back from using the Simple editor. One was a false alarm (the "asymmetric" bottom
margin was the caption band, which the user diagnosed themselves); the other six are treated.

**#7 — the zoom bug, and it was a real one.** `zoom_crop` grew the crop by the factor and then
clamped **width and height independently** against the photo. Scrolling out past the whole photo
therefore reshaped the crop — and since a crop whose aspect no longer matches its slot makes
`resize_crop` resize the *slot* to match, the cell visibly changed shape ("its frame is reduced or
extended"). Under `no_upscale` the slot followed the crop as well. The fix bounds the **factor** so
the crop stays inside the photo *with its aspect*, in both languages, with two conformance cases.
Verified in the browser: 40 wheel-outs now stop at exactly 1.00×, the rect unchanged and the crop
still at the cell's 0.7497.

**#3 — `4:3` and `3:4` rendered the same.** They did: `format_ratio` returned the *landscape form*
and the recipe's per-cell `landscape`/`portrait` annotation decided the orientation, which made
half the chips inert. A format now carries its orientation — the cells take the ratio as written —
and only `auto` (the 1-cell recipe) still turns it the photo's way. The panel gained a
**[Landscape] [Portrait]** toggle next to the chips. The recipes' cell kinds are inert as a result;
§10 notes they could be dropped.

**#4 — per-photo formats.** `composition.cell_formats` overrides the block's format cell by cell
(`null` inherits, `original` = that photo's own aspect, never `fill`). The solver already computed
a per-leaf aspect, so this was a parameter rather than a mechanism; the panel exposes it as a
"This photo" dropdown on the selected cell. A 1+2 with a `3:2` hero over two squares now works.

**#6 — creating from a multi-selection.** Selecting three photos created *three* artworks, because
the dialog defaulted to the one-slot "Single" layout and chunked the selection by slot count. It
now offers "One artwork with the 3 photos" (default) versus "One artwork per photo", and the
together path shows the recipe picker — so the dialog creates parametric artworks and the layout
dropdown is gone. Phase 8's "the create dialog still sends a layout_id" note is settled early.

**#2 — the zoom needed its tier.** The quality badge now sits under the zoom slider with a **Native
100%** button next to it. The first implementation drove the existing zoom action and landed a
pixel off — the badge read "Downscaled 100 %", which is exactly the lie the badge must never tell —
so the action sets the crop to the cell's size directly (`setNativeFraming`). It reads **Native
100%** and the stored crop equals the rect.

**#5 — swapping was undiscoverable.** Drag-onto-another was the only way and nothing said so. There
is now a hint line, a "cell 2 of 3" position row and **◀ ▶** buttons that swap with the neighbour.

**Verified**: `make check` green — 832 backend tests, 344 conformance cases. Everything above was
driven in a real browser (CDP): the create dialog from the Photos grid through to a stored 3-photo
parametric artwork, then the format orientation, a per-cell `1:1`, the swap arrows, Native 100% and
the wheel zoom-out, each checked against the **saved document** rather than the screen.

## 2026-09-23 — Phase 7 feedback, second round (`remarks.md`)

Ten items. Nine were actionable, one was a question answered in the reply (#7, below).

**#2 — the zoom bug was still there, and worse than it looked.** The previous round bounded
zooming *out*; nothing bounded zooming *in*. The wheel multiplied the crop by `1/1.06` without
limit, so a few seconds of scrolling shrank it to a handful of pixels, where two independently
rounded sides no longer describe the rect's aspect — and `resize_crop`'s answer to an inconsistent
crop is to resize the **slot**. Reproduced exactly: 120 wheel steps in took a 1800×1200 rect with a
3000×2000 crop to a 959×853 rect with an **8×8** crop, and zooming back out was stuck for ever
(`round_half_even(8 × 1.06) == 8`). Two fixes, both needed:

- `zoom_crop` (mirrored) now derives the height from the width and the **rect's** aspect, bounds
  the result by `largest_crop(source, that aspect)`, and always moves at least one pixel. The rect
  is the only reference that does not move: re-reading the aspect off the rounded crop every step
  drifts just as badly. Round trip now exact — all the way in to 1×1 and back out to the whole
  photo, with the rect untouched (four shapes checked, two conformance cases added).
- the editor routes the **wheel** through the same bounded 1×–8× scale as the slider
  (`zoomCrop` → `setPhotoZoom`), so scrolling cannot reach the pathological region at all.

**#1 — the upload overlay hijacked cell swaps.** Dragging a photo chip lit up "Drop photos or a
folder" across the window. A chip is an `<img>`, and Chrome offers such a drag to the page as a
file, so `hasFiles` was right about the `types` and wrong about the intent. Internal drags now
stamp themselves (`shared/dnd.ts`) and the global zone ignores a stamped drag — which also fixes
the same flash when dragging from the photo picker onto the canvas.

**#3 — clicking a photo on the canvas selects it.** In Simple the stage is always in crop mode, and
crop mode went straight to the gesture on the *primary* slot without hit-testing. It now selects
the photo under the pointer first, in both modes, so the canvas is a way to choose which photo the
panel edits and the chips are left to do the swapping.

**#4 — per-cell format, same control as the artwork's.** One `FormatChoice` component now serves
both, the per-cell one with an extra `Same as layout` chip: they are the same setting at two
scales, and chips-versus-dropdown made them read as unrelated.

**#5 — `original` at any photo count.** The document model rejected it above one slot. The rule was
conservative, not structural: `_leaf_aspect` has always given each leaf its own photo's aspect, and
a 3- and 4-cell solve lands each cell on its photo's ratio within the §3.4 tolerance. The rule is
gone (with the two client-side `original → fill` downgrades it forced), the chip is always offered.

**#6 — caption size is a slider in Simple.** No schema change: `apply` reads the typography back
off the document (§3.7), so the size round-trips on its own. It re-solves rather than detaches —
the band the solver reserves is a function of the size (§3.3).

**#8 — the frame style is changeable in the editor.** A dropdown in Background applies a style's
mat, shadow, border and caption typography, deliberately *not* its margins: under a block the
margins are derived, and the point is to re-dress the artwork without disturbing its layout. The
band becomes `composition.border` while a block is attached, since that is what owns `bands`.

**#9 — `P` toggles the TV preview** (it only ever opened it).

**#10 — a single photo hides what is about choosing a cell**: the layout picker (there is exactly
one 1-cell recipe), the gap sliders, the photo chips, the swap arrows and the per-cell format.

**#7 — the answer, no code.** A dropdown of "best quality" downscales (50 %, 25 %) is not worth
building: see the reply. The short version is that the renderer already resamples with a proper
filter, so there is no aliasing to dodge, and the tier the badge reports depends on the *cell* size
rather than on landing at a tidy fraction.

**Verified**: `make check` green — 834 backend tests, 346 conformance cases, mypy strict, ESLint,
tsc, i18n. Driven in a real browser (headless Chromium over CDP against the production build on
trusted localhost), each result read back from the **saved document** rather than off the screen:

- #2 — 200 wheel-ins then 300 wheel-outs on a 3-photo artwork: the crop stops at the 8× bound
  (384×510 of a 3071×4080 photo) and comes back to the whole photo, with the rect at 1427×1896
  before, during and after. The same sequence used to end at an 8×8 crop, a resized rect and no
  way back.
- #1 — a synthetic drag carrying a `File` raises the upload overlay; the same drag with our
  `text/x-the-frame-slot` stamp does not. Checked on both `/photos` and the editor route.
- #3 — clicking each of the three cells on the canvas moves the panel's "cell *n* of 3".
- #4/#5 — the format chips write `format: "3:2"` and `cell_formats: ["1:1"]`, and the solver
  answers with a 722×722 cell next to two 1083×722 ones; `original` on three photos gives each
  cell its own photo's aspect (1.327, 1.327, 0.752).
- #6 — the size slider takes the caption from 48 to 140 px and the margins re-solve around the
  bigger band (bottom 772 → 841).
- #8 — picking Linen writes its mat, a 12 px `#F6F2EA` border and an inner shadow.
- #9 — `P` opens the preview and closes it again.
- #10 — a one-photo artwork's panel has no Layout section, no Gap, no cell chips, no swap arrows
  and no per-cell format; a three-photo one has all of them.

Not driven: the native HTML drag that swaps two cells (a synthetic `dragstart`/`drop` pair does not
reproduce a real mouse drag — the previous round checked it, and this change only adds a `setData`
call to the existing handler).
