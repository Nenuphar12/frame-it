# User guide

Everything you need to go from an empty library to a picture on the TV. If you are here to change
the code, read [`AGENTS.md`](../AGENTS.md) instead.

> This app prepares **files**. It does not talk to the TV: you put the finished 3840×2160 image on
> the TV the way you already do (the SmartThings app, a USB stick, or whatever your Frame accepts).

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
`uv run the_frame_v2 setup-code` prints a fresh one. Open `http://<server>:8765/setup` and type it
in. The code lasts an hour and works once.

### With Docker

```sh
docker compose -f docker/compose.yaml up -d
```

Set `THE_FRAME_V2_PUBLIC_URL` to the address your phone will use (for example
`http://192.168.1.179:8765`) **before** starting it: that URL is what the pairing QR code contains.
In Docker the connection comes from a bridge address, not loopback, so you always need the setup
code:

```sh
docker logs frame 2>&1 | grep "Setup code"
```

LocalSend discovery needs host networking — see the comments in `docker/compose.yaml`.

### Keeping it running

```sh
uv run the_frame_v2 service install     # writes a systemd user unit (Linux) or a launchd agent (macOS)
```

It prints the file it wrote and the one or two commands that start it — it does not start anything
itself. `service status` says what is installed, `service uninstall` removes the unit and leaves
your library alone. Add `--public-url http://192.168.1.179:8765` so the QR codes keep working after
a reboot.

On Windows there is no unit to generate: create a Task Scheduler task that runs
`the_frame_v2 serve` **At log on**, with "Run whether user is logged on or not" unticked, or use
[NSSM](https://nssm.cc/) to register it as a real service.

### Checking the machine

```sh
uv run the_frame_v2 doctor
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
decoding it is not in this version. Format is detected from the file's bytes, so renaming something
to `.jpg` will not sneak it past.

---

## 3. From photo to artwork

**Inbox** is where new photos land. Review them, tag them, and make artworks; `i` shows the
details of the selected photo.

Select one or more photos and press `n` (or *Create artworks*). With several photos selected the
dialog offers **one artwork holding all of them** — pick the arrangement from the schemas — or one
artwork per photo.

An **artwork** is one 3840×2160 picture: your photos, the mat around them, optional borders,
shadows and a caption. It is a recipe, not a file — nothing is flattened until you export.

---

## 4. The editor

Open an artwork with `e` or a double-click. Two panels:

- **Simple** is the one to use. You choose an arrangement, then drag sliders: the *outer* margin
  around everything, the *gap* between photos, the format (3:2, 4:3, square, the photo's own…),
  the border, the caption. The layout re-solves geometrically as you drag, so it stays even.
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
undoes. Everything autosaves.

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

- **Tags** are flat and shared by photos and artworks. The tag manager renames, recolours, merges
  and deletes them, with the counts of what each change will touch.
- **Collections** nest, and you order their contents by hand (drag a card, drag onto the tree).
- **Smart collections** store a filter instead of a list — their contents are whatever matches, so
  there is nothing to reorder and nothing to add by hand. An artwork leaves one by ceasing to match.
- **Favourites** is the heart: `f` anywhere.
- **Search** (`/`) covers titles, tags, place names and collection names.

### The trash

Deleting is reversible for 30 days. **What is deleted together is restored together**: one gesture
is one batch, and restoring the batch brings all of it back.

Trashing a photo that artworks use asks you to choose: trash those artworks too, or empty their
slots and keep them. Nothing is freed from disk until a purge — daily, or on demand from the trash
page. That is the only step that cannot be undone.

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
uv run the_frame_v2 export -o library.tfarchive
uv run the_frame_v2 export -o renders.zip --kind renders --format jpg
uv run the_frame_v2 import library.tfarchive --dry-run
```

---

## 8. When something goes wrong

**Activity** in the sidebar lists background work that failed — a render, an import, an export —
with what went wrong and a **Retry**. A failure also raises a message when it happens. A red count
on that row means something is waiting for you.

Other things worth knowing:

| Symptom | What it is |
|---|---|
| "This address is not allowed by the server configuration" | The `Host` header is not in the allow-list. Reach the server by its LAN IP, or set `THE_FRAME_V2_ALLOWED_HOSTS`. |
| The phone sees the pairing page but the QR goes nowhere | `public_url` is wrong — it must be the address the *phone* can reach, not `0.0.0.0` or `localhost`. |
| No place name on photos from an Android phone | Expected with the browser picker: Android removes GPS. Send with LocalSend instead. |
| "This artwork's photos are too large to render together" | Too many large originals in one artwork. The renderer holds them all at once; use fewer or smaller photos. |
| Thumbnails or renders look stale | `uv run the_frame_v2 cache clear` — the cache is always safe to delete, it regenerates on demand. |

### Where your library lives

One directory, printed by `the_frame_v2 doctor`. It holds `library.db` (SQLite), `originals/`
(content-addressed, **never modified**) and `cache/` (always safe to delete). Back up the first two;
ignore the third.

---

## 9. Configuration

Precedence: command-line flag → environment variable `THE_FRAME_V2_*` → `<data_dir>/config.toml` →
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
