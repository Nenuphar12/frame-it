# Display on the TV (Phase 12)

How a set of artworks gets onto a Samsung Frame and stays there. The measurements behind every
decision are in [`docs/research/tv-display.md`](research/tv-display.md); this document is what the
code does. Phase 12 shipped 2026-09-25; the follow-ups of 2026-10-01 (discovery, "Don't change",
the dry run, progress, following a TV that moved) are folded in.

## 1. What the TV allows, and what follows

| The TV | Therefore the app |
|---|---|
| The art-mode slideshow plays **a whole category**. `content_list` is reported but ignored when sent, favourites refuse the API (`-7`), and no per-item request exists | **A slideshow push mirrors**: the TV's My Photos *is* the set. Anything else there has to go — and only ever with the user's explicit permission |
| With the slideshow **off**, the TV shows whatever was selected last and nothing else | **"Don't change"** needs no mirror: upload what is missing, select the first image, delete nothing (§3) |
| Uploaded items are listed **newest first** | The set is uploaded **in reverse**, each upload dated after everything already there, so the TV's order is our order (§4.2) |
| Intervals accepted: **3, 15, 60, 720, 1440 minutes** (everything else is `-7`) | `GET /display/capabilities` serves that list; `0` means "Don't change"; the API refuses anything else with `invalid_interval` |
| `select_image` **stops** a running slideshow; starting a slideshow **never moves** the panel | A push is **stop → select the first image → start** ("Don't change" stops after the selection). "Show this now" stops the rotation, and says so |
| Pairing happens on the **remote-control** channel, and the TV must be ON to draw its dialog | `POST /display/targets/{id}/pair` is a separate, deliberate step, and can be repeated whenever the TV forgets us (a power cut clears tokens) |
| The art channel cannot return a stored image (thumbnails are not answered on 2025 firmware either) | Whatever is deleted from a TV is gone. The app never deletes silently, and says how many foreign items a push would remove *before* it runs (§5) |
| A 4K JPEG takes 4–6 s to upload | A push is a job in its own lane, never a request the browser waits on; its progress is published as it goes (§7) |
| The REST endpoint (`:8001/api/v2/`) answers without a token and carries the Wi-Fi MAC | Discovery sweeps the LAN for it, and a TV whose address changed is found again by MAC (§6) |

## 2. Model

- **`display_targets`** — one TV: address, `mac`, pairing token (a credential: it stays in the
  data dir), the set it shows (`source`, an artwork query), interval (`0` = "Don't change"),
  ordered/shuffle, render format, state. Since migration `0010` it also caches what the TV last
  said — `ours_count`, `foreign_count`, `checked_at` — so the UI can name the number of foreign
  photos without a probe that takes seconds; keeps `last_result` (the last push's outcome, shown
  after a reload) and `progress` (the running push); and an `image_clock` (§4.2).
- **`display_target_items`** — `(artwork_id, render_hash) → content_id`, plus `position` in the
  current set (**NULL** when the image is ours but no longer part of the set). This map is what makes
  a re-push upload nothing, what replaces exactly what one changed artwork requires, and what
  separates "ours" from "somebody else's" on the TV.

`source` is the same query shape the artwork grid uses (`filter`, `collection_id`,
`include_nested`, `favorite`, `status`, `sort`, or an explicit `artwork_ids` list), so a collection,
a smart collection, Favorites and an ad-hoc selection are one feature. `status: "ready"` leaves the
drafts out — of an explicit list too. A query matching more than `MAX_SET` (200) is refused
(`set_too_large`), never silently cut.

## 3. The two modes

| | **Slideshow** (`slideshow_minutes` ∈ 3/15/60/720/1440) | **"Don't change"** (`slideshow_minutes = 0`) |
|---|---|---|
| What the TV shows | every image in My Photos, rotating | the first artwork of the set, until something else is selected |
| Our earlier uploads outside the set | **removed** (they would be shown too) — unless `keep_ours`: then left alone and played along with the set | **left alone** — still ours in the map, `position = NULL` |
| Photos this app did not send | stay unless `allow_delete_foreign`; then deleted | **never deleted** (`allow_delete_foreign` is ignored) |
| Last calls | stop → select → start | stop → select |
| Default in the UI | collections and selections: the TV's setting | a single artwork |

"Don't change" leaves things behind on purpose: the user asked for one image on screen, not for the
TV to be tidied. Nothing it leaves is lost track of — the next slideshow push removes our leftovers
as usual.

## 4. A push, step by step (`services/display.py`)

1. **Resolve** the set (the source above).
2. **Render** every member and read the `jpg` (default) or `png` derivative — before any connection
   is opened, because rendering is the slow part and needs no TV.
3. **Plan** it: `plan_push(wanted, map rows, what the TV holds, static=…)` — pure, and the same
   function the dry run reports (§5). Rows whose `content_id` the TV no longer holds (deleted with
   the remote) are forgotten here.
4. **Upload** what the plan says, last position first. Each upload is written to the map **in its own
   transaction the moment the TV accepts it** (§4.1).
5. **Re-number**: positions follow the set; any row of ours not in it gets `position = NULL`.
6. Slideshow mode only: **delete ours** outside the set (not with `keep_ours`: they stay, counted
   in `left_ours`), then foreign items **only with
   `allow_delete_foreign`** (otherwise the result carries `foreign_remaining` and the warning
   `foreign_items_remain`, and the TV honestly shows more than the set).
7. **Stop the slideshow → select the first image → (slideshow mode) start it.**

Failures never retry silently: any `TvError` becomes a `PermanentJobError` whose code
(`tv_unreachable`, `tv_art_unavailable`, `tv_unauthorized`, `tv_rejected`) reaches `/activity`,
where the job can be run again once the TV is awake. `tv_art_unavailable` is a TV that **took the
connection but whose art app never said it was ready** — off, or out of art mode — as opposed to a
TV that is not on the network at all; it is not looked for by MAC, since it answered where it is. A failure before the TV is reached (`empty_set`, a render error) ends the
same way, and clears the stored progress.

### 4.1 The map rule

**A row lives exactly as long as its upload is on the TV** — whatever the current set is. It is
written the moment an upload succeeds, and removed only when the app deletes that item or finds the
TV no longer holds it. Two earlier bugs broke this: a reordered set deleted the old row when it
re-uploaded, and a failed push rolled back the rows of the uploads that *had* succeeded. Either way
the app's own images became "photos this app did not send" — counted, warned about, and offered for
irreversible deletion. `test_the_map_never_loses_an_upload_static_mirror_static` and
`test_an_interrupted_push_keeps_track_of_what_it_uploaded` pin it.

### 4.2 Order: what can be reused

The TV lists newest first, and a new upload is always newer than everything already there. So in
slideshow mode **only a tail of the set can be reused in place**: walking from the last position up,
an existing upload of the right render is kept while it is newer than the one kept after it; the
first position that cannot be served that way is uploaded again, **and so is every position before
it** — a re-uploaded middle image would otherwise jump ahead of its predecessors. Consequences:
re-pushing the same set uploads nothing; a changed *first* artwork costs one upload; a changed
middle artwork costs itself plus everything before it.

Dates: each upload carries an `image_date` of `base + (count − position)` minutes, where `base` is
the later of now and the target's `image_clock` (the latest date ever written to it), so two quick
pushes never interleave even if the TV sorts by date. In "Don't change" any upload of the right
render serves, whatever its position — nothing rotates, so order is moot.

## 5. The dry run (`POST /display/targets/{id}/plan`)

The same `plan_push`, nothing executed. Body: an optional `source` (default: the target's),
`slideshow_minutes` (default: the target's) and `check_tv` (ask the TV what it holds — a few
seconds; otherwise the map is believed). Answer: `set_count`, `to_upload`, `already_there`,
`ours_to_remove` (slideshow) / `ours_left` (static), `foreign` (live, else the cached count, else
null), `drafts` and `drafts_left_out`, and `tv_error` when the TV did not answer — the numbers then
come from the map, and the dialog says so. A live check refreshes the cached counts and forgets rows
the TV no longer holds.

The "Show on the TV" dialog asks twice: `check_tv: false` (instant) then `true`.

## 6. Discovery, and a TV that moved (`tv/discovery.py`)

`GET /display/discover` runs two searches together and lists every Samsung TV that answers, Frames
first, each matched to the target it already is (same MAC, else same address):

- **SSDP** `M-SEARCH` for `urn:samsung.com:device:RemoteControlReceiver:1` and the DIAL service —
  quick, but multicast does not leave a Docker bridge network;
- a **sweep of the /24** (`:8001/api/v2/`, 64 at a time, 0.8 s timeout) — what found the user's Frame
  in the S5 spike. The /24 is the **LAN's**: `tv_scan_subnet` if set, else the public URL's address,
  else this host's (inside Docker the latter is the bridge network's, hence the order).

The first Frame not added yet is `recommended`. Adding a scanned TV stores its `mac` and model; a
status probe fills the MAC in for a TV added by hand.

**Following a TV that moved.** When the TV does not answer (`tv_unreachable`) and its MAC is known,
`_with_tv` looks for that MAC on the LAN; found at another address, the target's `host` is updated
(committed at once — the address is right even if what follows fails) and the operation runs once
more. A push says so (`moved_from` / `moved_to`, warning `tv_moved`), so does a status probe and the
dry run. Without a MAC, or when the MAC is not found, the original error stands.

## 7. Progress and outcome

The push job reports `(phase, done, total)` — `queued` (at enqueue), `rendering`, `uploading`,
`removing`, `starting` — throttled to one event per 0.25 s (every phase's first and last always go
through). Each report updates `display_targets.progress` and publishes SSE `display.progress`
`{target_id, job_id, phase, done, total}`; the job's own progress bar follows the same spans
(render 0–40 %, upload 40–90 %, remove, start). The end publishes `display.pushed` with the result
(`mode`, `uploaded`, `reused`, `deleted_ours`, `deleted_foreign`, `foreign_remaining`,
`foreign_on_tv`, `left_ours`, `moved_*`, `warnings`), which is also stored as `last_result`.

## 8. API

| Route | What it does |
|---|---|
| `GET /display/capabilities` | intervals the TV accepts, `static_display`, `max_set`, and the three things it cannot do (scoped slideshow, favourites, thumbnails) |
| `GET /display/discover` | the TVs on the LAN (§6), `subnet` swept |
| `GET/POST /display/targets`, `PATCH`/`DELETE /display/targets/{id}` | the TVs and their settings (`POST` takes `mac`/`model` from discovery) |
| `POST /display/targets/{id}/pair` | get a token (the TV must be ON); repeatable — this is the re-pair button |
| `GET /display/targets/{id}/status` | what the TV reports now, plus `ours` / `foreign` counts; refreshes the cache; `moved_from` |
| `PUT /display/targets/{id}/source` | the set this TV shows |
| `POST /display/targets/{id}/plan` | the dry run (§5) |
| `POST /display/targets/{id}/push` | queue a push; `slideshow_minutes` / `slideshow_ordered` are saved first; `allow_delete_foreign` is the confirmation; `keep_ours` leaves our earlier uploads on the TV |

CLI, same service layer: `the_frame_v2 tv scan|add|list|pair|status|push`, with `--collection`,
`--favorites`, `--every` (`0` = "Don't change"), `--shuffle`, `--yes-delete-others`, `--keep-previous`.

## 9. UI (`frontend/src/features/display/`)

- **TV** in the sidebar (`/display`, `DisplayPage`): one card per TV — pair / **pair again**,
  *Check the TV* (a live probe), what it shows, how many images are ours (and how many of those
  are in the set), how many are not from this app (cached, with when), the last push's summary or
  the running push's progress, and the rotation (`SlideshowSettings`: the interval list with
  *Don't change*, *In order | Shuffle*). *Send to the TV* runs the dry run first, so the
  confirmation before removing somebody else's photos — naming the count, with cancel / keep them /
  remove them — no longer depends on the user having pressed *Check the TV*.
- **Add a TV** scans as it opens, pre-selects the recommended Frame, offers *Scan again*, marks TVs
  already added, and keeps a field for an address typed by hand.
- **Show on the TV** (`ShowOnTvDialog`) on a collection, a grid selection, the artwork viewer and the
  editor's command palette: the TV, a collapsed *On the TV* row ("Every 15 minutes · In order") that
  expands to the rotation, the dry run's numbers, *Leave out N drafts* when the set has drafts
  (ticked for a collection or filter, unticked for a hand-picked selection), and — slideshow mode
  only, each only when there is at least one — *Remove the N images sent before* (ticked; unticked
  sends `keep_ours`, and the warning says they will play along) and *Also remove the N photos this
  app did not send*. The dry run is not asked again when the first one changes: keeping them
  changes no upload, only which count they land in.
  A single artwork starts at "Don't change", whose note says nothing else on the TV is touched.
- **While a push runs**, `PushTray` (in the sidebar, every page) shows the phase and a bar, fed by
  `display.progress` through `pushStore` (outside React) and by `target.progress` after a reload.
  When it ends, a toast summarises it (`summary.ts`); a result the user should act on (foreign
  photos still playing, the TV moved) stays until dismissed. A failure is the activity centre's
  `job.failed` toast.

## 10. Testing, and driving it without a TV

`the_frame_v2.tv.FakeTv` implements the same `TvClient` protocol as the real client and encodes the
firmware's behaviour — newest-first listing, `select_image` stopping the slideshow, `-7` for an
interval outside the accepted list, and the fact that starting a slideshow does not move the panel.
`tests/api/test_display.py` drives the whole feature through it (order, idempotence, both modes,
the map rule across static → mirror → static, an interrupted push, follow-by-MAC, discovery, the dry
run, the cached counts, progress events); `tests/unit/test_display_plan.py` pins `plan_push` and
`tests/unit/test_tv_discovery.py` the parsing and the subnet rule. A test puts the fake on the
context (`ctx.tv_factory`, `ctx.tv_discovery`, `ctx.tv_pairer`).

**`THE_FRAME_V2_FAKE_TV=1`** (development only) does the same for a running server: every target
reaches one in-memory `FakeTv` holding three "foreign" photos, discovery finds it, pairing needs no
prompt, uploads take 0.8 s each so progress is visible — and nothing reaches a real TV. The fake
lives in memory: restart the server and it is empty again, while the map in the database is not.

## 11. Not done here

Nothing rotates on a schedule from this app (the TV does that), no brightness/colour-temperature or
art-mode toggling is written (read-only at most), and there is no "keep in sync" — a push is always
explicit, by decision (`docs/research/tv-display.md` §8c). Not yet verified on hardware: deleting
foreign photos, whether the token survives a power cut, discovery on the real LAN, following a TV
that moved, and a "Don't change" push.
