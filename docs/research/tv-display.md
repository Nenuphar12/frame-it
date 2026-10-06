# S5 — Displaying a chosen set on the TV

Desk study, 2026-09-24; **revised 2026-09-25** with the actual TV model and the real set sizes.
No hardware driven yet, no code written. ADR-0005 (display-target seam) still holds: renders are
addressed by `(artwork_id, render_hash, format)` and a collection is an ordered artwork list — which
is all any option below consumes.

## 1. Givens (user, 2026-09-25)

| Given | Consequence |
|---|---|
| TV = **TQ55LS03FAUXXC** — 55" The Frame QLED **2025** (model group `25_PTM_FTV`) | The 2025 art-mode protocol generation (API 5.x) is the target; §2 is now mostly ✅ facts, not guesses |
| The TV must show the right set **with the computer off** | The TV's **own** slideshow must do the rotating; anything we drive per image is an extra, never the mechanism |
| Target is **art mode** (or a native equivalent) | Plain "My Photos" full-screen, matte `none`, filter `none`. The 2024+ "Auto Gallery / My Shelf / Board" modes re-layout and re-tint photos → they would destroy a pixel-perfect composition, and they are cloud-driven (not in the API) |
| A set is **5–20** artworks, never more than a few hundred | The TV's storage ceiling stops being a design driver; a **full mirror** of the set becomes the cheapest correct thing |
| Intended flow: ① wipe the TV, ② push the set in order, ③ art mode shows it (① ② automated) | Exactly option **O1** below. §4 lists the corrections that make it safe |

## 2. Does the local art API work on *this* TV? — evidence

The art channel is reverse-engineered (no Samsung documentation), so model-specific reports are the
only proof. The relevant ones, from the maintained art-mode fork
([NickWaterton/samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api), whose work is
merged into upstream [`samsungtvws`](https://pypi.org/project/samsungtvws/) 3.0.6, 2026-09-11):

| Evidence | What it tells us |
|---|---|
| **Issue #33** (2026-04-16): model `TQ50LS03FAUXXC`, model code `25_PTM_FTV`, `FrameTVSupport: true`, `TokenAuthSupport: true`, art websocket answers `get_artmode_status = on`, **uploads work** | ✅ **The same 2025 Frame family as yours (50" vs 55", same code) speaks the art API.** This is the single most important fact in this document |
| Same issue: REST `/api/v2/` reports `PowerState: "standby"` **while art mode is visibly on**; the fork's `in_artmode()` gates on power state and wrongly returns false | ⚠️ Never gate anything on REST power state — trust `get_artmode_status`. The **sync** client has no such gate; the **async** one does (dependency consequence, §6) |
| **PR #28** (2025-12-24): 2023+ models are art **API 5.x** and return `status` where 4.x returned `value` | Our client must tolerate both spellings; expect 5.x on a 2025 unit |
| **Issue #19** (2025-07, *"The Frame (non pro) 2025 — upload art"*): `send_image` refused (`error`, `-1`) on a 2025 unit. Reported fixes: use the **async** client; **chunked** upload (fork 3.0.5, Dec 2025); file-type quirks — one reporter got **only JPEG** through, the maintainer says **PNG works better** | ❓ **Upload is the one risky call on 2025 firmware**, and the working combination (client path × file type) must be settled on the unit. This is spike S5b, and it is the first thing to try |
| **Issue #15** + maintainer (2025-12): *"Samsung is now requiring a token for the art channel (which wasn't required before)"* — and the **"allow this device" dialog is raised by the remote-control channel, not the art channel**; opening `samsung.remote.control` on 8002 is what pairs. Confirmed here on 2026-09-25: probing the art channel on the user's TV produced no prompt at all | ⚠️ **Pairing is a separate first step**, and the TV must be fully ON — in art mode the panel is in standby and Samsung does not draw the dialog. `scripts/tv_probe.py` now pairs on the remote channel whenever the token file is missing; the `tv/` package must do the same |
| **Issue #16** + maintainer: **2022+ TVs keep the network up while "off"**; older ones drop it ~25–30 s after standby | ✅ We can push to the TV while the panel is showing art, and while it is "off" |
| **Issue #31** (open, 2026-02): `select_image(..., show=True)` pulled a TV **out of art mode** into its last input | ⚠️ Do not build the rotation on `select_image`. `select_image(..., show=False)` exists for "set it, don't force it" |
| **Issues #11 / #27**: the reference "sync a folder to the TV" scripts re-upload duplicates because they compare *images* to guess what is already there | We must key on our own map `(artwork_id, render_hash) → content_id`, never on image comparison |
| **Issue #17** + maintainer: the fancy 2024+ art modes are not in the API ("figured out by trial and error, there is no Samsung documentation") | Plain My-Photos slideshow is the only automatable native target — which is what we want anyway |
| Categories are **`MY-C0002` (my pictures)**, `MY-C0004` (favourites), `MY-C0008` (store) — `set_slideshow_status` / `set_auto_rotation_status` take exactly one `category_id` | ✅ **The TV has no album concept.** "Only this set" can only be expressed as *my pictures == the set*, *favourites == the set*, or *we pick each image ourselves*. That is the whole design space (§3) |
| Storage: Samsung support says ~2 GB for your own images; a community figure says **~75 images** on a 4 GB unit (3.5 GB taken by apps) | ❓ Unresolved by an order of magnitude. Irrelevant for a 5–20 set (≤ 65 MB as JPEG), **fatal for "keep the whole library on the TV"** (option O2) |
| Our renders (measured, `.dev-data`, 34 renders): JPEG q95 4:4:4 **mean 1.8 MB / max 3.2 MB**; PNG master **mean 7.7 MB / max 13 MB** | A 20-artwork set is ~36 MB as JPEG, ~155 MB as PNG. Both plausible; PNG is the lossless choice **if** this TV accepts PNG (see #19) |

Volatility, stated plainly: this API has broken and been restored across firmware generations (the
library still carries an `api_version == "0.97"` branch beside the modern D2D-socket path). Any
design must degrade to "the TV keeps showing what it already has", and USB must stay a viable path.

## 2b. Measured on the unit — `TQ55LS03FAUXXC`, 2026-09-25 (S5a ✅)

First real run of `scripts/tv_probe.py` against the TV (`192.168.1.71`), reports in
`.dev-data/tv-probe/`:

| What | Result |
|---|---|
| Discovery | `--scan` found it: `55" The Frame — TQ55LS03FAUXXC`, model code `25_PTM_FTV`, `FrameTVSupport=true`, `TokenAuthSupport=true`, wifiMac `04:CB:…` |
| Pairing | ✅ **only via the remote-control channel, TV fully on** — the art channel raises no dialog. Token saved; every later run is silent |
| `get_api_version` | **5.0.1.0** — the modern generation, as expected for a 2025 unit |
| `supported` | ✅ true (95 ms); art requests answer in ~1 s each |
| `get_artmode_status` | `off` while the TV was in normal mode (so this, not REST `PowerState`, is the signal to read) |
| `get_artmode_settings` | brightness 5 (min 0, max 10), colour temperature 0, and the motion settings — all readable, all able to change how our render looks |
| `get_content_list` | ✅ **64 items in `MY-C0002` (the user's own photos, already there) and 66 in `MY-C0008` (store)** |
| Item shape | `{content_id: "MY_F0095", category_id: "MY-C0002", content_type: "mobile", width: 3840, height: 2160, image_date: "2026:09:24 20:10:0", matte_id: "none", portrait_matte_id: "flexible_polar", slideshow: "false"}` — note the id spelling **`MY_F####`**, and that each item carries its own size, date and matte |
| `get_current_artwork` | ✅ `MY_F0095`, `content_type: "myphoto"` |
| `get_slideshow_status` | ✅ answers; empty `category_id`/`content_list` = no slideshow running |
| `get_auto_rotation_status` | ❌ **never answers** (the pre-2022 API; 5.x replaced it with `slideshow_status`). The probe now bounds every request and carries on |

### S5b — upload & selection, measured 2026-09-25 ✅

| Request | Result on `TQ55LS03FAUXXC`, API 5.0.1.0 |
|---|---|
| `send_image`, PNG 0.2 MB | ✅ **5 619 ms** → `MY_F0096` |
| `send_image`, JPEG 0.9 MB | ✅ **3 904 ms** → `MY_F0097` |
| Client | the **sync** client from PyPI `samsungtvws` — the fork's async path was never needed (§6 decision (a) stands) |
| Uploaded items | land in `MY-C0002` with `matte_id: "none"`, `portrait_matte_id: "none"` — our parameters stick (the TV's own items carry `flexible_polar`) |
| `select_image` | ✅ `is_shown: "Yes"`, and `get_artmode_status` still `on` 3 s later — **fork issue #31 does not affect this unit**, so "show this one now" is safe here |
| `get_current_artwork` | ✅ follows the selection (`content_type: "myphoto"`) |
| `get_matte_list` / `get_photo_filter_list` | ✅ mattes with colours; filters are `None, Aqua, ArtDeco, Ink, Wash, Pastel, Feuve` (note the capital `None`) |
| `get_artmode_settings` | brightness 5 (0–10), colour temperature 0 (−5…+5), motion sensitivity — all live and all able to change how a render looks |
| `get_device_info` | `resolution_type: UHD`, `server_sync_state: TRUE`, brightness-sensor and colour-tone support |
| `get_thumbnail` | ❌ **no reply in 25 s** — this firmware does not answer it |
| `get_auto_rotation_status` | ❌ no reply (pre-2022 API, replaced by `slideshow_status`) |

Consequences:

- **Upload is ~4–6 s per image**, dominated by TV-side processing, not bytes (the 0.2 MB PNG took
  *longer* than the 0.9 MB JPEG). A 20-artwork set is therefore ~2 minutes with the 2 s courtesy
  pause — fine for a background job, too slow for anything synchronous in the UI.
- **Both formats work**, so PNG (lossless) is available; the format choice is now about the panel's
  own re-encoding, not about acceptance.
- **No thumbnails from this TV.** The UI must show *our* renders as "what is on the TV", never
  fetched ones, and `--backup` on this unit yields the inventory only.

### S5c — first attempt, 2026-09-25: **two calls refuse with `-7`**

```
✓ upload order-1…5.jpg          send_image        3.5–5.5 s each   MY_F0098…MY_F0102
✗ favourite MY_F0098…0102       change_favorite   ResponseError: error number -7
✓ favourites now hold           MY-C0004          []
✗ slideshow 1 min, favourites   set_slideshow_status   error number -7
```

`-7` is the TV refusing a **value**, not the request: fork issue #20 has `set_artmode(True)` and
`set_artmode("true")` both returning -7 on a 2024 unit while `"on"` worked. So each call has to be
retried with other shapes before concluding anything — `--diagnose` does exactly that (six
favourite shapes, six slideshow duration/category combinations).

Two hypotheses, both testable in one minute:

1. **The duration.** We asked for 1 minute. The TV's own UI offers a fixed list (3, 5, 10, 30, 60…);
   `"1"` is probably not in it. And the slideshow was pointed at `MY-C0004`, which was **empty**
   because the favourite calls had just failed — pointing a slideshow at an empty category is a
   plausible -7 on its own.
2. **Favourites may not be settable over the API at all.** Weighing against O1-fav: the maintainer's
   own reference programs (`async_art_slideshow_anything.py`, `manual_slideshow.py`) **never call
   `set_slideshow_status`** — they keep a list themselves and drive `select_image` on a timer, and
   their docstrings say favourites are managed *"using the SmartThings app"*. That is what a library
   author writes after discovering the TV-side slideshow cannot be pointed at an arbitrary subset.

### S5c — the `--diagnose` matrix, 2026-09-25

| Attempt | Result |
|---|---|
| `change_favorite`, six shapes (`status` = on / true / True, with and without `category_id`, waiting and not waiting for `favorite_changed`) | ❌ **all six −7** → **favourites are not settable over the API on this firmware.** O1-fav is dead; the SmartThings app / remote owns favourites |
| `set_slideshow_status` 3 min, my pictures, shuffle | ✅ accepted — **and the TV started a slideshow** |
| the same call with 5 / 10 / 1 min, ordered, or favourites | ❌ −7, every one |
| `value: "off"` | ✅ accepted |

The failures are not about the durations: 10 min shuffle differs from the accepted call only in the
number. What changed between them is that **the slideshow was already running** — the accepted call
came from a stopped slideshow, `off` was accepted while running, and everything else was refused.
Working hypothesis: **this firmware will not reconfigure a running slideshow; it must be stopped
first.** `--diagnose` now sends `off` before every attempt.

### The lead: the TV keeps a `content_list`

The read-back of the *successful* call returned this (truncated in the terminal, full in the JSON
report):

```json
{"category_id": "MY-C0002", "value": "3", "type": "shuffleslideshow",
 "content_list": "[{\"content_id\":\"MY_F0102\",\"category_id\":\"MY-C0002\",
                   \"sub_category_id\":\"\",\"matte_id\":\"none\",
                   \"portrait_matte_id\":\"none\",\"width\":3840,\"height\":2160}, …]"}
```

**The TV's slideshow carries an explicit playlist**, not just a category. `get_slideshow_status`
reports it; the question is whether `set_slideshow_status` *accepts* one. If it does, that is a
fourth option, better than all three of §3:

**O4 — TV-side playlist.** Upload the set, then hand the TV a `content_list` of exactly those
content ids. Nothing is deleted, the user's 64 photos are untouched, no favourites are needed, and
the TV keeps rotating with the computer off. The only cost is the upload of the set itself.

`--diagnose` tries five shapes for the field (JSON string of `{content_id, category_id}`, a real
list, the full item shape the TV itself reports, comma-separated ids, a bare id list), and after
each one reads the status back and compares: a **★** line means the TV kept exactly our list.

### S5c round two, 2026-09-25 — `content_list` is **output-only**

| Attempt | Result |
|---|---|
| `set_slideshow_status` + `content_list`, five shapes (JSON string, real list, full item shape, comma-separated ids, bare id list) | ⚠️ **all five accepted without error — and all five ignored.** The read-back always came back with **71** entries, i.e. the whole of `MY-C0002`, never our 5 |
| Durations, each from a stopped slideshow | ✅ 3 min shuffle · ✅ 3 min ordered · ❌ 5 · ❌ 10 · ❌ 30 · ✅ 60 |
| The slideshow itself | ✅ runs, over the **whole category**, and survives the server (nothing else is needed to keep it going) |

So the TV *computes* `content_list` from the category and reports it; it does not take one. **O4 is
dead**, and with it the last non-destructive way found so far to scope a slideshow.

One genuinely useful by-product: the reported list comes back **newest first**
(`MY_F0102, MY_F0101, MY_F0100, MY_F0099 …` = reverse upload order). So an *ordered* slideshow
plays newest → oldest, which means our playlist order is obtainable by **uploading the set in
reverse** (or writing descending `image_date`s). §4.4's question is answered without needing the
TV to honour anything new.

The accepted-duration set {3, 60} with 5/10/30 refused is odd enough to re-measure
(`--diagnose-more` sweeps 2…1440), since 3-and-60-only would make "every 10 minutes" impossible.

### S5c round three, 2026-09-25 — **settled**

| Question | Answer |
|---|---|
| Which slideshow intervals does the TV accept? | **3, 15, 60, 720, 1440 minutes** — i.e. 3 min, 15 min, 1 h, 12 h, 24 h, exactly the TV's own UI list. Everything else (2, 5, 10, 20, 30, 45, 120, 180, 360) is −7 |
| Is there a hidden request that scopes without deleting? | **No.** All ten guessed names (`set_slideshow_content`, `change_slideshow`, `get_sub_category_list`, `get_album_list`, …) never answered. The per-item `slideshow: "false"` flag is reported, not settable |

So **scoping a Frame's slideshow to a subset is not possible over this API**. The slideshow plays a
whole category; the only category we can write is My Photos; therefore **"show only this set" means
My Photos *is* the set** — the destructive mirror — or the rotation is driven by the app.

**Decision (user, 2026-09-25): the mirror.** The originals of the 64 photos exist outside the TV
(phone, and to be recovered from SmartThings), so emptying My Photos is a cleanup, not a loss.

### The design, as measured

| Aspect | Settled answer |
|---|---|
| Scope | My Photos == the set; everything else there is deleted on push |
| Rotation | the TV's own slideshow, `MY-C0002`, **3 / 15 / 60 / 720 / 1440 min**, shuffle or ordered — runs with the computer off |
| Order | ordered plays **newest first**, so the app uploads the set **in reverse** (or writes descending `image_date`) |
| Cost of a switch | ~4–6 s per image (upload) + one delete call; a 20-artwork set ≈ 2 min |
| First frame | a push is *stop slideshow → select the first image → start slideshow*: setting a slideshow never moves the panel, and `select_image` stops a running one |
| Safety | the app must never delete silently: items it did not upload are counted and named, and removing them needs an explicit confirmation (`--yes-delete-others` in the spike; a typed confirmation in the UI) |
| Not available | favourites (−7), a scoped `content_list` (ignored), per-item slideshow flag (read-only), thumbnails (no reply) |

### What is left, and the one unexplored lead

Each item in `get_content_list` carries a per-item **`slideshow: "false"`** flag. If a request
exists that sets it, a set can be scoped **without deleting anyone's photos** — that is the last
non-destructive possibility, and `--diagnose-more` probes for it (ten guessed request names, short
timeout, an unknown name simply never answers).

If nothing answers, the choice is between two honest options, and it is the user's:

| | **Mirror (destructive)** | **App-driven rotation** |
|---|---|---|
| Mechanism | My Photos == the set: delete the 64 existing photos, upload the set, slideshow over `MY-C0002` | Slideshow off; the app calls `select_image` on its own timer |
| Set scoping | exact | exact |
| Order | newest-first ⇒ upload in reverse | exact, ours |
| With the computer off | ✅ the TV keeps rotating the set | ⚠️ the TV **freezes on the last image we selected** — art mode still shows an artwork of the set, it just stops changing |
| Cost | **the 64 photos are deleted and cannot be recovered from the TV** (thumbnails only) | nothing is deleted, nothing of the user's is touched |

### The decision tree this creates

| Outcome | Then |
|---|---|
| ~~a favourite shape works~~ | ❌ ruled out 2026-09-25 — every shape −7 |
| ~~`content_list` is accepted and honoured~~ | ❌ ruled out 2026-09-25 — accepted, then ignored (the TV reports its own list of 71) |
| **a request sets the per-item `slideshow` flag** | Non-destructive scoping — the best remaining outcome (`--diagnose-more`) |
| nothing scopes | Scoping needs My Photos to **be** the set → the destructive mirror: the user's 64 photos would have to go, and they cannot be recovered from the TV (thumbnails only) |
| nothing scopes, and the 64 must stay | **App-driven rotation** (`select_image` on our timer — already proved safe on this unit, art mode stayed on). Full control of set and order, but rotation stops when the computer is off |

The last row is the honest fallback, and it is exactly what the library's own examples do.

### The wrinkle S5b exposes

The TV already holds **64 of the user's own photos in `MY-C0002`**, and §2b's finding stands: the
art channel cannot give their originals back. But the TV's slideshow runs over a whole *category* —
so "My Photos == the set" (O1 as written) would mean **deleting those 64 photos**, irreversibly.

That makes a third arrangement the likely winner, available only because it was measured that
`set_favourite` exists and uploads land where we ask:

**O1-fav — upload the set, mark exactly it as favourite, slideshow over `MY-C0004`.** The user's 64
photos stay untouched in My Photos; "only this set" is expressed by the favourites category; a
switch is upload + favourite the new, unfavourite + delete the old. It keeps O1's ceiling-free cost
model *and* is non-destructive. The open question — does the favourites-category slideshow behave —
is now the single most important thing S5c must answer.

**The art channel cannot give the originals back**: `get_thumbnail` / `get_thumbnail_list` are the
only read paths for pixels, so what is uploaded to a Frame is only ever recoverable as a thumbnail.
`--backup` therefore writes an inventory (`inventory.json`, every field of every item, all
categories), one thumbnail per item, and an `index.md` table — a record of what the TV holds, not a
copy of it. Originals must be kept where they came from; for anything this app sends, the render is
reproducible from the artwork anyway (`render_hash`).

Two design consequences, both already in §4: the TV **already holds 64 of the user's own photos**,
so "only delete what we uploaded" is not a nicety but the difference between a sync and a data
loss; and `image_date` is per item and writable at upload, which is what the order test leans on.

## 3. The three options that actually differ

All three ride the local art channel (the alternatives to *that* — USB, SmartThings cloud, an HDMI
kiosk player, DLNA/AirPlay — are analysed in §8; none of them is both automatic and native art mode).

| | **O1 — Mirror** (your plan) | **O2 — Keep everything on the TV, switch with Favourites** | **O3 — We drive each image** |
|---|---|---|---|
| Mechanism | My Photos == the set; TV slideshow over `MY-C0002` | The whole library sits in My Photos; the active set is marked favourite; TV slideshow over `MY-C0004` | Slideshow off; our scheduler calls `select_image` every N minutes |
| Switching a set | upload the new (5–20 × ~2–5 s ❓) + delete the old ⇒ **~1–2 min** background job | a handful of `set_favourite` calls ⇒ **seconds** | same upload cost as O1 |
| Order | upload order / `image_date` ❓ (§4.4) | none (favourites slideshow shuffles) | **exact**, ours |
| With the computer off | ✅ TV keeps shuffling **exactly** the set | ✅ keeps shuffling the favourites | ❌ freezes on the last image we selected |
| Storage risk | none (one set at a time) | ⚠️ bets the whole library fits — and the ceiling may be ~75 images | none |
| Bug exposure | uploads only | uploads + favourites semantics ❓ | **issue #31** (TV leaves art mode) |
| TV-side tidiness | My Photos *is* the set — browsing with the remote shows the right thing | My Photos becomes a junk drawer of every artwork ever | same as O1 |
| Interference from the remote | the user can add store art (harmless) | the user can (un)favourite → silently changes the displayed set | — |

**Recommendation: O1-fav** (see §2b — the variant that leaves the user's own photos alone), i.e.
your plan with the set expressed as *favourites* rather than *all of My Photos*, and with the
corrections in §4. What follows about O1 applies unchanged to it: the only difference is which
category the slideshow is pointed at, and that a switch unfavourites instead of only deleting. It is the only one that is at
once immune to the storage unknown, immune to the `select_image` bug, correct with the server off,
and honest on the TV itself ("My Photos" is literally the set you chose).

**O2 is worth keeping in the back pocket, not building now.** It is strictly an optimisation of
switching time, it depends on two unknowns (capacity and favourite-slideshow behaviour), and it can
be added later *on top of* O1's item map without a migration — the map already knows what is on the
TV and what it costs to keep it there.

**O3 is not the mechanism but is a nice extra once O1 exists**: "show this artwork now" from the
grid or from `/m/browse`, and per-artwork dwell time while the server happens to be up. It must use
`show=False` semantics or be gated behind "the TV is in art mode", because of #31.

## 4. Corrections to the ①②③ flow

1. **Upload first, delete second** — the opposite of step ①-then-②. Emptying My Photos before the new
   set is there gives the TV a window with nothing of ours to show (it falls back to store art, and
   it may be showing an image we are about to delete). Order: upload the new members → point the TV
   at the first one → delete the members that fell out.
2. **Never re-upload what is already there.** Key everything on `(artwork_id, render_hash) →
   content_id`; a re-push of the same set is then a no-op, an edited artwork replaces exactly one
   image, and the job is resumable after a crash. This also avoids the duplicate-upload bug class of
   the reference scripts (#11/#27).
3. **Only delete content ids we uploaded.** Art the user added by hand (store items, USB imports) is
   listed and reported, never removed. Proposed invariant.
4. **Order on the TV**: upload in playlist order *and* set each item's `image_date` increasing, then
   `set_slideshow_status(duration_minutes, type=False /* ordered */, category_id="MY-C0002")`.
   Whether the ordered slideshow follows `image_date` or insertion order is ❓ — one test settles it
   (S5c). If it follows neither, ordered playback is only achievable while the server is up (O3), and
   the honest UI is then "shuffle when the server is off".
5. **Step ③ can be automated too**: `set_artmode(True)` (and `get_artmode_status` to verify). Keep a
   manual path — some units are reported to be fussy about art-mode transitions.
6. **Upload with `matte_id="none"`, `portrait_matte_id="none"`, and leave the photo filter at none.**
   A TV-side matte re-frames our render and a filter re-tints it; both would silently undo the whole
   point of this app. Worth a proposed invariant, and worth *reading back* `get_photo_filter_list` /
   the item's matte after upload in the spike.
7. **Select first, start the slideshow last — and never the other way round.** Two measurements,
   2026-09-25: setting a slideshow **does not move the panel** (it keeps showing whatever it showed,
   possibly an image the push just deleted, until a whole interval elapses — at 24 h that is a day
   of the wrong picture), and **`select_image` stops a running slideshow** (status came back
   `value: "off"` immediately after, and the TV then sat on that one image forever). So a push ends
   with: stop the slideshow → `select_image(<first of the set>, show=True)` → set the slideshow.
   The same measurement gives a product rule: **"show this one now" stops the rotation**, so that
   action must either say so in the UI or re-arm the slideshow behind it.
8. **Push while the panel shows art** (2022+ keeps the network up, #16). A genuinely hard-off TV ⇒
   job retries with backoff, then a failed job with a code in `/activity` (invariant 14) — never a
   silent failure. Wake-on-LAN by MAC is available as a last resort.

## 5. Minimal shape of the implementation (if accepted)

Small, because the sets are small — no windowed cache, no eviction policy, no rendering pipeline
changes:

- **`tv/`** package beside `localsend/`: `client.py` (the protocol, behind our own interface),
  `identity.py` (token storage), plus a `FakeTv` for tests. `services/display.py` = use cases,
  `api/display.py` = thin router. Domain stays pure and untouched.
- **Migration `0009`**: `display_targets` (name, host, mac, token, model, api_version, capabilities,
  source filter + sort, slideshow minutes, ordered/shuffle, render format, state, last_sync_at,
  last_error) and `display_target_items` (target_id, artwork_id, render_hash, content_id,
  uploaded_at, unique `(target_id, content_id)`).
- **One `display` job lane, one worker, coalesced per target** — `jobs/queue.py` already gives lanes,
  coalescing, retries and `schedule_every` (used by the trash purge) for the periodic re-resolve that
  smart sets need. Renders are produced by the existing render lane (`ensure_render`,
  `derivative(..., "jpg"|"png")`).
- **The set is a filter AST + a sort**, not a collection id (`domain/filters.py`), so a collection
  (ordered by `position`), a smart collection, Favorites and an ad-hoc selection are one feature.
- **UI**: a *Display* section in Settings (pair by IP, accept the on-screen prompt, show model/API
  version/what is on the TV now, interval, ordered vs shuffle) and one action — "Show this on the TV"
  — on a collection, on a grid selection and in `/m/browse`. Failures land in `/activity`.
- **CLI**: `frame-it tv pair | status | push <collection> | show <artwork> | clear`, same service
  layer, no browser (as `export`/`import` do).
- Tokens live in the DB in the data dir (a token is a credential for the TV), not in `config.toml`.

## 6. Which client code — three ways, one wrapper

| | **(a) PyPI `samsungtvws>=3.0.6`** (sync art) | **(b) fork 3.0.5 from git** (async art) | **(c) our own ~400–600 line client in `tv/`** |
|---|---|---|---|
| Pros | a normal pinned dependency; `pip-audit` and `uv export` keep working; sync fits our threaded jobs with no event loop; **no `in_artmode()` power-state trap** | the code path the 2025 uploaders were told to use; chunked upload; richer event handling | no LGPL dependency; every 2025 quirk handled where we can see it; a `FakeTv` makes API tests real; precedent: we already hand-wrote the LocalSend v2 receiver |
| Cons | upload is a single `sendall`, not chunked — the exact call that failed for 2025 reporters ❓ | git dependency (hurts the audit story), single maintainer, async in a sync codebase | we own the reverse engineering and every firmware break |
| Licence | LGPL-3.0 (→ `NOTICE.md`) | LGPL-3.0 | ours (MIT) |

Recommendation: **spike with (a)**, fall back to (b) if `upload` refuses on this unit, and put
whichever wins behind `tv/client.py` so (c) stays a later refactor rather than a rewrite. Either
library goes in `NOTICE.md`; LGPL-3.0 as an unmodified imported library is compatible with shipping
this app under MIT.

## 7. Spikes on the real TV, in order (each is minutes of work)

`scripts/tv_probe.py` runs them. It is read-only by default — every write needs its own flag, and
the only thing it ever deletes is what it uploaded in the same run. Each run prints a feature matrix
(request → worked? value? ms) and writes it to `.dev-data/tv-probe/<stamp>-report.{md,json}`.

```sh
cd backend
uv run python ../scripts/tv_probe.py --fake \
    --make-chart /tmp/chart.png --upload /tmp/chart.png   # no TV: see the output shape
uv run --with samsungtvws python ../scripts/tv_probe.py --scan    # find the TV (--subnet 192.168.1)

# S5a — probe & pair. The first run pairs on the remote-control channel: the TV must be
# fully ON (not art mode) to draw the "allow this device" dialog; accept it with the remote.
uv run --with samsungtvws python ../scripts/tv_probe.py --host <ip>
uv run --with samsungtvws python ../scripts/tv_probe.py --host <ip> --pair   # force a re-pair

# S5b — upload & fidelity: the chart, as PNG *and* JPEG, left on the TV to look at
uv run --with samsungtvws python ../scripts/tv_probe.py --host <ip> \
    --make-chart /tmp/chart.png --upload /tmp/chart.png --file-type both \
    --select-uploaded --keep-uploaded

# S5c — set semantics: 5 numbered images, increasing image_date, ordered slideshow every minute
uv run --with samsungtvws python ../scripts/tv_probe.py --host <ip> \
    --order-test 5 --slideshow 1 --ordered --keep-uploaded

# Rehearse the real thing: My Photos == this run's set (DRY RUN without --yes-delete-others)
uv run --with samsungtvws python ../scripts/tv_probe.py --host <ip> --quick \
    --order-test 5 --keep-uploaded --mirror --slideshow 3 --ordered

# Backup what the TV already holds, before anything else (inventory + one thumbnail per item)
uv run --with samsungtvws python ../scripts/tv_probe.py --host <ip> --backup

# cleanup (ids are in the reports)
uv run --with samsungtvws python ../scripts/tv_probe.py --host <ip> --delete MY_F1001 MY_F1002
```

If `send_image` is refused (the #19 risk), retry the same command with `--client async` under
`uv run --with 'samsungtvws @ git+https://github.com/NickWaterton/samsung-tv-ws-api'`.

The chart the script builds is the fidelity test: a 1 px checkerboard (smearing = re-encode), a grey
ramp (banding = re-encode/tone mapping), colour bars (shifted hue = filter or colour temperature), a
2 → 12 px line wedge (moiré = rescale), text at 10/14/20/28 pt, and a 1 px frame with corner ticks
(missing = crop/overscan). Photograph the panel, or just look at it from 30 cm.

| # | Question | Pass criterion |
|---|---|---|
| ~~S5a — probe & pair~~ | ✅ **done 2026-09-25** — §2b | paired, API 5.0.1.0, 15 reads answer |
| ~~S5b — upload & fidelity~~ | ✅ **done 2026-09-25** — §2b | PNG 5.6 s, JPEG 3.9 s, `select_image` safe, art mode stays on. *Panel fidelity judged by eye: "went well"; the chart is still on the TV as `MY_F0096`/`MY_F0097` if a closer look is wanted* |
| **S5a — probe & pair** | `rest_device_info()` → model, `FrameTVSupport`, `TokenAuthSupport`, `get_api_version()`; the on-screen allow prompt; token survives a reboot; `available()` lists the store items; `get_artmode_status` while the panel shows art | The channel answers and the token persists. Also records whether `PowerState` lies (expected: `standby`, #33) |
| **S5b — upload & fidelity** | Upload one render as **JPEG q95** and as **PNG**, `matte="none"`; does `send_image` succeed (the #19 risk)? time per upload; does the panel show it 1:1 (no crop, no matte, no re-encode softness, no filter)? | One format works ⇒ that becomes the per-target default. A photographed test chart matches the render (our `render_parity` habit) |
| **S5c — set semantics** | Push a 5-image set in order; `set_slideshow_status(type=False, MY-C0002)`; does the TV walk **our** order, and does `image_date` drive it? Does deleting our old items leave My Photos == the set? What does `MY-C0004` (favourites) slideshow do? | The TV shows only our set; the order behaviour is documented (and decides whether §4.4's fallback is needed) |
| **S5d — resilience & ceiling** | Computer off: does the slideshow keep going? TV off → on. Factory-reset/hand-deleted art: does a re-push reconcile from `available()` without duplicates? Keep uploading until the TV complains | The set survives the server; reconcile is clean; **the real storage ceiling is measured** (settles ~75 images vs ~2 GB, and thus whether O2 is ever possible) |

## 8. If the art channel turns out to be dead on this unit

In order: **USB export** (already implemented — `POST /exports` with `render_format=jpg` writes
`<Collection>/<Sub>/<title>.jpg`, which is exactly what Art Mode → My Photos → USB imports; art mode,
server-off, zero integration, manual) → a `/display` kiosk page on a small HDMI player (full control,
but normal panel mode, no art mode, needs the server up) → SmartThings by hand from the phone (cloud,
manual). Nothing in §5 is wasted by running S5a–S5b first, and S5a is a 10-minute test.

## 8b. The plan from here

Three spike questions still gate the build; each is one command and a look at the TV. Then four
build stages, each shippable on its own.

### Step 0 — tidy up (1 min)

The chart is on the TV twice. Either keep it for the fidelity look, or:
`--delete MY_F0096 MY_F0097`.

### Step 1 — S5c, the set question (~10 min, decides the design)

```sh
uv run --with samsungtvws python ../scripts/tv_probe.py --host 192.168.1.71 \
    --order-test 5 --favourite-uploaded --slideshow 1 --ordered --slideshow-category 4 \
    --keep-uploaded
```

Five numbered images, one minute apart in `image_date`, marked favourite, with the slideshow told to
run over **favourites**. Watch the TV for five minutes and answer:

1. Does the slideshow show **only** the five (favourites really do scope it)? → decides **O1-fav vs
   O1**: whether the user's 64 photos can stay.
2. Does it walk **1 → 2 → 3 → 4 → 5**? → decides whether a collection's manual order survives with
   the server off, or whether ordered playback needs the app running.
3. Does `1` reappear after `5` (it loops), and does the interval hold at 1 min?

Then the same with `--slideshow-category 2` for comparison, and `--delete` the five.

### Step 2 — S5d, resilience & ceiling (~1 h elapsed, mostly waiting)

Close the laptop (or stop the server) and confirm the slideshow keeps going; turn the TV off and on
and confirm it resumes; pull the TV's power for a minute and confirm the **token survives** (if not,
pairing needs a re-pair path in the UI). Optionally upload until the TV refuses, to find the real
storage ceiling (the ~75-images figure versus ~2 GB).

### Step 3 — build, four stages

| Stage | What | Acceptance |
|---|---|---|
| **12.1 Client & pairing** | `tv/` package (`client.py` wrapping `samsungtvws` sync, `FakeTv` for tests), `display_targets` table (migration `0009`), `services/display.py` pair/status, CLI `frame-it tv pair|status` | Pair from the CLI; status prints model, API version, art-mode state, item counts; API tests run against `FakeTv`; `make check` green |
| **12.2 Push a set** | `display_target_items` map `(artwork_id, render_hash) → content_id`; the diff (render → upload missing → favourite/slideshow → delete only ours); `display` job lane, coalesced per target; SSE `display.*`; `jobs.code` for `tv_unreachable`/`tv_unauthorized`/`tv_storage_full`; CLI `tv push <collection>` | Pushing a 10-artwork collection twice uploads 10 then 0; editing one artwork replaces exactly one image; the user's own TV art is never touched; failures land in `/activity` |
| **12.3 UI** | Settings → Display (pair, state, what is on the TV, interval, ordered/shuffle), "Show on the TV" on a collection / grid selection / `/m/browse`, an "on the TV" badge on artworks | The whole flow without a terminal; i18n keys; AA in both themes; `make gen-api` in the same change |
| **12.4 Polish** | "Show this now" (`select_image`), art-mode on/off, the TV's brightness/colour-temperature surfaced read-only or editable, `docs/user-guide.md` section, `docs/gotchas.md` entry | Documented, tested, and the AGENTS.md status line updated in the same commit |

Sequencing note: 12.1 and 12.2 are the whole value (a CLI that puts a collection on the TV); 12.3 is
convenience; 12.4 is finish. Nothing here needs the editor, the renderer or the archive to change.

## 8c. Decisions (user, 2026-09-25)

| Decision | Chosen | Consequence for the build |
|---|---|---|
| How "only this set" is expressed | **Favourites = the set** (O1-fav), to be confirmed by S5c | Nothing the app did not upload is ever deleted; the user's 64 photos stay. A target stores the favourite ids it owns, and a switch is: upload new → favourite new → unfavourite + delete the previous set |
| When the TV is updated | **Explicit push** | "Show this on the TV" on a collection or a selection, plus an *out of date* badge when the set or a `render_hash` moved since the last push. No background re-sync in 12.2; an opt-in "keep in sync" may come later |
| How much of art mode the app drives | **Images + slideshow only** | The app sets the slideshow category, interval and ordered/shuffle. It never writes brightness, colour temperature, motion settings, and never forces art mode on — they are read-only in the UI at most |

## 9. Still open

- **S5c**: does the favourites slideshow scope to favourites, and does it walk our order? (Step 1 of
  §8b — the last thing that can still change the design.)
- **S5d**: does the slideshow survive the server being off / the TV being power-cut, and does the
  token survive a power cut? Real storage ceiling.
- Dwell times the TV actually accepts for the slideshow (the UI offers a fixed list of minutes) ❓.
- `get_thumbnail` does not answer on this unit: the UI must render "what is on the TV" from our own
  renders. Whether `get_thumbnail_list` fares better is untested.
- One TV now, but the design is per-target, so a second one costs nothing.

## Appendix — art-channel surface we would use

`supported()` / `rest_device_info()` (capability probe) · `get_api_version()` · `available(category)`
(the diff) · `upload(bytes, file_type, matte="none", date=…) → content_id` · `delete_list(ids)` ·
`select_image(content_id, show=…)` · `set_favourite(content_id, on/off)` ·
`set_slideshow_status(minutes, ordered?, category_id)` / `set_auto_rotation_status(…)` ·
`set_artmode(True)` / `get_artmode_status` · `get_artmode_settings` (brightness, colour temperature,
motion sensor) · `get_matte_list` / `change_matte` and `get_photo_filter_list` / `set_photo_filter`
(only ever to assert "none") · `get_thumbnail` (to show in the UI what the TV believes it has).

---

Sources: [samsungtvws upstream (PyPI 3.0.6)](https://github.com/xchwarze/samsung-tv-ws-api) ·
[NickWaterton fork — art mode, issues #16/#17/#19/#28/#31/#33](https://github.com/NickWaterton/samsung-tv-ws-api/issues) ·
[NickWaterton/gallery](https://github.com/NickWaterton/gallery) ·
[Jon Sully — "The Samsung Frame: Best When Scripted"](https://jonsully.net/blog/samsung-frame-art-api) ·
[Samsung — using Art Mode](https://www.samsung.com/ch/support/tv-audio-video/art-mode-des-the-frame-tvs-verwenden) ·
[Samsung community — image quality recommendations](https://us.community.samsung.com/t5/QLED-and-The-Frame-TVs/Digital-image-quality-recommendations-for-quot-75-The-Frame/m-p/2715533) ·
[Samsung community — My Photos UI / capacity reports](https://us.community.samsung.com/t5/QLED-and-The-Frame-TVs/Horrible-UI-for-My-Photos/m-p/3623372)
