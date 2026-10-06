# User guide

Everything you need to go from an empty library to a picture on the TV. If you are here to change
the code, read [`AGENTS.md`](../AGENTS.md) instead.

> This app prepares finished 3840×2160 images, and can put them on a Samsung Frame over the local
> network (§7, *Showing it on the TV*). Files still work the way you already use them: the
> SmartThings app, a USB stick, or whatever your Frame accepts.

---

## 1. Install and first run

### On a computer

Requirements: Python 3.14 with [uv](https://docs.astral.sh/uv/) and Node 22+ with pnpm.

```sh
make install
make serve            # builds the interface and serves everything on http://localhost:8765
```

Open <http://localhost:8765>. **On the machine running the server you are admin automatically** —
the app trusts loopback connections, so there is nothing to log into.

From *another* computer you need the **setup code**: it is printed in the server log at startup, and
`uv run frame-it setup-code` prints a fresh one. Open `http://<server>:8765/setup` and type it
in. The code lasts an hour and works once.

### With Docker

```sh
docker compose -f docker/compose.yaml up -d
```

Set `FRAME_IT_PUBLIC_URL` to the address your phone will use (for example
`http://192.168.1.179:8765`) **before** starting it: that URL is what the pairing QR code contains.
In Docker the connection comes from a bridge address, not loopback, so you always need the setup
code:

```sh
docker logs frame 2>&1 | grep "Setup code"
```

LocalSend discovery needs host networking — see the comments in `docker/compose.yaml`.

### Keeping it running

```sh
uv run frame-it service install     # writes a systemd user unit (Linux) or a launchd agent (macOS)
```

It prints the file it wrote and the one or two commands that start it — it does not start anything
itself. `service status` says what is installed, `service uninstall` removes the unit and leaves
your library alone. Add `--public-url http://192.168.1.179:8765` so the QR codes keep working after
a reboot.

On Windows there is no unit to generate: create a Task Scheduler task that runs
`frame-it serve` **At log on**, with "Run whether user is logged on or not" unticked, or use
[NSSM](https://nssm.cc/) to register it as a real service.

### Checking the machine

```sh
uv run frame-it doctor
```

It reports the data directory, the public URL, and what your libvips build can actually decode
(AVIF, colour management, Ultra HDR). A missing capability is listed under `missing_required`.

---

## 2. Adding your phone

**Devices › Pair a device** shows a QR code. Scan it with the phone, on the same Wi-Fi. The phone
gets its own paired identity with the role you chose:

| Role | Can |
|---|---|
| `uploader` | Send photos, browse the library read-only, set tags/collections/favourite while uploading |
| `admin` | Everything, including editing, deleting and exporting |

Pairing codes last five minutes and work once. A device can be renamed, have its role changed, or
be revoked immediately from the same page.

### Two ways to send photos

**The web page** (`/m` on the phone, or the QR link) uploads in full quality, resumes after a
dropped connection, and skips photos the library already has. It is the simplest route and it
always works.

**[LocalSend](https://localsend.org)** is the better route on Android, for one reason: the Android
photo picker **strips GPS from every file it hands to a browser** and renames the file to a
MediaStore number like `1000125423.jpg`. LocalSend sends the real file, so you keep the location
(and therefore the place name) and the original name. Open TCP and UDP port 53317 in the firewall;
the server then appears as a nearby device, and the first transfer from an unknown phone waits for
you to approve it in the web interface.

Sending a photo the library already has is not an error — it is put back in the inbox so you can
work with it again, and the tray tells you that is what happened. If a later copy carries GPS or a
real filename, that information is merged into the photo you already had.

### What can be sent

JPEG, PNG and AVIF. **HEIC is rejected** with a message telling you to set the camera to JPEG —
decoding it is not in this version (on an iPhone: *Settings › Camera › Formats › Most Compatible*;
HEIC support is on the roadmap). Format is detected from the file's bytes, so renaming something
to `.jpg` will not sneak it past.

---

## 3. From photo to artwork

**Inbox** is your to-do list: new photos land there and stay until an artwork using them is
**finished**. Review them, tag them (`t`), and make artworks; `i` shows the details of the selected
photo.

Select one or more photos and press `n` (or *Create artworks*). With several photos selected the
dialog offers **one artwork holding all of them** — pick the arrangement from the schemas — or one
artwork per photo.

An **artwork** is one 3840×2160 picture: your photos, the mat around them, optional borders,
shadows and a caption. It is a recipe, not a file — nothing is flattened until you export.

### Draft and Ready

A new artwork is a **draft**. While you work on it, its photos stay in the inbox, marked
**Draft** — click the badge to reopen the draft rather than starting another one. When you are
happy with it, mark it **Ready** (`Enter` in the editor's review queue or in the viewer): *ready*
means *done* — it is complete, and its photos leave the inbox. Going back to draft, or deleting
the artwork, does not put them back; *Back to inbox* on the Photos page does, whenever you want.

Two other ways off the list, kept apart on purpose: **Dismiss** (`d`) keeps the photo in your
library, just not on the to-do list; **Delete** sends it to the trash.

---

## 4. The editor

Open an artwork with `e` or a double-click. Two panels:

- **Simple** is the one to use. You choose an arrangement, then drag sliders: the *outer* margin
  around everything, the *gap* between photos, the format (3:2, 4:3, square, the photo's own…),
  the border, the caption. The layout re-solves geometrically as you drag, so it stays even.
  - In **Fill**, the gaps between photos are handles: drag one on the canvas to make a photo
    wider or taller. The photos sharing that row or column follow — a layout is rows and columns,
    so you are moving a division, not one photo. It snaps to halves, thirds and the golden
    section (hold `Alt` to stop it), and a double-click puts it back. For an exact figure, select
    a photo and use its **Width** and **Height**.
  - Each photo's chip has a `⋯`: **Replace photo…** opens the library on the photos taken the same
    days or at the same place — usually where the better frame is — and **Remove** takes it out;
    **Add photo** adds one, and the arrangement follows the count.
  - The **caption** has its font, weight, size, colour and spacing right there, and can sit
    centred or flush with the photos' left or right edge.
  - Every slider has a field next to it: type the value when dragging is not precise enough.
  - Selecting a photo no longer dims the others. Click the mat (or press `Escape`) to deselect.
  - The **border** can be *Flat* or a **Bevel** — the cut edge of a mat window, shaded as if lit
    from above (the top the darkest, both sides alike, the bottom barely), in any colour you like
    (*Use the mat's colour* gives the classic look) — and **Frame shadow** (in Background, folded:
    click the line to open it) adds the soft shadow a frame casts on the
    picture from the edge of the screen. Keep it light: the TV's own frame casts one too. The
    built-in **Bevelled mat** style combines both, close to the mat the TV draws itself.
- **Advanced ᴮᴱᵀᴬ** lets you place every photo by hand — free-form move, resize, rotate, overlap,
  align and distribute. Anything you do there **detaches** the artwork from its arrangement: the
  sliders stop driving it, because your placement is now the truth.

### Quality: the three tiers

The badge under the zoom slider is the most useful thing on screen.

| Tier | Means |
|---|---|
| **Native** | The photo is being used at exactly its own pixels. As good as it gets. |
| **Downscaled** | More photo pixels than the TV needs. Also excellent — this is the normal case for a modern camera. |
| **Upscaled** | Fewer photo pixels than the space they fill: the picture is being stretched and *will* look soft on a 55″ screen. |

Each photo also has a **lock** that decides what the editor is allowed to do:

- **No upscale** (the default) — the frame can never grow past the photo's real size.
- **Native** — the frame is pinned to the photo's exact pixels.
- **Free** — anything goes, including upscaling. Use it knowingly.

The **Native 100%** button next to the badge sets the crop to the cell's size exactly. A photo
smaller than its cell cannot reach it, and the button says so by being disabled.

### Useful keys

`?` shows the full list and closes it again. `Ctrl/Cmd+K` opens the command palette, which is the
fastest way to find anything. In the editor: `P` toggles the TV preview, `f` favourites, `Ctrl+Z`
undoes, `Escape` lets go of the selection and, pressed again, leaves. Everything autosaves.

The **TV preview** fills the screen with the artwork at the proportions the Frame will show, and
the **loupe** renders a small region on the *server* at full resolution — that is what the TV will
actually display, pixel for pixel, not the canvas's approximation.

---

## 5. Templates

A **frame style** is a look (mat colour or texture, border, shadow, caption typography). A
**layout** is an arrangement plus its margins — a recipe with its parameters filled in.

Both are **copied when you apply them**. Changing a template later does not disturb the artworks
that used it, unless you deliberately ask for a **push update** — which shows you what it would
change first and snapshots every artwork before touching it, so the snapshot is your undo.

*Save as template* in the editor turns the artwork you are looking at into one of either kind.
Templates travel as `.tfstyle.json` / `.tflayout.json` files.

---

## 6. Organising

- **Tags** are shared by photos and artworks, and an **artwork carries its photos' tags**: tag a
  photo "Alice" and every artwork made of it shows up under Alice — in filters, smart collections
  and search. Those inherited tags appear dashed on the artwork; change them on the photo. Tags
  that are about the artwork itself ("to print") are put on the artwork.
- **Tag many at once**: select photos or artworks and press `t`. Each tag says whether all, some
  or none of the selection has it; a click adds it to all (or removes it from all). After an
  upload, *Tag these N photos…* in the upload panel does the same for what just arrived.
- **Categories** group tags (People, Events, Themes, and your own); a tag with none is "Other".
  The Tags page renames, recolours, merges and deletes tags and categories, moves tags between
  categories, and clears out tags nothing uses. Its **Places** tab lists where your photos were
  taken (from their GPS position) and opens the artworks from each place.
- **Collections** nest, and you order their contents by hand (drag a card, drag onto the tree).
- **Smart collections** store a filter instead of a list — their contents are whatever matches, so
  there is nothing to reorder and nothing to add by hand. An artwork leaves one by ceasing to match.
  *New collection* (`Shift+N`) asks which kind first. The quickest way to make one is from a grid:
  filter Artworks the way you want, then **Save as smart collection** — the search box and the
  Favorites view are kept too.
- **By location**: in the filter bar, *Place* → *near*, type a place (accents don't matter; "Paris,
  Texas" picks among namesakes, and the places you have photos at come first) and pick a radius.
  It uses the photos' GPS position, so "within 50 km of Kyoto" includes Osaka. Photos sent through
  Android's photo picker have no position and are never found this way — the chip says how many
  artworks that leaves out; *contains* still matches place names. From a photo's details, *Artworks
  within 10 km* opens the same filter around it.
- **Favourites** is the heart: `f` anywhere.
- **Search** (`/`) covers titles, tags, place names and collection names.

### The trash

Deleting is reversible for 30 days. **What is deleted together is restored together**: one gesture
is one batch, and restoring the batch brings all of it back. So `Delete` does not ask first: it
moves the selection to the trash, and the message that appears offers **Undo**.

Trashing a photo that artworks use asks you to choose: trash those artworks too, or empty their
slots and keep them (`Enter` or `Delete` again confirms). Nothing is freed from disk until a
purge — daily, or on demand from the trash page. That is the only step that cannot be undone.

---

## 7. Getting pictures out

**Export & import** in the sidebar.

- **Rendered images** is what you want for the TV: a ZIP of finished JPEGs or PNGs, laid out by
  collection. PNG is the lossless master; JPEG is written at quality 95 with no chroma subsampling,
  which is visually lossless for this purpose.
- A **`.tfarchive`** is your backup: a plain ZIP anyone can open, holding the JSON records, the
  originals, and a `checksums.sha256` in the normal `sha256sum` format. Nothing proprietary.

Importing shows you a **dry run** first — what is new, what is identical, what conflicts — and you
choose what happens to conflicts, for the whole import, per kind, or item by item. Only then does
anything get written, and it is written in one transaction.

The same thing without a browser:

```sh
uv run frame-it export -o library.tfarchive
uv run frame-it export -o renders.zip --kind renders --format jpg
uv run frame-it import library.tfarchive --dry-run
```

### Showing it on the TV

**TV** in the sidebar. The details, and why the TV behaves as it does, are in
[`tv-display.md`](tv-display.md).

1. **Add a TV.** The dialog looks for TVs on your network as it opens and pre-selects the first
   Frame it has not seen before (*Recommended*). If yours is not listed, *Scan again*, or type its
   address (on the TV: Settings → Support → About this TV). In Docker, set `FRAME_IT_PUBLIC_URL`
   (or `FRAME_IT_TV_SCAN_SUBNET=192.168.1`) so the app looks on your network, not the
   container's.
2. **Pair it.** Turn the TV fully **on** (not art mode — it cannot draw its prompt there), press
   *Pair*, and accept "allow this device" on the TV. A power cut can make the TV forget the app:
   *Pair again* is the fix.
3. **Show on the TV** — from a collection, a selection of artworks, or one artwork in the viewer
   (or the editor's command palette). The dialog says, before anything happens, how many images
   will be sent, how many are already on the TV, and what else is there.

**Two ways to show.** *On the TV* in the dialog (and on the TV page) chooses:

- **A slideshow** — every 3 minutes, 15 minutes, 1 hour, 12 hours or 24 hours (the only intervals
  the Frame accepts), *In order* or *Shuffle*. The Frame's slideshow plays **everything** in its
  My Photos, so the app makes My Photos *be* your set: images it sent before that are not part
  of the set are removed. Photos the app did **not** send stay — and play between yours — unless
  you tick *Also remove the N photos this app did not send*. That box only appears when there are
  some, and the TV cannot give a deleted photo back, so keep a copy elsewhere first.
- **Don't change** — the first artwork goes on screen and stays there; nothing rotates and
  **nothing on the TV is deleted**, neither your earlier images nor anybody else's. It is what a
  single artwork starts with. The images it leaves behind are still known to be yours: the next
  slideshow push tidies them away.

**Drafts.** When a collection holds artworks not yet marked ready, *Leave out N drafts* is ticked:
only finished artworks go to the wall. Untick it to send them too (a hand-picked selection is
sent as picked).

**While it sends**, a line under the sidebar shows each step (preparing the images, sending them
— 4–6 seconds each on the TV — then putting the first one on screen), on whatever page you are.
A message then says what happened: how many were sent, how many were already there, how many were
removed, and whether photos the app did not send are still playing. The TV page keeps that summary
and how many foreign photos the TV last reported.

**Sending the same set again** uploads nothing; changing one artwork re-sends only what its new
position on the TV requires. If the router gives the TV a new address, the app finds it again by
its network identity on the next send or *Check the TV*, and says so.

The same from a terminal: `uv run frame-it tv scan`, `tv add <ip>`, `tv pair <id>`,
`tv status <id>`, and `tv push <id> --collection <id> --every 15` (`--every 0` is *Don't change*,
`--yes-delete-others` removes the photos the app did not send).

---

**Language.** The app speaks English and French. It follows the browser's language until you pick
one in **Settings → Language**, which that browser then remembers — so a phone set to French gets
the upload page in French with nothing to choose.

## 8. When something goes wrong

**Activity** in the sidebar lists background work that failed — a render, an import, an export —
with what went wrong and a **Retry**. A failure also raises a message when it happens. A red count
on that row means something is waiting for you.

Other things worth knowing:

| Symptom | What it is |
|---|---|
| "This address is not allowed by the server configuration" | The `Host` header is not in the allow-list. Reach the server by its LAN IP, or set `FRAME_IT_ALLOWED_HOSTS`. |
| The phone sees the pairing page but the QR goes nowhere | `public_url` is wrong — it must be the address the *phone* can reach, not `0.0.0.0` or `localhost`. |
| No place name on photos from an Android phone | Expected with the browser picker: Android removes GPS. Send with LocalSend instead. |
| "This artwork's photos are too large to render together" | Too many large originals in one artwork. The renderer holds them all at once; use fewer or smaller photos. |
| "The TV is on the network, but its art mode did not answer" | The TV is off or not showing art. Turn it on (or switch it to art mode) and press **Retry** in Activity. |
| Thumbnails or renders look stale | `uv run frame-it cache clear` — the cache is always safe to delete, it regenerates on demand. |

### Where your library lives

One directory, printed by `frame-it doctor`. It holds `library.db` (SQLite), `originals/`
(content-addressed, **never modified**) and `cache/` (always safe to delete). Back up the first two;
ignore the third.

By default that is the platform's data directory for `frame-it` (`~/.local/share/frame-it` on
Linux); `--data-dir` or `FRAME_IT_DATA_DIR` puts it elsewhere.

---

## 9. Configuration

Precedence: command-line flag → environment variable `FRAME_IT_*` → `<data_dir>/config.toml` →
default.

| Setting | Default | What it does |
|---|---|---|
| `data_dir` | platform data dir | Where the library lives |
| `host` / `port` | `0.0.0.0` / `8765` | Where the server listens |
| `public_url` | LAN IP guess | The address in the QR codes |
| `allowed_hosts` | LAN IP + hostname | Extra allowed `Host` values (`*` disables the check) |
| `trust_localhost` | `true` | Loopback connections are admin (off automatically behind a proxy) |
| `trash_retention_days` | `30` | How long the trash keeps things |
| `render_workers` | `1` | Renders at a time — **raise it only if you have RAM to spare** (a 9-photo collage of 24 MP sources peaks around 2.3 GB) |
| `ingest_workers` | `2` | Photos processed at a time |
| `localsend_enabled` | `true` | The built-in LocalSend receiver |
| `max_upload_bytes` | 1 GiB | Largest single file |

See [`docs/security.md`](security.md) for what protects the library on a shared network.
