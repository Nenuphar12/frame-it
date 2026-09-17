# S2 / S4 — Phone uploads over plain HTTP (2026-09-16)

Scope: **Android + Chrome only** (iOS/Safari out of focus, user decision 2026-09-16).

## Status

| Item | Status |
|---|---|
| Upload protocol (resumable chunks, dedupe, verification) | ✅ implemented and tested (API tests + scripted LAN client) |
| Hashing without secure context (hash-wasm) | ✅ works over HTTP; benchmark below |
| Android Chrome picker behaviour | ✅ verified 2026-09-17 (Pixel 8 Pro, Chrome) — results below |

## Results on a real Android phone (2026-09-17)

Same photos copied over USB vs uploaded through each picker:

| Picker | Bytes identical? | File name | GPS |
|---|---|---|---|
| Photos (`accept="image/*"`, Android photo picker) | size identical, **only GPS bytes differ** | MediaStore id (`1000125423.jpg`) | **zeroed** |
| Files (document picker) | size identical, **only GPS bytes differ** | original (`PXL_…MP.jpg`) | **zeroed** |

- Pixels, ICC, capture time, camera, Ultra HDR gain map and Motion Photo payload are preserved (full quality).
- Android zeroes the GPS IFD **in place** (same size; `GPSVersionID` = `0.0.0.0`, refs NUL) for any app without
  `ACCESS_MEDIA_LOCATION`. Chrome does not hold it, so **no web picker can obtain the location**. Initial
  hypotheses 1–2 below are thus refuted for GPS; hypothesis 1 also loses the file name.
- Consequences: `place_name` is always empty for browser uploads (detected → warning `location_removed`); the
  SHA-256 of a browser upload differs from a USB/Syncthing copy of the same photo (dedupe across transfer
  methods would need a metadata- or pixel-based key).
- Chosen solution (2026-09-17, option "C"): keep browser uploads and **merge a later copy** carrying GPS and
  the real name (USB, LocalSend, desktop drop) by content fingerprint — see `docs/data-model.md` "Photo copies".
  Verified with these real files: redacted upload + USB copy → one photo with place and camera file name.
- Options kept for later: server-side folder import (Syncthing/SMB), a LocalSend-protocol receiver built into
  the server, a native Android app with `ACCESS_MEDIA_LOCATION`, manual place entry.

## Converted-file heuristics (`services/ingest.py::quality_warnings`)

| Warning | Rule |
|---|---|
| `metadata_missing` | no DateTimeOriginal/DateTime and no camera Make |
| `location_removed` | GPS IFD present without usable coordinates, `GPSVersionID` and latitude ref blank/NUL |
| `possibly_downscaled` | long edge < 2000 px |
| `below_tv_resolution` | both dimensions below 3840×2160 |
| `high_bit_depth_reduced` | PNG with > 8 bits per channel |

## S4 — Hashing speed

`hash-wasm` SHA-256 over 50 MiB in 8 MiB slices: **~375 ms** on the development laptop (Node 24, x86-64).
Phones are typically 3–6× slower → ~1–2.5 s for 50 MiB, within the < 5 s budget. To confirm on the real device.
