# ADR-0001 — Stack: FastAPI + pyvips backend, React SPA frontend

Status: accepted (2026-09-16)

## Context
Local web server usable from a desktop browser and phones on the LAN, deployable in Docker. Heavy,
colour-managed image processing; a future Samsung Frame integration (Python ecosystem is the most mature).

## Decision
- Backend: Python 3.14, FastAPI, SQLAlchemy 2 (sync, threadpool) + Alembic, SQLite (WAL), pyvips with the
  prebuilt `pyvips-binary` wheels, Pillow only for EXIF/ICC parsing.
- Frontend: React 19 + TypeScript (strict) + Vite, TanStack Query/Router, Zustand, Tailwind v4 + Radix.
- API types are generated from FastAPI's OpenAPI schema (`make gen-api`).
- Single process; in-process persistent job queue (no Redis/Celery).

## Consequences
One deployable artefact (frontend built into the Python package). TypeScript pinned to 6.0 while
typescript-eslint does not support 7.x. HEIC is not decodable with the prebuilt libvips (see ADR-0006).
