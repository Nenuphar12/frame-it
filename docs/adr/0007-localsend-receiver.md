# ADR-0007 — Built-in LocalSend receiver

Status: accepted (2026-09-17, user decision)

## Context
Android removes GPS data from photos given to browsers and the photo picker renames files, so web uploads cannot
keep place and original name. The LocalSend app transfers files unchanged (verified on a Pixel 8 Pro).

## Decision
The server implements the receiving side of LocalSend protocol v2 on its own TLS port (53317), with multicast
discovery. New sender devices must be approved by an admin in the web UI (then remembered; can be blocked).
Received files go through the existing ingest pipeline. Browser uploads are kept.

## Consequences
- New dependency `cryptography` (certificate generation); a persistent certificate in the data dir.
- Sender identity relies on the announced fingerprint (not cryptographically verified, see docs/localsend.md).
- Docker needs host networking for automatic discovery.
- A future native companion app is not needed for full-fidelity transfers.
