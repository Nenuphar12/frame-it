# ADR-0006 — HEIC not supported in v1

Status: accepted (2026-09-16, user decision)

## Context
The prebuilt libvips bundles libheif with the AV1 decoder only (AVIF works, HEVC does not). HEVC decoding would
require pillow-heif (bundled libde265) and carries patent caveats for redistribution.

## Decision
HEIC/HEIF files are detected by magic bytes and rejected with the problem code `unsupported_format_heic` and
guidance (configure the camera to save JPEG). The client also rejects `.heic/.heif` names before uploading.

## Consequences
Adding HEIC later = a decoder branch in `imaging/decode.py` (single seam) + this ADR superseded.
