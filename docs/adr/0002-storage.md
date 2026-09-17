# ADR-0002 — Content-addressed originals, disposable cache

Status: accepted (2026-09-16)

## Decision
Originals are copied into `originals/<sha[0:2]>/<sha256>.<ext>` and never modified; identity = SHA-256 (dedupe
on upload and import). Everything derived (thumbnails, proxies, renders) lives in `cache/` and is regenerated
on demand, so `cache/` can always be deleted. Metadata lives in SQLite; all entity ids are UUIDv7.

## Consequences
Backups = `library.db` + `originals/`. Uploads are verified against the client-declared hash before ingest.
