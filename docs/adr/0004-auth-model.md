# ADR-0004 — Device-based authentication

Status: accepted (2026-09-16)

## Decision
No user accounts. Browsers become *devices* with a role (`admin` / `uploader`) by redeeming a single-use code:
a QR pairing code (created by an admin) or the setup code printed at startup. The device token is an HttpOnly,
SameSite=Strict cookie stored hashed server-side. Loopback requests without proxy headers are trusted as admin
(disabled when `trusted_proxies` is set). Guards: Host allowlist (DNS rebinding), `X-TF-Client` header + Origin
check on mutating API calls (CSRF), rate-limited code redemption.

## Consequences
Zero-setup on the computer running the server; phones pair in seconds; Docker deployments need the setup code.
Revocation is immediate. Details: `docs/security.md`.
