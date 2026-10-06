# Frame It

Prepare and curate pictures for a 4K art-mode TV (Samsung The Frame): send originals from your
phone over Wi-Fi, frame them pixel-perfectly, group them in collections, export them as finished
3840×2160 images or send them straight to the TV.

Self-hosted, offline, one directory of files you own.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

![A three-photo composition on a linen mat, rendered at 3840x2160](docs/images/artwork.jpg)

<sup>What comes out: one 3840×2160 file. Demo photos from [Unsplash](https://unsplash.com) —
credits in [NOTICE.md](NOTICE.md).</sup>

## Written with AI

Nearly all of this project — the code, the tests and the documentation — was written by an AI
coding agent, [Claude Code](https://claude.com/claude-code), from my specifications. I decided
what to build, questioned the designs and tested the features in the running app. **I did not
review the code line by line.**

What I checked myself, on real hardware:

- uploads from an Android phone in full quality, through both of Android's pickers;
- the Docker image: build, run, and the library surviving a restart;
- my own TV, a 2025 Frame (`TQ55LS03FAUXXC`): pairing, uploading, selecting a picture, the
  slideshow.

What has not been tried on hardware yet is listed in [AGENTS.md](AGENTS.md) (*Purpose & status*).
What stands in for a line-by-line review is `make check`: about 1 100 backend tests, the geometry
rules written twice (Python and TypeScript) and compared on shared fixtures, and a few reference
images. That is evidence, not a guarantee: read the code before you rely on it for anything that
matters, and keep your own copy of your photos.

The git history does not mark which commits the agent wrote: assume all of them.

## What it does

- **Phone uploads in full quality** over the LAN — resumable, deduplicated, no cloud. Pair a device
  by scanning a QR code, or send from [LocalSend](https://localsend.org) to keep GPS and filenames
  that Android's picker would otherwise strip.
- **A framing editor that keeps the geometry honest.** Pick an arrangement, then drag the outer
  margin, the gaps, the format — or the divisions between the photos themselves, on the canvas:
  the layout re-solves so it stays even. A badge tells you at every
  moment whether a photo is **native**, **downscaled** or **upscaled**, and a per-photo lock stops
  the editor from ever stretching a picture behind your back.
- **A server-rendered loupe and TV preview**, so what you judge is the real output rather than the
  canvas's approximation.
- **Frame styles**: mats with a paper, linen or canvas weave, borders (flat, or bevelled like the
  cut edge of a real mat), recessed or raised shadows, a caption, and the soft shadow a frame
  casts on the picture.
- **Collections, smart collections, tags, favourites, search and a 30-day trash** where what was
  deleted together is restored together.
- **Export and import**: finished JPEGs/PNGs laid out by collection, or a `.tfarchive` backup that
  is a plain ZIP of JSON and your originals, with checksums. Importing shows a dry run first.
- **Show it on the TV**: find the Frame on your network, pair it once, and send a collection or a
  selection as an art-mode slideshow — or one artwork that stays on screen and leaves everything
  else on the TV untouched. Nothing the app did not send is ever deleted without your say-so
  ([`docs/tv-display.md`](docs/tv-display.md)).

## A look at it

![The editor: three photos on a linen mat, the Simple panel open on the right](docs/images/editor.png)

**The editor.** Everything in the right-hand panel re-solves the layout as you drag it — the
arrangement, the outer margin, the gap, the format, the mat, the border — and the gaps between the
photos are handles on the canvas. The badge under the zoom slider reads *Downscaled 73%*, and the
button beside it snaps the selected photo to *Native 100%*. The strip along the bottom is the
review queue.

|  |  |
|---|---|
| [![Artworks in a grid, each with its quality tier](docs/images/artworks.png)](docs/images/artworks.png) | [![A collection open beside the collection tree](docs/images/collections.png)](docs/images/collections.png) |
| **The library.** Every artwork carries its worst quality tier, so a soft one cannot hide in the grid. | **Collections** nest and keep a manual order; a smart one stores a filter instead of a list. |

![The inbox with the upload tray reporting 11 imported photos](docs/images/inbox.png)

**The inbox.** New photos arrive with their pixel size and any quality warning, and the tray says
what happened to each file — including the ones the library already had.

## Status

**Phases 0–12 of [the plan](docs/PLAN.md) are implemented** — foundations, device pairing, uploads,
ingest, the artwork document and renderer, the editor, parametric compositions, templates,
organization, export/import, the hardening pass and sending to the TV — plus a round of
improvements from daily use ([`docs/progress.md`](docs/progress.md) is the log). A few §16
questions are the remaining open items.

## Quick start

Requirements: Python 3.14 + [uv](https://docs.astral.sh/uv/), Node 22+ + pnpm.

```sh
make install
make serve          # builds the UI and serves everything on http://localhost:8765
```

On the computer running the server you are admin automatically. To add your phone: **Devices › Pair
a device**, then scan the QR code from the same Wi-Fi. From another computer, use the setup code
printed at startup (or `uv run frame-it setup-code`).

To keep it running across reboots:

```sh
uv run frame-it service install    # systemd user unit, or a launchd agent on macOS
```

### Docker

```sh
docker compose -f docker/compose.yaml up -d   # set FRAME_IT_PUBLIC_URL first
```

LocalSend discovery needs host networking in Docker (see the comments in `docker/compose.yaml`).

**Full instructions, including what the quality tiers mean and how to get pictures out:
[docs/user-guide.md](docs/user-guide.md).**

## How it is built

Python 3.14 · FastAPI · pyvips (Lanczos3, sRGB) · SQLite. React + TypeScript (strict) · Vite ·
TanStack Query/Router · react-konva.

The geometry is a **pure, mirrored core**: the same rules exist in `backend/…/domain/` and
`frontend/src/editor/core/`, and shared JSON fixtures fail the build if the two ever disagree. That
is what lets the editor draw exactly what the server will render.

Originals are content-addressed and never modified. The cache is always safe to delete.

## Development

```sh
make dev     # API on :8765 with reload + Vite on :5173
make check   # ruff, ESLint, mypy strict, tsc, i18n keys, geometry conformance, pytest
```

Contributors: [CONTRIBUTING.md](CONTRIBUTING.md). Coding agents: start with
[AGENTS.md](AGENTS.md) — it is the maintained entry point.

## Licence and credits

MIT — see [LICENSE](LICENSE).

Place names © [GeoNames](https://www.geonames.org/) (CC BY 4.0). Bundled fonts are SIL Open Font
License 1.1; mat textures are CC0. Image processing by [libvips](https://www.libvips.org/). Full
attribution in [NOTICE.md](NOTICE.md).
