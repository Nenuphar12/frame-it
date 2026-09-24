# the_frame_v2 — Implementation Plan

> Status: **Phases 0–10 implemented** (see `docs/progress.md`) ·
> Created 2026-09-16 · Placeholder name `the_frame_v2` (rename before open-sourcing)
>
> This plan is the single source of truth for scope and sequencing. Specs (§5–§9, §12) live in dedicated
> files under `docs/` (linked in place). Agents: read `AGENTS.md` first (see §3).

---

## Table of contents

1. [Product summary](#1-product-summary)
2. [Glossary](#2-glossary)
3. [AGENTS.md — mandatory, always up to date](#3-agentsmd--mandatory-always-up-to-date)
4. [Architecture](#4-architecture)
5. [Data model](#5-data-model)
6. [Artwork document spec (v1)](#6-artwork-document-spec-v1)
7. [Geometry, quality & placement rules](#7-geometry-quality--placement-rules)
8. [Rendering spec](#8-rendering-spec)
9. [Security model](#9-security-model)
10. [API surface](#10-api-surface)
11. [Frontend architecture & UX](#11-frontend-architecture--ux)
12. [Archive (export/import) format](#12-archive-exportimport-format)
13. [Testing strategy](#13-testing-strategy)
14. [Phases & milestones](#14-phases--milestones)
15. [Cross-cutting conventions & Definition of Done](#15-cross-cutting-conventions--definition-of-done)
16. [Risks, open questions, out of scope](#16-risks-open-questions-out-of-scope)

---

## 1. Product summary

A self-hosted web application to prepare pictures for a Samsung The Frame TV (3840×2160, landscape),
with a desktop editor and a phone upload companion on the same LAN.

| Area | Decision |
|---|---|
| Shape | Local web server + web UI; same app runs in Docker (NAS) |
| Backend | Python 3.14, FastAPI, pyvips (Lanczos3, sRGB), SQLite (SQLAlchemy 2 + Alembic) |
| Frontend | React + TypeScript (strict) + Vite, TanStack Query/Router, react-konva editor |
| Storage | Managed data dir: content-addressed originals (never modified) + SQLite + disposable cache |
| Devices | One library; QR-paired devices with roles `uploader` / `admin`; localhost trusted; setup code for remote admin |
| Phone | Upload (resumable, dedupe, quality check) + tags/collections/favorite at upload + read-only browsing |
| Inputs | JPEG, PNG, AVIF (HEIC dropped for v1: rejected with guidance); ICC → sRGB; HDR gain-map photos use SDR base |
| Outputs | Lossless PNG master + JPEG (q≥95, 4:4:4) derivative |
| Quality | Tiers Native / Downscaled / Upscaled; per-slot lock Native / No upscale (default) / Free |
| Frames | Optional composable layers: mat (uniform or per side, color, texture) + bands + inner/drop shadow |
| Compositions | Free-form slots, smart guides, overlap/z-order, rotation, 90° orient/flip, captions |
| Templates | Frame styles and Layouts, independent; copy-on-apply with optional push-update |
| Organization | Nested collections (manual order, cover, description, dates, include-nested), smart collections, flat tags, EXIF, offline place names, favorites (heart), 30-day trash |
| Export/Import | Full archive, partial archive, rendered images, template files; dry-run import with conflict policies |
| UX | Sidebar + grid, focused editor, inbox review flow, undo/redo + autosave, keyboard-first + command palette, dark/light, TV-accurate fullscreen preview, i18n-ready (English) |
| Quality bar | Backend unit + API tests, very light golden-image tests, mypy strict, ruff |
| TV | Not in scope; architecture keeps a clean seam (ADR) |

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Photo** | An uploaded original, stored untouched, identified by SHA-256. Has tags + EXIF metadata. |
| **Artwork** | A non-destructive composition rendered at 3840×2160. Described by an **Artwork document** (JSON). Has tags, collections, favorite. |
| **Draft** | Artwork not yet validated. A photo only becomes displayable after explicit validation, even if already 3840×2160. |
| **Slot** | A rectangle on the canvas showing a crop of one photo. |
| **Mat** | Canvas background (color + optional texture). |
| **Margins** | Minimum mat widths (per side) used by `fit_in_mat` placement. |
| **Band** | Solid-color strip drawn directly around a slot's photo (outside the photo rect). |
| **Shadow** | `inner` (recessed look, drawn over photo+bands) or `drop` (raised look, drawn onto the mat). |
| **Scale** | TV pixels per source pixel for a slot (`slot.w / crop.w`). |
| **Quality tier** | `native` (scale 1, integer-aligned, no rotation) · `downscaled` (scale ≤ 1 otherwise) · `upscaled` (scale > 1). |
| **Quality lock** | Per-slot constraint: `native` · `no_upscale` (default) · `free`. |
| **Placement** | How a single-slot artwork is laid out: `fit_in_mat` (default) · `fill` · `manual`. |
| **Frame style** | Reusable template: mat, margins, slot decorations, caption defaults. |
| **Layout** | Reusable template: a recipe and its parameters (Phase 8, `docs/templates.md`). |
| **Recipe** | A named split tree (rows/columns of cells) that a solver turns into slot rects — the parametric replacement for a layout's absolute rects (Phase 7, `docs/simple-editor.md`). |
| **Composition** | The document block holding a recipe id plus its parameters (balance, outer margins, gutters, format, border, caption). Source of truth for the slots it derives. |
| **Inbox** | Photos uploaded but not yet processed into artworks (or dismissed). |
| **Proxy** | Downsized sRGB JPEG of a photo (long edge 2560) used by the editor preview. |
| **Render hash** | Hash of everything that influences a render; keys the render cache. |

---

## 3. AGENTS.md — mandatory, always up to date

`AGENTS.md` at the repository root is **created in Phase 1 (first task)** and **must be kept up to date
at all times**. It is the entry point for every coding agent (and human contributor). Its goal is to let an
agent produce relevant changes **without re-exploring the whole codebase**, saving time and tokens.

### 3.1 Rules

1. **Updated in the same change** as the code it describes. A PR/commit that changes commands, structure,
   invariants, conventions, or phase status without updating `AGENTS.md` is incomplete (part of the DoD, §15).
2. **Concise and high-signal**: target ≤ 300 lines. Link to `docs/*` for details instead of copying them.
3. **Accurate over complete**: remove stale statements immediately; never leave "TODO: update".
4. Agents **read it first** and trust it; they verify only the parts they modify. If they find it wrong, they fix it.
5. `CLAUDE.md` contains only `@AGENTS.md` (import) so Claude Code loads it automatically; other tools read `AGENTS.md` directly.
6. Nested `AGENTS.md` files (e.g. `backend/AGENTS.md`, `frontend/AGENTS.md`) are allowed when a sub-tree has
   enough specific guidance; the root file links them.

### 3.2 Required sections

| Section | Content |
|---|---|
| Purpose & status | 3 lines of purpose; **current phase**, what is done, what is next (link to plan section). |
| Quick commands | install, dev (both servers), test, lint, typecheck, regenerate API types, build, docker, conformance check. |
| Repo map | One line per important directory/module: responsibility. |
| Architecture essentials | Layers and dependency rules (e.g. `domain/` is pure, no IO). |
| Invariants | Must-never-break rules (see §4.4) — short list. |
| Glossary | Link to §2 (or its extracted doc) + any new term. |
| Conventions | Naming, errors, IDs, time, migrations, API-change workflow, i18n, commits. |
| Where specs live | Links: document spec, render spec, archive format, security, ADRs. |
| Gotchas | Discovered pitfalls (e.g. secure-context APIs unavailable over HTTP). Append as found. |

---

## 4. Architecture

### 4.1 Overview

```
 ┌────────────── Desktop browser (admin) ──────────────┐   ┌──── Phone browser (uploader) ────┐
 │ React SPA: library, editor (react-konva), templates │   │ /m/* mobile routes: upload,      │
 │ live preview from proxies + pure geometry (TS)      │   │ metadata at upload, read-only    │
 └───────────────▲─────────────────────────────────────┘   └───────────────▲──────────────────┘
                 │ REST /api/v1 (JSON) + SSE /api/v1/events                 │
 ┌───────────────┴──────────────────────────────────────────────────────────┴──────────────────┐
 │ FastAPI app (uvicorn)                                                                       │
 │  api/ (routers, thin) → services/ (use cases, transactions) → domain/ (pure logic)          │
 │                                   ↘ imaging/ (pyvips, Pillow)       ↘ db/ (SQLAlchemy)      │
 │  jobs/ : persistent in-process job queue (thread workers): ingest, render, purge, export…   │
 └───────────────┬───────────────────────────────┬─────────────────────────────────────────────┘
                 │                               │
          <data_dir>/library.db          <data_dir>/originals, cache/, uploads/, exports/
```

- Single process. SQLite in WAL mode. Jobs persisted in DB and resumed at startup.
- The frontend is built into static files and served by FastAPI (SPA fallback). In dev, Vite proxies `/api` to uvicorn.
- The **display-target seam** (future TV work): render service produces TV-ready files addressed by
  `(artwork_id, render_hash, format)`; collections expose an ordered list. No TV code (ADR-0005).

### 4.2 Repository layout

```
the_frame_v2/
├── AGENTS.md                 # §3 — always up to date
├── CLAUDE.md                 # "@AGENTS.md"
├── README.md
├── Makefile                  # dev, test, lint, typecheck, gen-api, build, docker, conformance
├── docs/
│   ├── PLAN.md               # this file
│   ├── architecture.md
│   ├── artwork-document.md   # §6
│   ├── geometry-and-quality.md # §7
│   ├── rendering-spec.md     # §8
│   ├── security.md           # §9
│   ├── archive-format.md     # §12
│   ├── research/             # spike findings (Phase 0)
│   ├── adr/                  # NNNN-title.md
│   └── schemas/              # JSON Schemas (artwork document, archive entities, template files)
├── backend/
│   ├── pyproject.toml, uv.lock
│   ├── src/the_frame_v2/
│   │   ├── __main__.py, cli.py (Typer), config.py (pydantic-settings), app.py (factory)
│   │   ├── api/              # routers only: auth, devices, uploads, photos, artworks, collections,
│   │   │                     #   tags, templates, render, exports, imports, trash, events, system
│   │   ├── auth/             # device tokens, localhost trust, host/origin checks, dependencies
│   │   ├── db/               # models.py, session.py, migrations/ (Alembic)
│   │   ├── domain/           # PURE: document.py, geometry.py, quality.py, placement.py,
│   │   │                     #   filters.py (smart-collection AST), templates.py, ordering.py
│   │   ├── imaging/          # decode.py, color.py, metadata.py, proxies.py, render.py,
│   │   │                     #   textures.py, text.py, palette.py, capabilities.py
│   │   ├── services/         # ingest, library, artworks, collections, tags, trash, templates,
│   │   │                     #   export, import_, geocode, devices
│   │   ├── jobs/             # queue.py, worker.py, handlers/
│   │   ├── events.py         # SSE broadcaster
│   │   └── assets/           # textures/, fonts/, icc/, geonames/, presets/
│   │   └── static/           # built frontend (generated, git-ignored)
│   └── tests/ unit/ api/ golden/ fixtures/
├── frontend/
│   ├── package.json, pnpm-lock.yaml, vite.config.ts, tsconfig.json
│   └── src/
│       ├── api/              # schema.d.ts (generated), client.ts (openapi-fetch), queries/
│       ├── app/              # router, providers, shell (sidebar), theme, shortcuts registry
│       ├── editor/
│       │   ├── core/         # PURE TS mirror of domain: geometry.ts, quality.ts, placement.ts,
│       │   │                 #   constraints.ts, snapping.ts, alternatives.ts, history.ts
│       │   ├── canvas/       # react-konva stage, slot nodes, mat/texture, shadows, guides
│       │   └── panels/       # slots, properties, colors, captions, loupe, alternatives
│       ├── features/         # inbox, library, photos, collections, tags, templates, trash,
│       │                     #   devices, settings, export-import, tv-preview, mobile
│       ├── i18n/             # i18next setup, locales/en/*.json
│       └── shared/           # UI kit (Radix + Tailwind), hooks, utils
├── conformance/geometry/     # shared JSON fixtures for Python/TS geometry parity (§13.3)
├── docker/ Dockerfile, compose.yaml
└── scripts/ gen_api_types, build_geonames.py, generate_textures.py, seed_library.py
```

### 4.3 Key libraries

**Backend**: fastapi, uvicorn[standard], pydantic v2, pydantic-settings, sqlalchemy 2 (sync, run in
threadpool), alembic, pyvips + pyvips-binary, pillow, typer, platformdirs, sse-starlette,
segno (QR for CLI/terminal only). Dev: pytest, pytest-cov, httpx, mypy (strict), ruff.

**Frontend**: react, react-dom, @tanstack/react-query, @tanstack/react-router, @tanstack/react-virtual,
zustand + immer (patches for undo), konva + react-konva, @radix-ui/*, tailwindcss, cmdk, tinykeys,
dnd-kit, react-colorful, qrcode, hash-wasm, i18next + react-i18next, openapi-typescript + openapi-fetch.
Lint: eslint (typescript-eslint, react-hooks), prettier.

Versions: latest stable at Phase 1, pinned by `uv.lock` / `pnpm-lock.yaml`.

**Verified facts (2026-09-16)**: the prebuilt libvips in `pyvips-binary` bundles libheif **with aom only**
(AVIF OK, **no HEVC → HEIC not decodable**), lcms (color management) and libultrahdr. ⇒ **HEIC is not
supported in v1** (decision 2026-09-16). HEIC uploads are detected by magic bytes and rejected with guidance
(e.g. set the camera to produce JPEG). Re-adding it later =
a pillow-heif decoder behind `imaging/decode.py` (ADR required: HEVC patent caveat).

### 4.4 Architectural invariants

1. Originals are **never modified**; stored at `originals/<sha[0:2]>/<sha>.<ext>`.
2. `cache/` is **always safe to delete**; everything in it is reproducible.
3. `domain/` (Python) and `editor/core/` (TS) are **pure** (no IO, no framework), mirror each other and are
   checked by the shared conformance fixtures.
4. **All geometry is integer** (canvas px and source px) except rotation angle (§7.1).
5. The server render is **authoritative**; the client preview is an approximation for interaction.
6. Templates are **copied on apply**; artworks never change because a template changed, unless the user pushes an update.
7. Routers contain no business logic; services own transactions; jobs call services.
8. API schema changes ⇒ regenerate frontend types in the same change.
9. Every user-facing string goes through i18n.
10. No browser API requiring a **secure context** in code paths used over plain HTTP
    (`crypto.subtle`, `crypto.randomUUID`, Service Worker, Clipboard write, Wake Lock) without a fallback.

### 4.5 Configuration

`pydantic-settings`, precedence: CLI flags > env (`THE_FRAME_V2_*`) > `<data_dir>/config.toml` > defaults.

| Key | Default | Notes |
|---|---|---|
| `data_dir` | platformdirs user data dir; `/data` in Docker | |
| `host` / `port` | `0.0.0.0` / `8765` | LAN reachable by default |
| `public_url` | auto (first private LAN IPv4) | Used in pairing QR; required in Docker (container can't see host IP) |
| `allowed_hosts` | localhost, 127.0.0.1, ::1, detected LAN IPs, hostname(.local) | DNS-rebinding protection |
| `trust_localhost` | `true` (auto `false` if `trusted_proxies` set) | |
| `trusted_proxies` | empty | |
| `tls_cert` / `tls_key` | unset | Optional HTTPS |
| `trash_retention_days` | 30 | |
| `max_upload_bytes` | 1 GiB | per file |
| `max_image_pixels` | 250 MP | decompression-bomb guard |
| `render_workers` | 1 | memory bound |
| `ingest_workers` | 2 | |
| `jpeg_quality` | 95 | 95–100 |

---

## 5. Data model

Moved to [`docs/data-model.md`](data-model.md) — maintained there.

---

## 6. Artwork document spec (v1)

Moved to [`docs/artwork-document.md`](artwork-document.md) — maintained there.

---

## 7. Geometry, quality & placement rules

Moved to [`docs/geometry-and-quality.md`](geometry-and-quality.md) — maintained there.

---

## 8. Rendering spec

Moved to [`docs/rendering-spec.md`](rendering-spec.md) — maintained there.

---

## 9. Security model

Moved to [`docs/security.md`](security.md) — maintained there.

---

## 10. API surface

REST under `/api/v1`, JSON, errors as RFC 9457 `application/problem+json` with stable `type` codes (translated in
the UI). Lists use keyset pagination (`?cursor=&limit=`). All payloads are Pydantic models → OpenAPI → TS.

| Group | Endpoints (main) | Role |
|---|---|---|
| system | `GET /system/info` (version, capabilities), `GET /system/me` | any |
| auth | `POST /auth/setup` (code), `POST /auth/pair` (code), `POST /auth/logout` | public/any |
| devices | `GET/PATCH/DELETE /devices/{id}`, `POST /devices/pairing-codes` | admin |
| uploads | `POST /uploads/check` (sha256[] → known/trashed/new), `POST /uploads` (create/resume session), `HEAD /uploads/{id}` (offset), `PATCH /uploads/{id}` (chunk, `Upload-Offset`), `DELETE /uploads/{id}` | uploader+ |
| photos | `GET /photos` (filters), `GET /photos/{id}`, `GET /photos/{id}/thumb/{size}`, `GET /photos/{id}/proxy`, `GET /photos/{id}/palette`, `PATCH /photos/{id}` (tags, inbox_state), `GET /photos/{id}/usage`, `POST /photos/import-local` (desktop folder import is client-side upload; this is for CLI) | read: uploader+, write: admin |
| inbox | `GET /inbox`, `POST /inbox/batch-create` ({photo_ids, style_id, layout_id, placement}), `POST /inbox/dismiss` | admin |
| artworks | `GET /artworks`, `POST /artworks` (from photos + style + layout *or* composition), `GET /artworks/{id}`, `PUT /artworks/{id}/document` (`If-Match: version`), `PATCH /artworks/{id}` (title, favorite, tags, status), `POST /artworks/{id}/validate`, `POST /artworks/{id}/duplicate`, `GET/POST /artworks/{id}/snapshots`, `POST /artworks/{id}/snapshots/{sid}/restore`, `GET /artworks/{id}/render.{png,jpg}`, `GET /artworks/{id}/thumb/{size}` | read: uploader+, write: admin |
| render | `POST /render/region` ({document, rect}) → PNG, `POST /render/alternatives-preview` | admin |
| collections | CRUD, `POST /collections/{id}/move` (parent, position), `GET /collections/{id}/items?include_nested=`, `POST /collections/{id}/items` (add), `POST /collections/{id}/items/reorder`, `DELETE /collections/{id}/items/{artwork_id}` | read: uploader+, write: admin |
| tags | `GET /tags?q=` (autocomplete), `POST /tags`, `PATCH /tags/{id}` (rename/color), `POST /tags/{id}/merge` | create: uploader+, else admin |
| templates | `GET/POST /frame-styles`, `PATCH/DELETE /frame-styles/{id}`, `POST /frame-styles/{id}/duplicate`, `POST /frame-styles/from-artwork`, `GET/POST /frame-styles/{id}/export`, `/frame-styles/import`, `GET /frame-styles/{id}/usage`, `POST /frame-styles/{id}/push-update/preview`, `POST /frame-styles/{id}/push-update` (same for `/layouts`); `POST /artworks/{id}/apply-template`; `GET /recipes`, `GET /fonts`, `GET /textures`, `GET /presets/colors` | admin |
| swatches | `GET/POST /swatches`, `PATCH/DELETE /swatches/{id}`, `POST /swatches/reorder` | admin |
| colours | `GET /photos/{id}/palette` (OKLab k-means, cached), `GET /presets/colors` | admin |
| defaults | `GET/PUT /artwork-defaults` ({style_id, recipe_id, format}) | admin |
| trash | `GET /trash`, `POST /trash/restore`, `POST /trash/purge`, `DELETE` flows use `?cascade=trash_artworks|empty_slots` | admin |
| exports | `POST /exports` ({kind: library/renders, selection, options}) → job; `GET /exports`, `GET /exports/{job_id}`, `GET /exports/{job_id}/download` (streaming), `DELETE /exports/{job_id}` | admin |
| imports | `POST /imports` then `PATCH /imports/{id}` (chunks, `Upload-Offset`) → staging job; `GET /imports`, `GET /imports/{id}`, `GET /imports/{id}/report`; `POST /imports/{id}/apply` ({default, per_kind, per_item}); `DELETE /imports/{id}` | admin |
| events | `GET /events` (SSE): `photo.ingested`, `photo.ingest_failed`, `upload.completed`, `artwork.rendered`, `job.progress`, `job.failed`, `entity.changed`, `export.ready`, `import.staged`, `import.failed`, `import.applied` | uploader+ (filtered) |
| jobs | `GET /jobs?state=`, `POST /jobs/{id}/retry` | admin |

CLI (`the_frame_v2`): `serve`, `doctor`, `setup-code`, `openapi`, `schemas`, `export`, `import`, `service install|uninstall|status`
(systemd user unit / launchd agent; Windows: documented manual steps), `db upgrade`, `cache clear`.

---

## 11. Frontend architecture & UX

### 11.1 State & data

- Server state: TanStack Query; SSE events invalidate/patch query caches (`entity.changed` → keys).
- Editor state: Zustand store holding the working document; every edit is an Immer produce with patches →
  undo/redo stack (inverse patches), grouped per gesture (drag = 1 step). Max 200 steps.
- Autosave: debounce 800 ms after last change → `PUT document` with `If-Match`; 409 ⇒ reload dialog (keep mine / take server).
  On editor open: `POST snapshots {reason: opened}` ⇒ "Revert to when opened".
- Routing: TanStack Router, typed search params for filters (shareable URLs).

### 11.2 Desktop screens

| Screen | Content |
|---|---|
| Shell | Left sidebar: Inbox (count), Artworks, Photos, Favorites, Collections tree (drag to nest/reorder, drop artworks), Templates, Trash, Devices, Settings. Top: filter/search bar (chips from filter AST), view options (size, sort). |
| Inbox | Grid of new photos with EXIF/place, quality warnings; multi-select; actions: Open (single editor), Batch create (style + layout picker with live mini-preview), Dismiss. |
| Review flow | Editor in "queue mode": filmstrip of queued items, `Enter` = validate & next, `S` = skip, `J/K` prev/next, progress "12 / 40". |
| Artworks / Favorites / Collection | Virtualized grid of render thumbs with badges (tier, favorite, draft, incomplete, outdated template); bulk actions (tag, add to collection, favorite, delete, export). Collection header: cover, description, dates, include-nested toggle, manual reorder mode. |
| Photos | Virtualized grid; detail drawer (EXIF, map-less place, usage list, tags). |
| Editor (Simple, default) | Canvas center, right: one column — layout picker (schemas), Balance, format chips, Outer/Gap sliders, photos (swap, reframe, zoom), background & border, caption. Top: mode switch + quality summary + undo/redo + TV preview + loupe. `docs/simple-editor.md`. |
| Editor (Advanced ᴮᴱᵀᴬ) | Same page behind the mode switch, with a warning strip: left slots list (z-order drag, add slot, photo picker), right properties (placement, margins, lock, crop ratio, orient, rotation, bands, shadow, mat color/texture, captions), bottom filmstrip. Free-form edits detach the artwork from its layout. Alternatives panel pops when a slot becomes upscaled. |
| Templates | Tabs Frame styles / Layouts; cards with a preview the page draws itself (the solver for a layout, a sample mat for a style); edit, duplicate, delete, export/import JSON; push update with per-artwork badges and skip reasons. `docs/templates.md`. |
| Trash | Items with days remaining; restore (with batch), delete permanently, empty. |
| Devices | Pair device (role, QR + URL), list, rename, role, revoke. |
| Settings | Theme, language, default style/layout, JPEG quality, trash retention, public URL, about (licenses, GeoNames attribution). |
| Export / Import | Wizards: kind → selection → options → progress → download. Import: upload → report (new / identical / conflicting per kind) → policies (bulk + per item) → apply. |
| TV preview | Fullscreen API; server render scaled to fit monitor with simulated bezel (color option) and optional matte overlay; `←/→` navigate within current list, `Esc` exit. |

### 11.3 Color tools

Free picker (react-colorful, hex/HSL input), saved swatches, **photo palette** (server: k-means on 64×64 in OKLab
→ dominant, muted variants, complementary; cached), curated presets (museum white, warm off-white, linen, stone,
charcoal, black), textures list with strength slider.

### 11.4 Loupe (100%)

Hold `Z` (or toggle): server `POST /render/region` for a 512×512 TV-pixel region under the cursor (debounced 150 ms,
using the current unsaved document). Displayed with `image-rendering: pixelated` at `512 / devicePixelRatio`
CSS px so that **1 TV pixel = 1 device pixel**.

### 11.5 Keyboard & command palette

Central registry (tinykeys) with scopes (global, grid, editor). `Ctrl/Cmd+K` palette (cmdk) lists every command
with its shortcut. `?` shows the cheat sheet. Examples: `F` favorite, `T` tag, `C` add to collection, `Del` trash,
`Ctrl+Z / Ctrl+Shift+Z`, arrows nudge 1 px (`Shift` 10 px), `[`/`]` z-order, `R` rotate source 90°,
`H` flip, `1/2/3` lock native/no-upscale/free, `P` TV preview, `Enter` validate.

### 11.6 Mobile (`/m/*`)

- **Upload**: pick photos (input `multiple`, attributes decided by spike S2) → per-file SHA-256 with hash-wasm
  (works over HTTP) → `uploads/check` → skip known → optional metadata sheet (tags autocomplete + create,
  collections picker, favorite) → queue with 2 parallel uploads, 8 MiB chunks, per-file progress/retry.
  Resume after interruption: re-picking the same files resumes by `(device, sha256, size)`.
  Advice banner: keep the screen on (Wake Lock unavailable over HTTP).
- **Quality warnings** after ingest: e.g. "This photo seems converted by your phone (no camera EXIF / reduced size) —
  here's how to send originals" (heuristics from S2).
- **Browse**: read-only artworks grid, collections, favorites, artwork fullscreen view.

### 11.7 Theming & i18n

Tailwind with CSS variables; dark (default, neutral gray for photo judgment) + light; `prefers-color-scheme` initial.
i18next with namespaces per feature; English only in v1; a script checks for missing keys; no hardcoded strings
(ESLint rule `i18next/no-literal-string` on JSX).

---

## 12. Archive (export/import) format

Moved to [`docs/archive-format.md`](archive-format.md) — maintained there.

---

## 13. Testing strategy

Scope decided with the user: **backend unit + API tests** and **very light golden-image tests**. No frontend test
suite, no CI in v1 (local `make check`).

### 13.1 Backend unit tests (`tests/unit`)

- `domain/`: geometry, tiers, locks, placement (incl. native linking), snapping candidates, alternatives,
  filter AST validation, document validation + migrations, ordering renormalization.
- `imaging/`: decode of each format (small fixtures), orientation (8 EXIF values), ICC conversion (P3 fixture →
  known sRGB values ± 2), metadata extraction, palette determinism.
- Services: ingest idempotency, trash cascade/restore/purge, template push-update, import dry-run classification &
  remapping, export → import round-trip equality.

### 13.2 API tests (`tests/api`)

httpx `TestClient`, temp `data_dir` fixture, synthetic images. Cover: role matrix for every router, localhost trust
on/off, host/origin/CSRF rejections, pairing & setup flows, resumable upload (interrupt, resume, wrong hash),
optimistic concurrency (409), pagination, SSE event emission, archive safety (zip slip, oversized).

### 13.3 Geometry conformance (Python ↔ TS)

`conformance/geometry/*.json`: `{ name, input: {document/operation…}, expected: {…} }` for tiers, placement,
native linking, constraint solver, rounding. Verified by pytest **and** by a tiny Node script
`pnpm conformance` (plain script, not a test framework) — the single frontend check, justified by invariant 4.4-3.

### 13.4 Golden images (very light, `tests/golden`)

≈6 references at reduced canvas scale factor 0.25 for speed + 1 at full size: native single, fit-in-mat with
texture, recessed style, raised style, rotated overlapping collage, caption. Compare: mean absolute error ≤ 0.5 and
max channel diff ≤ 8 (text regions ≤ 32). `make golden-update` regenerates with explicit review.

### 13.5 Fixtures

Generated synthetically (scripts) where possible; real-device samples (Android JPEG / Ultra HDR,
AVIF) are small, owned by the user and licensed CC0 in-repo.

### 13.6 Manual verification in a browser (soft requirement)

There is no frontend test suite (§13), so UI work is verified by hand. Phases 1–6 were each driven in a real
browser and that is still the **preferred** evidence — it found bugs no backend test could (render loops, a
frozen tab, snapping that swallowed typed values, a caption drawn 14 px too high).

It is **not a blocking requirement**, because the tooling is not dependable:

- The Chrome-extension harness can no longer drive this app at all: the SSE stream (`/api/v1/events`) means the
  page never goes idle, so `executeScript`, screenshots and `get_page_text` time out — and so do
  `chromium --dump-dom` and `--virtual-time-budget`, for the same reason.
- What does work (2026-09-21) is CDP: a headless `chromium --remote-debugging-port=<port>` plus
  `Runtime.evaluate`, against the **production build served by the backend on trusted localhost** (no setup
  code). Synthetic events need care: mouse events go to the `<canvas>` (Konva listens below the container div)
  and a `KeyboardEvent` needs a `code` or tinykeys drops it.

So: drive the AC in a browser when a harness is available, and prefer checking the *saved document* through the
API over screenshots (a Konva canvas can capture black although its pixels are correct). When it is not
available, verify what can be verified without one — `make check`, the pure core through the conformance
fixtures, the API and the render endpoints — and **write in `docs/progress.md` what was not driven in a
browser**, so the gap is known rather than assumed away. A phase is not held back by the harness.

---

## 14. Phases & milestones

Each task lists **deliverables** and **acceptance criteria (AC)**. A phase ends with: all AC met, `make check`
green, docs + **AGENTS.md updated** (status section), short demo note in `docs/progress.md`. Driving the AC in a
real browser is **expected but not blocking** — see §13.6.

Dependency graph: `0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8`; `9` can start after `4` (parallel with 5–8);
`10` after `8` and `9`; `11` last.

### Phase 0 — Research spikes (de-risking)

| # | Spike | Output | AC |
|---|---|---|---|
| S1 | Decode matrix: pyvips-binary on P3 JPEG, Android Ultra HDR JPEG, AVIF, 16-bit PNG, CMYK JPEG; HEIC rejection path | `docs/research/decoding.md` + fixture files | Each fixture decodes to correct orientation and visually correct sRGB; capability detection code sketched |
| S2 | Phone originals over HTTP: **Android Chrome only** (iOS/Safari out of focus, user decision 2026-09-16), `accept` variants (`image/*`, explicit list, none), photo picker vs "Files" picker — find the configuration yielding **full-resolution files with EXIF (incl. GPS)** | `docs/research/phone-uploads.md` with a matrix (format, size, EXIF kept?) | Chosen input configuration + detection heuristics for converted files + user guidance text |
| S3 | *(Moved to the start of Phase 4 — needs the renderer.)* Preview parity prototype: shadow blur mapping, texture formula, caption metrics — Konva vs pyvips | `docs/research/render-parity.md` + screenshots | Documented tolerances; mapping formulas confirmed or corrected in §8.2 |
| S4 | hash-wasm SHA-256 speed on phones (50 MB file) + chunked upload over Wi-Fi | numbers in `phone-uploads.md` | < 5 s hashing for 50 MB on a recent phone, or fallback decided (hash server-side only) |

### Phase 1 — Foundations

1. **AGENTS.md + CLAUDE.md** (first commit) per §3; `README.md` skeleton; extract §5–§9, §12 into `docs/*`; ADRs:
   0001 stack, 0002 storage/content addressing, 0003 integer geometry & server-authoritative render,
   0004 auth model, 0005 display-target seam.
2. Backend skeleton: uv project, app factory, config (§4.5), logging, problem+json errors, `/system/info`,
   SQLAlchemy + Alembic initial migration (all §5 tables), WAL, data dir bootstrap, `the_frame_v2 serve|doctor`.
3. Frontend skeleton: Vite + TS strict, Tailwind + Radix base components, router with all routes as placeholders,
   shell/sidebar, theme switch, i18n setup + missing-key script, shortcut registry + empty command palette,
   OpenAPI type generation, openapi-fetch client, Query provider.
4. Tooling: Makefile (`dev`, `check` = ruff + mypy + pytest + eslint + tsc + conformance, `gen-api`, `build`,
   `docker`), pre-commit optional, `.editorconfig`, `.gitignore`.
5. Packaging: build frontend into `backend/src/the_frame_v2/static`; multi-stage Dockerfile (node build → python
   slim runtime), `compose.yaml` with `/data` volume and `THE_FRAME_V2_PUBLIC_URL`.
6. Jobs queue (`jobs/`) + SSE broadcaster with a demo job.

**AC**: `make dev` gives a working shell at http://localhost:5173 proxied to API; `the_frame_v2 serve` serves the
built SPA; `docker compose up` works with a volume; `make check` green; AGENTS.md accurate.

### Phase 2 — Security & devices

1. Auth dependencies: localhost trust, cookie device auth, roles, Host allowlist, Origin + custom header CSRF check,
   security headers, rate limiting.
2. Setup code flow (startup print + `setup-code` CLI) and `/setup` page.
3. Pairing: codes, QR page (desktop), `/pair` page (phone), device list/rename/role/revoke UI.
4. Optional TLS (`tls_cert/key`), `public_url` detection & override.

**AC**: API role matrix tests pass; DNS-rebinding and CSRF tests pass; phone on LAN pairs by QR in < 30 s;
revoked device gets 401 immediately; Docker instance requires setup code.

### Phase 3 — Ingest & photo library

1. Upload protocol (§10) with sessions, resume, verification, limits; dedupe check endpoint (incl. trashed).
2. Ingest job: sniff, decode (§8.3), metadata (EXIF via Pillow for JPEG/PNG, pyvips `exif-data` for AVIF; GPS), offline geocoding
   (`scripts/build_geonames.py` → compact dataset from GeoNames cities1000, CC BY 4.0, attribution in About/NOTICE;
   nearest city via lat/lon grid buckets), thumbs 256/768 WebP, proxy 2560 JPEG, palette (lazy), quality warnings,
   move to `originals/`, inbox state, SSE events.
3. Desktop upload: drag & drop files and folders (`webkitGetAsEntry`), folder picker (`webkitdirectory`), upload tray
   with progress.
4. Mobile upload UI (§11.6) incl. metadata sheet and pending meta.
5. Photos grid (virtualized, keyset pagination), photo detail drawer, Inbox view (grid, multi-select, dismiss).
6. `the_frame_v2 doctor` reports capabilities; startup check.

**AC**: 40 photos from an Android phone upload at original quality (per S2 findings), interrupted
Wi-Fi resumes without re-sending completed chunks, duplicates are skipped instantly; AVIF/P3/Ultra HDR fixtures render; a HEIC upload is rejected with guidance
correctly in thumbnails; inbox updates live on desktop during phone upload; budgets §8.5 for ingest met.

### Phase 4 — Artwork domain & renderer

1. `domain/document.py` (Pydantic v1 schema + validation + JSON Schema export), `geometry.py`, `quality.py`,
   `placement.py`; TS mirrors in `editor/core/`; conformance fixtures + `pnpm conformance`.
2. `imaging/render.py` full pipeline (§8.1), textures (`scripts/generate_textures.py`, deterministic, CC0),
   bundled fonts (OFL: e.g. Cormorant Garamond, Inter, EB Garamond, Josefin Sans — final pick in this phase),
   PNG/JPEG outputs, region render.
3. Render cache + coalesced render jobs + derived artwork columns + `artwork_photos` index.
4. Artwork API: create from photo(s) with default style/layout and placement, get, `PUT document` with versioning,
   patch, validate, duplicate, snapshots, render/thumb endpoints.
5. Built-in presets: 4–6 frame styles (None, Gallery recessed, Float mount, Thin black, Linen, Museum white),
   layouts (Single, 2 side-by-side, 1+2, 3 in a row, 2×2, 3×3, Polaroid pile).
6. Golden tests (§13.4).

**AC**: documents round-trip; invalid documents rejected with precise errors; golden tests pass; render budgets met;
a native 3840×2160 photo renders bit-identical to its sRGB decode.

### Phase 5 — Editor (single photo) & review flow

1. Konva canvas: mat/texture, slot image from proxy, bands, shadows, zoom/pan, selection handles.
2. Crop tool (pan/zoom inside slot, crop ratio presets), orient (90°/flip), placement switcher (fit_in_mat / fill / manual).
3. Margins control (uniform + per side, px and %), quality lock (3 modes) with constraint solver and native
   bidirectional linking (§7.3–7.4).
4. Quality badge (tier + %), snapping incl. quality points, alternatives panel with previews (§7.6), loupe (§11.4).
5. Style controls: color picker, swatches CRUD, photo palette, curated presets, texture + strength, bands (≤3), shadow.
6. Undo/redo, autosave with conflict handling, revert-to-opened.
7. Inbox → editor queue mode (validate & next), artwork title/tags (inherited from photos, pre-checked)/collections/favorite
   in a side sheet; pending phone metadata applied on creation.
8. TV preview (fullscreen, bezel, matte overlay, navigation).
9. Keyboard shortcuts + palette commands for all editor actions.

**AC**: process 40 inbox photos with keyboard only; slot badge updates live while dragging at 60 fps; native lock
keeps scale exactly 1 while editing margins and crop; alternatives appear when upscaling and apply correctly;
undo/redo covers every edit; reloading the page never loses more than 1 s of edits; client preview matches server
render within S3 tolerances.

**State (2026-09-19)**: done. All nine items are implemented, `make check` is green and the AC were
exercised in a real browser (client-vs-server parity measured: MAE ≤ 1.5/255, `docs/research/render-parity.md`),
except the "40 photos" scale of the review run (done on 11 drafts). Captions stay read-only here (editing them
is Phase 6, item 4). Verification notes and the three bugs it found: `docs/progress.md` (2026-09-19).

### Phase 6 — Multi-photo compositions

1. Add/remove slots, photo picker (search/filter, drag from filmstrip), swap photos between slots, empty slots.
2. Free-form move/resize/rotate with Konva transformer, smart guides (edges, centers, equal gaps), nudge.
3. Z-order (list drag, `[`/`]`), per-slot lock/crop/orient/bands/shadow, "fit slot to photo" / "fill slot".
4. Captions: add/edit inline, font/weight/size/color/spacing/anchor/rotation, snapping.
5. Multi-select operations (align, distribute, same size, apply decoration to all).

**AC**: build a 1+2 collage and a rotated polaroid pile in < 2 min each; server render matches preview; rotated slots
never show `native`; quality badges per slot correct.

**State (2026-09-21)**: done. Slots panel (z-order list with drag, add/remove, photo picker, swap, empty slot,
fit/fill), free-form move/resize/rotate on the canvas with smart guides (canvas, slot edges/centres, **equal
gaps**, `Alt` to disable), multi-selection (Shift-click) with align/distribute/same size/copy decorations
(`domain/arrange.py` ↔ `editor/core/arrange.ts`, §7.7), caption editing (panel + double-click inline on the
canvas, drag to move) and the shortcuts `a`, `t`, `[`, `]`, `Delete`, `$mod+a`. Verified in a browser over CDP
(see `docs/progress.md` for what was exercised and the three bugs it found).

### Phase 7 — Simple editor & parametric layouts

Full spec: `docs/simple-editor.md` (decisions taken with the user on 2026-09-21).

1. ✅ **done (2026-09-21)** — `composition` block in the artwork document (optional, schema stays v1)
   + the pure solver `domain/composition.py` ↔ `editor/core/composition.ts`, 186 conformance cases,
   recipe catalogue (`assets/presets/recipes.json`, 17 entries: rich for 2–4 photos, one default for
   5–6) and `GET /recipes`.
2. ✅ **done (2026-09-22)** — server authority: the mirrored `composition.apply` (§3.7's table),
   `PUT document` re-solves and overwrites the slot rects (crops re-fitted around their previous
   centre, locks downgraded, border → band, margins and the derived caption written back), and
   `POST /artworks` takes a composition — the default when no `layout_id` is given.
3. ✅ **done (2026-09-22)** — Simple editor panel: layout picker drawn by the solver itself,
   `Balance`, format chips (`Original` for a single photo, `Fill`, ratios, custom), `Outer`/`Gap`
   sliders expandable to four and bounded by a bisection on `solve_strict`, reframe + zoom inside a
   cell, photo swap, background & border, caption above/below. A hand-built artwork shows the
   picker and attaches a block when one is chosen.
4. ✅ **done (2026-09-22)** — `[Simple] [Advanced ᴮᴱᵀᴬ]` switch on the editor page, Simple by
   default, warning strip on the beta side; a free-form edit sets `composition.detached` (the rule:
   an edit detaches exactly when `apply` would overwrite it) and Simple offers a confirmed,
   undoable **Re-apply layout**.

**AC**: a 3-photo hero composition from an empty draft in under 30 s using only the picker and the two sliders;
switching format to 3:2 keeps every reframe; the server-stored rects equal the ones the editor previewed;
`make check` green with the new conformance cases.

**State (2026-09-22)**: done, all four stages. Driven in a real browser over CDP (§13.6): the AC
"the server-stored rects equal the ones the editor previewed" was checked directly — the effective
margin the panel displayed is the one the server stored after re-solving. The detach loop
(free-form edit → banner → Re-apply → `⌘Z`) round-trips through the server, and a shadow change
does **not** detach. Not measured: the "under 30 s" stopwatch, and the review-queue flow in Simple
mode.

### Phase 8 — Templates

Full spec: `docs/templates.md`.

1. ✅ **done (2026-09-23)** — frame styles CRUD (API + Templates page), "Save as style" from an
   artwork, cards with previews the page draws itself (a layout by the solver, a style as a mat
   with one framed photo).
2. ✅ **done (2026-09-23)** — a layout is a **recipe + parameters** (Phase 7's composition minus the
   caption text and `detached`); the absolute-rect layout code, `build_document` and
   `map_rect_to_area` are gone, the presets rewritten, `0004_parametric_layouts` clears the old rows
   and the stale `origin_layout_id`s.
3. ✅ **done (2026-09-23)** — apply to an artwork: `restyle` / `relayout`, pure and **mirrored**
   (`domain/templates.py` ↔ `editor/core/templates.ts`, 16 conformance cases), through
   `POST /artworks/{id}/apply-template` outside the editor and as a normal undoable edit inside it;
   origin + revision recorded, outdated = recorded revision below the template's.
4. ✅ **done (2026-09-23)** — usage & push update: server-side dry run, `pre_template_update`
   snapshot per artwork (so it is undoable), layouts skipping another photo count or a detached
   artwork, and a dialog that shows each artwork with its badge or its skip reason.
5. ✅ **done (2026-09-23)** — creating from a layout (`POST /artworks` with `layout_id`, fewer photos
   than cells leaves placeholders), the create dialog offering the saved layouts that fit the
   selection, and `settings.artwork_defaults` = style + recipe + format (`null` = follow the photos).
6. ✅ **done (2026-09-23)** — `.tfstyle.json` / `.tflayout.json` export & import, validated
   server-side like a hand-written document.

**AC**: editing a style never alters artworks until push update; push update is undoable via snapshot; batch create
of 40 photos produces 40 drafts in the review queue.

**State (2026-09-23)**: done. The first two AC are pinned by `tests/api/test_templates.py`
(editing a style leaves every artwork untouched until the push, and restoring the
`pre_template_update` snapshot puts the old look back). Batch create is unchanged from Phase 7 —
the dialog now also offers a saved layout — and was not re-measured at 40 photos.

### Phase 9 — Organization — **done** (2026-09-23, `docs/organization.md`)

1. Tags: autocomplete, create inline, tag manager (rename, merge, color, counts).
2. Favorites everywhere (grid, editor, phone upload), Favorites view.
3. Collections: nested tree with DnD (move/reorder, cycle prevention), manual item ordering (reorder mode), cover,
   description, date range, include-nested toggle, add/remove from grid/editor/bulk.
4. Filter bar (AST chips) + FTS search; smart collections = saved filter; smart collection editor.
5. Trash: soft delete, cascade dialog (trash artworks vs empty slots), batch restore, purge job (daily + manual),
   file/cache cleanup.
6. Mobile read-only browse (artworks, collections, favorites).

**AC**: 10k-item seeded library (`scripts/seed_library.py`) browses smoothly; include-nested counts correct;
smart collections update live; deleting a used photo lists affected artworks and both cascade options behave;
purge frees disk space.

### Phase 10 — Export / Import — **done** (2026-09-23, `docs/archive-format.md`)

1. Archive writer (full/partial, optional renders) as a job + download; CLI `export`.
2. Archive reader: validation & safety, migrations, staging.
3. Dry-run report + policy UI (bulk + per item) + apply transaction; CLI `import --policy`.
4. Rendered images export (ZIP/folder structure).
5. JSON Schemas published in `docs/schemas/archive/`; `docs/archive-format.md` finalized.

Nothing about the file needs this app to read it: a ZIP of JSON + JSON Lines + the originals, with
a `sha256sum`-format checksum list — chosen so an archive stays openable if the app disappears.

**AC**: full export → import into empty library yields identical DB content (excluding devices/jobs) and identical
renders; partial import into a non-empty library classifies new/identical/conflicting correctly and all three
policies work; malicious archive fixtures are rejected.

### Phase 11 — Hardening & polish

1. Performance pass against §8.5 on seeded library; memory profiling of renders.
2. Accessibility pass (focus management, labels, contrast in both themes).
3. Error UX: toasts with problem types, job failure center, retry.
4. `service install` helpers (systemd user unit, launchd agent), docs for Windows.
5. Docs: user guide (pairing, sending originals from Android, quality tiers explained), README with screenshots,
   CONTRIBUTING, NOTICE (fonts, GeoNames, ICC profiles).
6. Security review against §9; dependency audit.
7. Decide name + license (open questions §16).

**AC**: all budgets met; no known data-loss bugs; fresh-user walkthrough (install → pair phone → upload → create
artwork → collection → export) completes without reading code.

---

## 15. Cross-cutting conventions & Definition of Done

### Conventions

- **Python**: ruff (lint + format), mypy strict, type hints everywhere, `snake_case`, no business logic in routers,
  services receive a `Session`, domain functions are pure and deterministic.
- **TypeScript**: strict, no `any`, feature folders, components `PascalCase.tsx`, hooks `useX.ts`, pure logic out of components.
- **API change workflow**: edit Pydantic models → `make gen-api` → fix TS compile errors → commit together.
- **DB**: every schema change = Alembic migration (never edit old migrations); migrations tested on an empty and a seeded DB.
- **Errors**: problem+json `type` = `https://the-frame-v2/errors/<code>`; frontend maps `<code>` to i18n key.
- **Time/IDs**: UTC ISO-8601; UUIDv7.
- **Commits**: Conventional Commits (`feat(editor): …`).
- **Docs**: specs in `docs/`; any behavior change to a spec updates the spec in the same change; decisions with
  trade-offs get an ADR.
- **Licensing of assets**: only OFL/CC0/CC BY with attribution recorded in NOTICE.

### Definition of Done (every task)

1. Code implements the spec; spec updated if it changed.
2. Backend tests added/updated; `make check` green.
3. API types regenerated if the API changed; conformance fixtures updated if geometry changed.
4. User-facing strings in i18n files; keyboard shortcut + palette command for new actions.
5. UI changes driven in a browser **when a harness is available** (§13.6 — soft, never blocking); when none is,
   what was not driven is written down in `docs/progress.md` instead of being assumed to work.
6. **`AGENTS.md` updated** (commands, repo map, invariants, gotchas, phase status) when anything it describes changed.
7. No TODO without an issue/plan reference.

---

## 16. Risks, open questions, out of scope

### Risks & mitigations

| Risk | Mitigation |
|---|---|
| Phones silently send converted/downscaled photos (Android photo picker may strip GPS/transcode) | Spike S2 before building upload UI; server-side heuristics + user guidance; desktop import as fallback |
| HEIC dropped: phones configured for HEIC get rejections | Spike S2 decides the upload configuration; clear rejection message + setup guidance; decoder seam keeps HEIC addable later |
| Preview ≠ render (shadows, text) | Integer geometry, identical texture formula, spike S3, server-rendered TV preview & loupe, golden tests |
| Memory spikes rendering many 48 MP sources | Sequential slot processing, libvips streaming, render_workers=1, LRU of 2 decoded images |
| Localhost trust abused via browser | Host allowlist, Origin + custom header, SameSite=Strict, no CORS |
| Scope size (11 phases) | Strict phase gating; phases 9 and 5–8 parallelizable; each phase shippable |
| SQLite concurrency with job workers | WAL, short transactions, single writer lock around job state updates |

### Open questions (to decide at the indicated phase)

- Final project name and license (Phase 11).
- Caption band factor (1.5 × size) reserved by the composition solver: implemented and pinned by
  conformance, still to be checked against a real render (Phase 7 stage 3, `docs/simple-editor.md` §10).
- ~~Exact bundled fonts and texture set (Phase 4)~~ — decided in ADR-0008.
- ~~Color-picker presets list (Phase 5)~~ — curated mat colours shipped in `services/colors.py` (`CURATED`,
  served by `GET /presets/colors`): museum white, warm off-white, linen, stone, charcoal, black.
- ~~Built-in styles look~~ — reviewed on real renders (2026-09-17): styles, layouts, fonts and textures kept;
  Float mount lost its inner white band; default style stays Gallery recessed (may change later).

### Out of scope for v1

TV connection/sync, HEIC/HEIF, RAW/TIFF/WebP inputs, AI upscaling, linear-light resampling, portrait canvas, multi-user
accounts, native mobile apps, PWA/offline, frontend test suite, CI, HDR tone mapping, face/saliency smart crop,
maps view, custom user fonts/textures.
