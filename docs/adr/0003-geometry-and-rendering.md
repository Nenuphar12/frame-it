# ADR-0003 — Integer geometry, server-authoritative rendering

Status: accepted (2026-09-16) — implementation starts in Phase 4

## Decision
Artwork documents use integer pixel geometry (canvas and source space) except rotation. The browser renders
a live approximation from proxies; the server render (pyvips) is authoritative and used for the TV preview and
the 100 % loupe. Pure geometry code is mirrored in Python and TypeScript and checked with shared fixtures.

## Consequences
Pixel-perfect ("native") placement is exactly representable; client/server drift is limited to resampling,
blur and text metrics (measured by spike S3).
