# the_frame_v2

Prepare and curate pictures for a 4K art-mode TV (Samsung The Frame): send originals from your phone over
Wi-Fi, frame them pixel-perfectly, group them in collections. *(Placeholder name; work in progress.)*

## Status

Phases 0–4 of [the plan](docs/PLAN.md) are implemented: device pairing (QR), resumable full-quality uploads from
phone and desktop (and LocalSend), ingest (JPEG/PNG/AVIF, colour management, EXIF, offline place names), photo
library and inbox, artworks from photos with built-in frame styles and layouts, and the 4K renderer (PNG/JPEG
downloads). The interactive editor is next.

## Quick start

Requirements: Python 3.14 + [uv](https://docs.astral.sh/uv/), Node 22+ + pnpm.

```sh
make install
make serve          # builds the UI and serves everything on http://localhost:8765
```

On the computer running the server you are admin automatically. To add your phone: **Devices › Pair a device**
and scan the QR code (same Wi-Fi). To keep GPS location and file names, send from the
[LocalSend](https://localsend.org) app instead: the server appears as a nearby device (allow it once in the web
UI; open TCP/UDP port 53317 in the firewall, see [docs/localsend.md](docs/localsend.md)). From another computer, use the setup code printed at startup
(or `uv run the_frame_v2 setup-code`).

### Docker

```sh
docker compose -f docker/compose.yaml up -d   # edit THE_FRAME_V2_PUBLIC_URL first
```

LocalSend discovery needs host networking in Docker (see the comments in `docker/compose.yaml`).

## Development

```sh
make dev     # API on :8765 with reload + Vite on :5173
make check   # lint, type-check, i18n keys, tests
```

Contributors and coding agents: start with [AGENTS.md](AGENTS.md).

## Credits

Place names © [GeoNames](https://www.geonames.org/) (CC BY 4.0). Image processing by
[libvips](https://www.libvips.org/).
