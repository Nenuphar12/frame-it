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
| LocalSend receiver | Separate TLS port, no cookies/API access. Unknown sender devices wait for admin approval; approved ones are remembered, blockable. Identity = announced fingerprint (not verified, see `localsend.md`). JPEG/PNG/AVIF only, size cap, SHA-256 checked when announced, uploads bound to session token + sender IP, ≤ 10 pending approvals. |
