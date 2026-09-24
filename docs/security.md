# Security model

> Extracted from `PLAN.md` §9 (Phase 1). This file is now the maintained spec.

Threats: other devices on the LAN; **malicious websites in the admin's browser** targeting `localhost`
(CSRF, DNS rebinding); malicious files (decoder exploits, bombs); malicious archives (zip slip, zip bombs).

| Control | Detail |
|---|---|
| Device tokens | 256-bit random; stored as SHA-256; sent as cookie `tf_device` (HttpOnly, SameSite=Strict, `Secure` when HTTPS). |
| Localhost trust | Admin if peer IP is loopback **and** no proxy headers **and** `trust_localhost`. Disabled automatically with `trusted_proxies`. In Docker, peers are bridge IPs ⇒ not trusted. |
| Setup code | If no admin device exists and request is not trusted: 10-char code printed at startup (logs/terminal), single use, 1 h expiry; entering it registers the browser as admin. |
| Pairing | Admin creates code (role, 5 min, single use) → QR `http(s)://<public_url>/pair#code=…` (fragment ⇒ not in server logs) → phone POSTs code → device created, cookie set. |
| Host allowlist | Reject requests whose `Host` is not in `allowed_hosts` (DNS rebinding). |
| CSRF | Mutating requests require `Origin` matching an allowed host **and** header `X-TF-Client: 1` (forces CORS preflight; no CORS allowed). |
| Roles | `uploader`: uploads, read library, create tags, set upload metadata. `admin`: everything. Enforced per route via dependencies; API tests cover the matrix. |
| Rate limits | Pairing/setup-code attempts: 5/min and 20/hour per IP (in-memory, `auth/ratelimit.py`). |
| Dev server | Vite proxies `/api` with `xfwd: true`, so LAN devices using the dev server are never trusted as localhost. |
| Uploads | Size cap, SHA-256 verified at completion, magic-byte sniffing, pixel cap, decode in worker with try/except; temp files outside `originals/`. |
| Archives | Reject absolute paths/`..`, symlinks; cap total uncompressed size and entry count; verify checksums; never import devices/tokens. |
| Headers | CSP (self only), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. |
| Device management | List, rename, change role, revoke (immediate). |
| Rendering | Region renders ≤ 1024² px of a validated document (admin only); documents bounded (≤ 32 slots/captions, coordinates ±20 000, photos must exist); full renders bounded by `render_workers`; fonts/textures only from the bundled catalog (ids validated, no paths). |
| LocalSend receiver | Separate TLS port, no cookies/API access. Unknown sender devices wait for admin approval; approved ones are remembered, blockable. Identity = announced fingerprint (not verified, see `localsend.md`). JPEG/PNG/AVIF only, size cap, SHA-256 checked when announced, uploads bound to session token + sender IP, ≤ 10 pending approvals. |

---

## Review — 2026-09-24 (phase 11 §14.6)

Reviewed against the table above, plus a dependency audit. **No vulnerability was found that
needed a fix**; three hardening changes and one correction are recorded here.

### Dependency audit

| Set | Tool | Result |
|---|---|---|
| Python runtime (`uv export --no-dev`) | `pip-audit` | No known vulnerabilities |
| Python with dev group | `pip-audit` | No known vulnerabilities |
| JavaScript, production and dev | `pnpm audit` | No known vulnerabilities |

Reproduce with:

```sh
cd backend && uv export --no-emit-project --no-dev --format requirements.txt -o /tmp/reqs.txt \
  && uv run --with pip-audit pip-audit -r /tmp/reqs.txt
cd frontend && pnpm audit
```

### Response headers — tightened

Four directives were missing and are now sent on every response
(`auth/middleware.py`, pinned by `tests/api/test_auth.py::test_security_headers`):

| Header | Why |
|---|---|
| `form-action 'self'` (CSP) | A form's POST target is **not** covered by `default-src`, so an injected form could have posted elsewhere. |
| `object-src 'none'` (CSP) | Explicit rather than inherited. |
| `Cross-Origin-Resource-Policy: same-origin` | Another origin must not be able to embed a render or a thumbnail, or keep one in its cache. |
| `Cross-Origin-Opener-Policy: same-origin` | Severs the opener relationship with any window that opens us. |
| `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()` | Nothing here asks for a device; saying so means an injected script cannot either. |

### Renders — a bounded appetite

A render holds **every decoded original of the document at once** (pyvips builds a lazy pipeline,
so nothing can be released until the image is written). Measured with `scripts/bench_render.py` on
24 MP JPEGs: 6 slots peak at 1.6 GB RSS, 9 slots at 2.3 GB. A document may carry 32 slots, which at
48 MP each would ask for roughly 14 GB — an out-of-memory kill of the whole server, taking the job
queue with it, from a document a paired uploader could save.

`imaging/render.py` now refuses a render whose **distinct** sources exceed `MAX_RENDER_PIXELS`
(320 Mpx ≈ 1 GB of decoded pixels ≈ 2.5 GB peak, which covers 13 × 24 MP), with problem code
`render_too_large`. The count is read from the file headers, so nothing is decoded before the
refusal. Tested in `tests/unit/test_render_limits.py`.

### Archives — the size budget is now measured, not declared

`_safe_names` bounds an import by summing each member's declared `file_size`, which the archive
writes itself. That turns out to be sound in practice — CPython's `zipfile` stops a member at its
declared length and then fails its CRC, so understating it cannot smuggle a bomb through — but it
is a property of the standard library rather than of the ZIP format. `_verify_checksums` already
streamed every member before anything else read one; it now spends the byte budget against the
bytes it actually sees, so the guarantee no longer depends on that behaviour. Both cases are
pinned: `test_a_member_that_lies_about_its_size_is_refused` and
`test_an_archive_over_the_size_budget_is_refused`.

### Checked and found correct

- **CSRF.** Mutating `/api/` requests need `X-TF-Client: 1` (impossible from a cross-origin form,
  and it forces a preflight that no CORS handler answers) plus a same-origin `Origin` when one is
  sent; `Origin: null` is refused outright. Every mutating route is under `/api/` — everything
  outside it is `GET`.
- **Host allowlist.** Applied before anything else, port-stripped, IPv6-aware.
- **Localhost trust.** Loopback **and** no proxy header **and** `trust_localhost`; any of
  `X-Forwarded-For`, `X-Real-IP` or `Forwarded` disqualifies the request. Docker peers are bridge
  addresses, so a container is never trusted.
- **Rate limits.** Both code-redemption routes go through the limiter (5/min, 20/h per IP); no
  other route hands out a credential.
- **Device tokens.** 256-bit random, stored as SHA-256, matched by an indexed lookup rather than a
  comparison. Revocation is immediate (the lookup filters `revoked_at`).
- **SPA file serving.** `resolve()` plus a "must be a descendant of the static dir" check.
- **Archive member names.** Absolute paths, drive letters, backslashes, `.`/`..` and empty
  segments are rejected rather than normalized; originals must be content-addressed names.
- **SSE.** `/events` requires an authenticated principal and the broker filters by audience.

### Known and accepted

- **A LocalSend sender's identity is its announced fingerprint**, which is not verified — see
  `docs/localsend.md`. Unknown senders wait for an admin's approval, which is the actual control.
- **The app runs over plain HTTP on the LAN by default.** Cookies get `Secure` only under HTTPS,
  and the threat model is a home network, not a hostile one (`docs/PLAN.md` §9).
- **`style-src 'unsafe-inline'`** is required by the component libraries' inline styles. Scripts
  are not: `script-src 'self' 'wasm-unsafe-eval'`, the wasm being the upload hasher.
