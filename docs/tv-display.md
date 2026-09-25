# Display on the TV (Phase 12)

How a set of artworks gets onto a Samsung Frame and stays there. The measurements behind every
decision are in [`docs/research/tv-display.md`](research/tv-display.md); this document is what the
code does.

## 1. What the TV allows, and what follows

| The TV | Therefore the app |
|---|---|
| The art-mode slideshow plays **a whole category**. `content_list` is reported but ignored when sent, favourites refuse the API (`-7`), and no per-item request exists | **A push mirrors**: the TV's My Photos *is* the set. Anything else there has to go — and only ever with the user's explicit permission |
| Uploaded items are listed **newest first** | The set is uploaded **in reverse**, and each upload carries an `image_date` one minute apart, so the TV's order is our order |
| Intervals accepted: **3, 15, 60, 720, 1440 minutes** (everything else is `-7`) | `GET /display/capabilities` serves that list; the API refuses anything else with `invalid_interval` |
| `select_image` **stops** a running slideshow; starting a slideshow **never moves** the panel | A push is **stop → select the first image → start**. "Show this now" stops the rotation, and says so |
| Pairing happens on the **remote-control** channel, and the TV must be ON to draw its dialog | `POST /display/targets/{id}/pair` is a separate, deliberate step, and can be repeated whenever the TV forgets us (a power cut clears tokens) |
| The art channel cannot return a stored image (thumbnails are not answered on 2025 firmware either) | Whatever is deleted from a TV is gone. The app never deletes silently, and the UI says how many foreign items a push would remove |
| A 4K JPEG takes 4–6 s to upload | A push is a job in its own lane, never a request the browser waits on |

## 2. Model

- **`display_targets`** — one TV: address, pairing token (a credential: it stays in the data dir),
  the set it shows (`source`, an artwork query), interval, ordered/shuffle, render format, state.
- **`display_target_items`** — `(artwork_id, render_hash) → content_id`, plus the position in the
  set. This map is what makes a re-push upload nothing, what replaces exactly one image when one
  artwork changes, and what separates "ours" from "somebody else's" on the TV.

`source` is the same query shape the artwork grid uses (`filter`, `collection_id`,
`include_nested`, `favorite`, `status`, `sort`, or an explicit `artwork_ids` list), so a collection,
a smart collection, Favorites and an ad-hoc selection are one feature.

## 3. A push, step by step (`services/display.py`)

1. **Resolve** the set (max `MAX_SET` = 200; a Frame holds a few hundred images at most).
2. **Render** every member and read the `jpg` (default) or `png` derivative — before any connection
   is opened, because rendering is the slow part and needs no TV.
3. **Upload** what the TV does not already have, walking the set backwards so position 0 lands last
   and therefore leads. An artwork whose `render_hash` changed, or whose position moved, is
   re-uploaded; its old content id is deleted.
4. **Delete ours** that fell out of the set.
5. **Delete foreign items only with `allow_delete_foreign`.** Without it they stay, the result
   carries `foreign_remaining` and the warning `foreign_items_remain`, and the TV honestly shows
   more than the set.
6. **Stop the slideshow → select the set's first image → start the slideshow.**

Failures never retry silently: any `TvError` becomes a `PermanentJobError` whose code
(`tv_unreachable`, `tv_unauthorized`, `tv_rejected`) reaches `/activity`, where the job can be run
again once the TV is awake.

## 4. API

| Route | What it does |
|---|---|
| `GET /display/capabilities` | intervals the TV accepts, `max_set`, and the three things it cannot do (scoped slideshow, favourites, thumbnails) |
| `GET/POST /display/targets`, `PATCH`/`DELETE /display/targets/{id}` | the TVs and their settings |
| `POST /display/targets/{id}/pair` | get a token (the TV must be ON); repeatable — this is the re-pair button |
| `GET /display/targets/{id}/status` | what the TV reports now, plus `ours` / `foreign` counts |
| `PUT /display/targets/{id}/source` | the set this TV shows |
| `POST /display/targets/{id}/push` | queue a push (`allow_delete_foreign` is the confirmation) |

CLI, same service layer: `the_frame_v2 tv add|list|pair|status|push`, with
`--collection`, `--favorites`, `--every`, `--shuffle`, `--yes-delete-others`.

## 5. UI

- **TV** in the sidebar (`/display`): one card per TV — pair / **pair again** (a power cut clears
  the TV's tokens, so re-pairing is a first-class action, not a recovery procedure), *Check the
  TV* (a live probe: art mode, how many photos it holds, how many came from this app, whether the
  slideshow runs), the interval (only the five the firmware accepts) and ordered/shuffle, and
  *Send to the TV*.
- **Show on the TV** on a collection and on a grid selection. The dialog says what a push means in
  one sentence — the Frame plays everything in My Photos, so the set is all it can show — and
  offers, unticked, *also remove photos this app did not send*, with the reason it matters: the TV
  cannot give an image back.
- When a push would remove somebody else's photos, the Display page asks again, naming the count,
  with three ways out: cancel, keep them, remove them.
- A push is a job: the toast says it started, `display.pushed` refreshes the page, and a failure
  lands in `/activity` with its code (`tv_unreachable` and friends are translated).

## 6. Testing

`the_frame_v2.tv.FakeTv` implements the same `TvClient` protocol as the real client and encodes the
firmware's behaviour — newest-first listing, `select_image` stopping the slideshow, `-7` for an
interval outside the accepted list, and the fact that starting a slideshow does not move the panel.
`tests/api/test_display.py` drives the whole feature through it: push order, reverse upload order,
idempotence, one changed artwork replacing one image, foreign photos surviving a push, and an
unreachable TV failing with a code. A test puts the fake on the context (`ctx.tv_factory`).

## 7. Not done here

Nothing rotates on a schedule from this app (the TV does that), no brightness/colour-temperature or
art-mode toggling is written (read-only at most), and there is no "keep in sync" — a push is always
explicit, by decision (`docs/research/tv-display.md` §8c).
