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
| `prepare-upload` | Sender recorded in `localsend_devices` (by announced fingerprint). `blocked` → 403. Only JPEG/PNG/AVIF (by extension or MIME) within `max_upload_bytes` are accepted; nothing supported → 403. Device `pending` (new) → the request waits for an admin decision (`localsend.request` SSE event → dialog in the web UI, which also says how many files are already in the library) up to `localsend_approval_timeout_seconds` (default 120 s); allow → device `approved` (auto-accepted from then on); decline/timeout → 403, device stays `pending`. Then files whose announced SHA-256 is already in the library are handled as **already sent** (see below). |
| `upload` | Bound to session, file token and sender IP (403 otherwise). Already-sent file → 409 with a message, body not read. Streamed to `uploads/tmp`, size and optional SHA-256 checked (400/422; the file can be retried); a file that turns out to be known (sender without checksum) → 409 with a message. Otherwise an `UploadSession` (`device_key = localsend:<id>`, state `processing`) is created and the regular `ingest` job runs (dedupe, copy merge, inbox, `photo.ingested`). |
| `cancel` | Drops the session (files already received are kept). |
| `info`, `register` | Return alias, `deviceType: server`, fingerprint. Registrations are not stored. |

Verified end-to-end (2026-09-17) with the official `localsend-cli` 1.18.2 (same Rust core as current apps):
discovery by alias over multicast, pinned TLS transfer, approval dialog, auto-accept of approved devices, files
stored byte-identical with place and name.

### Already-sent photos

A file whose SHA-256 is already in the library (photo or merged copy) is **not transferred again**, and the
sender's app sees a plain successful transfer — no error, no message:

| Case | Response to the phone | What the app shows |
|---|---|---|
| Some files already sent | They get no token in `prepare-upload` | Only the new photos transfer (the app hides files without a token); the transfer ends normally |
| Every file already sent | The **smallest one** gets a token; its `upload` → 200 and the copy is dropped | A normal, finished transfer of that one photo |
| Sender without SHA-256 (checksums disabled in the app) | `upload` → 200, the received copy is dropped | A normal, finished transfer |

Why transfer one photo instead of answering 204: the app pushes its transfer screen only for files it may
send. With nothing accepted it goes straight back to its home screen, so the user sees no sign that anything
happened. Accepting the smallest file costs one transfer and gives the usual "finished" screen.

Every received photo — already sent or not — goes back to the **inbox** (`photo_copies.receive_again`, the rule
for all uploads: `docs/data-model.md` "Photo copies"), and a trashed one is restored. Re-sending a photo is
therefore the natural way to find it in the inbox again. Its original file, import date, tags and artworks are
untouched.

Known files are only disclosed to allowed devices (a pending device is asked for first). Same image with
different metadata is not "already sent": it is received and merged by the ingest job.

The web UI is where this is spelled out: transfers are mirrored into the upload tray (admin SSE events
`localsend.transfer` with every offered file and its status `incoming | known | rejected`, `localsend.file` with
`receiving | processing | known | failed`, `localsend.cancelled`), so already-sent photos show "Already in your
library — back in the inbox · from <device>". An already-sent photo is not ingested, so no `photo.ingested`
event is published for it: `photo.updated` is what refreshes the open pages (inbox, library, counts).

Not implemented: PIN, download API (reverse transfer), protocol v1 routes, IPv6 multicast, text messages.

## Settings (`FRAME_IT_…`)

`LOCALSEND_ENABLED` (true) · `LOCALSEND_PORT` (53317, TCP, TLS) · `LOCALSEND_DISCOVERY` (true) ·
`LOCALSEND_MULTICAST_PORT` (53317, UDP) · `LOCALSEND_ALIAS` (`Frame It (<hostname>)`) ·
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

`localsend/identity.py` (certificate) · `localsend/dto.py` (wire models) · `localsend/client.py` (outgoing
connections) · `localsend/app.py` (protocol
routes) · `localsend/discovery.py` (multicast) · `localsend/runner.py` (starts server + discovery in the app
lifespan) · `services/localsend.py` (devices, approvals, sessions, hand-off to ingest) · `api/localsend.py`
(admin API) · frontend `features/localsend/` (approval dialog, Devices section). Tests:
`tests/api/test_localsend.py`.
