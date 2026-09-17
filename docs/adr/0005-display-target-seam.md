# ADR-0005 — Display-target seam (future TV integration)

Status: accepted (2026-09-16)

## Decision
No TV-specific code or tables in v1. Renders are addressed by `(artwork_id, render_hash, format)` and
collections expose an ordered artwork list; a later "display target" module consumes only these.

## Consequences
The TV integration can be added without migrating existing data.
