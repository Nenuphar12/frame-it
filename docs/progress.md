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

**Known limits / follow-ups**: collections can only be listed (creation in Phase 8), so the phone collection
picker stays empty; "Create artworks" disabled until Phases 4–5; no ESLint rule for literal JSX strings yet.
