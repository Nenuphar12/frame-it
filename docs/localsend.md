# LocalSend receiver

The server implements the receiving side of the [LocalSend protocol v2](https://github.com/localsend/protocol),
so phones send photos with the LocalSend app. Unlike browser uploads, LocalSend transfers the **exact file**
(GPS location and original file name included — verified 2026-09-17 with a Pixel 8 Pro). The web upload page
stays available. Decision record: `adr/0007-localsend-receiver.md`.

## Behaviour

| Step | What happens |
|---|---|
| Discovery | At startup the server announces itself on multicast `224.0.0.167:53317` (3 messages). When a LocalSend app announces itself, the server answers with `POST /api/localsend/v2/register` to it (TLS, presenting its certificate as client certificate), or a multicast answer as fallback. |
| Identity | Self-signed RSA-2048 certificate in `<data_dir>/localsend/` (created once). Fingerprint = uppercase hex SHA-256 of the DER certificate; LocalSend apps pin it, so **never regenerate it** (senders would have to rediscover the server). |
| `prepare-upload` | Sender recorded in `localsend_devices` (by announced fingerprint). `blocked` → 403. Only JPEG/PNG/AVIF (by extension or MIME) within `max_upload_bytes` are accepted; files with a known SHA-256 are skipped; all known → 204; nothing supported → 403. Device `pending` (new) → the request waits for an admin decision (`localsend.request` SSE event → dialog in the web UI) up to `localsend_approval_timeout_seconds` (default 120 s); allow → device `approved` (auto-accepted from then on); decline/timeout → 403, device stays `pending`. |
| `upload` | Bound to session, file token and sender IP (403 otherwise). Streamed to `uploads/tmp`, size and optional SHA-256 checked (400/422; the file can be retried), then an `UploadSession` (`device_key = localsend:<id>`, state `processing`) is created and the regular `ingest` job runs (dedupe, copy merge, inbox, `photo.ingested`). |
| `cancel` | Drops the session (files already received are kept). |
| `info`, `register` | Return alias, `deviceType: server`, fingerprint. Registrations are not stored. |

Verified end-to-end (2026-09-17) with the official `localsend-cli` 1.18.2 (same Rust core as current apps):
discovery by alias over multicast, pinned TLS transfer, approval dialog, auto-accept of approved devices, files
stored byte-identical with place and name.

Not implemented: PIN, download API (reverse transfer), protocol v1 routes, IPv6 multicast, text messages.

## Settings (`THE_FRAME_V2_…`)

`LOCALSEND_ENABLED` (true) · `LOCALSEND_PORT` (53317, TCP, TLS) · `LOCALSEND_DISCOVERY` (true) ·
`LOCALSEND_MULTICAST_PORT` (53317, UDP) · `LOCALSEND_ALIAS` (`the_frame_v2 (<hostname>)`) ·
`LOCALSEND_APPROVAL_TIMEOUT_SECONDS` (120).

## Deployment notes

- **Firewall**: open TCP and UDP 53317 (NixOS: `networking.firewall.allowedTCPPorts`/`allowedUDPPorts`).
- **Same machine as a LocalSend desktop app**: TCP 53317 is taken → the receiver uses the next free port
  (up to +9; the real port is announced, shown in *Devices*). Without discovery the configured port is required.
  Multicast (UDP 53317) is shared with the app.
- **Docker**: multicast does not cross the bridge network. Either use `network_mode: host`, or publish
  `53317/tcp` and add the server by IP in LocalSend. Behind the bridge every sender appears with the gateway IP.

## Security

- Sender identity is the **announced** fingerprint: the Python TLS stack cannot request a self-signed client
  certificate without rejecting it, so it is not verified (unlike LocalSend-to-LocalSend mTLS). Someone on the
  LAN who learns an approved device's fingerprint (it is broadcast) could impersonate it — the same trust level
  as LocalSend "favorites". Mitigations: approval per device, block/forget in *Devices*, photos land in the
  inbox, size/format limits, at most 10 pending approvals.
- The LocalSend port has no cookies and no access to the main API.

## Code map

`localsend/identity.py` (certificate) · `localsend/dto.py` (wire models) · `localsend/app.py` (protocol
routes) · `localsend/discovery.py` (multicast) · `localsend/runner.py` (starts server + discovery in the app
lifespan) · `services/localsend.py` (devices, approvals, sessions, hand-off to ingest) · `api/localsend.py`
(admin API) · frontend `features/localsend/` (approval dialog, Devices section). Tests:
`tests/api/test_localsend.py`.
