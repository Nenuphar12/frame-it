# Progress log

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

**Known limits / follow-ups**: collections can only be listed (creation in Phase 8), so the phone collection
picker stays empty; trashed artworks cannot be restored before Phase 8; no ESLint rule for literal JSX strings
yet; Docker image not rebuilt/tested with the fonts (Pango/fontconfig in the slim image); collage renders hold
all decoded originals in memory.
