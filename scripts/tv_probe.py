#!/usr/bin/env python3
"""S5a-S5c spike (`docs/research/tv-display.md`): what can we actually do to the Frame?

Probes the TV's art channel, runs every read-only request it knows, and reports a feature matrix
(request → worked? value? how long?) as a table plus a Markdown/JSON report. Writes — uploading,
selecting, favouriting, the slideshow, art mode, deleting — each need their own flag, and the only
thing this script ever deletes is content **it uploaded in the same run**.

Usage (the backend venv brings pyvips for the test charts; `--with` keeps the library out of
`pyproject.toml` while this is still a spike):

    cd backend
    uv run --with samsungtvws python ../scripts/tv_probe.py --scan
    uv run --with samsungtvws python ../scripts/tv_probe.py --host 192.168.1.42

    # S5b — does `send_image` work on 2025 firmware, and is the panel 1:1?
    uv run --with samsungtvws python ../scripts/tv_probe.py --host 192.168.1.42 \
        --make-chart /tmp/chart.png --upload /tmp/chart.png --file-type both \
        --select-uploaded --keep-uploaded

    # S5c — does the TV walk *our* order?
    uv run --with samsungtvws python ../scripts/tv_probe.py --host 192.168.1.42 \
        --order-test 5 --slideshow 1 --ordered

    # clean up whatever an earlier run left behind (ids are in the reports)
    uv run --with samsungtvws python ../scripts/tv_probe.py --host 192.168.1.42 --delete MY_F0042

If the sync client's upload is refused (fork issue #19, seen on 2025 units), retry with the fork's
async client — same flags, plus `--client async`:

    uv run --with 'samsungtvws @ git+https://github.com/NickWaterton/samsung-tv-ws-api' \
        python ../scripts/tv_probe.py --host 192.168.1.42 --client async --upload /tmp/chart.png

First run: the TV shows an "allow this device?" prompt (it must be on, or in art mode). Accept it
with the remote; the token is saved to `--token-file` and reused afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import contextlib
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / ".dev-data" / "tv-probe"
DEFAULT_TOKEN = REPO / ".dev-data" / "tv-token.txt"
CATEGORIES = {"MY-C0002": "my pictures", "MY-C0004": "favourites", "MY-C0008": "store"}


# --------------------------------------------------------------------------------------- results


@dataclass
class Result:
    """One request: did it work, how long did it take, what did it say."""

    step: str
    request: str
    ok: bool
    ms: int
    value: str = ""
    error: str = ""
    write: bool = False


@dataclass
class Report:
    host: str
    client: str
    started_at: str
    results: list[Result] = field(default_factory=list)
    uploaded: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def short(value: Any, limit: int = 240) -> str:
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict) and any(isinstance(v, (bytes, bytearray)) for v in value.values()):
        # A thumbnail batch: name the items and their sizes, never dump the pixels.
        return ", ".join(f"{k}: {len(v)} bytes" for k, v in list(value.items())[:6])
    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class UnreachableError(Exception):
    """Nothing answered: probing 15 more times would only print the same timeout."""


class Runner:
    """Runs a request, records the outcome, never lets one failure end the probe."""

    def __init__(self, report: Report, verbose: bool, step_timeout: float = 25.0) -> None:
        self.report = report
        self.verbose = verbose
        self.step_timeout = step_timeout
        #: Drops the art connection after a hung request, so the next one reconnects.
        self.reset: Callable[[], None] | None = None

    def _bounded(self, call: Callable[[], Any]) -> Any:
        """Run `call` in a thread we can walk away from.

        A request the TV simply never answers (e.g. `get_auto_rotation_status`, which API 5.x
        dropped in favour of `get_slideshow_status`) leaves the client blocked forever — the
        socket timeout does not fire because the socket is healthy, only silent.
        """
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                box["value"] = call()
            except BaseException as exc:
                box["error"] = exc

        thread = threading.Thread(target=run, daemon=True, name="probe-step")
        thread.start()
        thread.join(self.step_timeout)
        if thread.is_alive():
            if self.reset is not None:
                with contextlib.suppress(Exception):
                    self.reset()
            raise TimeoutError(
                f"no reply in {self.step_timeout:.0f} s — this firmware most likely does not "
                "implement this request"
            )
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def step(
        self,
        step: str,
        request: str,
        call: Callable[[], Any],
        *,
        write: bool = False,
    ) -> tuple[bool, Any]:
        start = time.monotonic()
        try:
            value = self._bounded(call)
        except Exception as exc:
            ms = int((time.monotonic() - start) * 1000)
            error = f"{type(exc).__name__}: {exc}"
            result = Result(step, request, False, ms, error=error, write=write)
            self.report.results.append(result)
            print(f"  ✗ {step:<28} {request:<28} {ms:>6} ms  {short(result.error, 120)}")
            return False, None
        ms = int((time.monotonic() - start) * 1000)
        result = Result(step, request, True, ms, value=short(value), write=write)
        self.report.results.append(result)
        print(f"  ✓ {step:<28} {request:<28} {ms:>6} ms  {short(value, 100)}")
        if self.verbose:
            print(f"      {short(value, 2000)}")
        return True, value


# ---------------------------------------------------------------------------------------- client


class AsyncArt:
    """The fork's async art client, driven from a background event loop so callers stay sync."""

    def __init__(self, host: str, token_file: str, port: int, timeout: float) -> None:
        from samsungtvws.async_art import SamsungTVAsyncArt  # type: ignore[import-not-found]

        self._timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="art-loop")
        self._thread.start()
        self._art = SamsungTVAsyncArt(
            host=host, port=port, token_file=token_file, name="Frame It probe"
        )
        self._submit(self._art.start_listening())

    def _submit(self, coro: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=self._timeout + 60)

    def __getattr__(self, name: str) -> Callable[..., Any]:
        attr = getattr(self._art, name)

        def call(*args: Any, **kwargs: Any) -> Any:
            return self._submit(attr(*args, **kwargs))

        return call

    def shutdown(self) -> None:
        try:
            self._submit(self._art.close())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)


class FakeArt:
    """An in-process TV (`--fake`): exercises every path of this script without hardware.

    It answers the way a 2025 Frame is expected to — art mode on, `MY-C0002`/`MY-C0008` content,
    an incrementing `MY-F…` content id per upload — so the output below is the shape to expect.
    """

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = [
            {"content_id": "SAM-F0001", "category_id": "MY-C0008"},
            {"content_id": "MY-F0001", "category_id": "MY-C0002", "matte_id": "none"},
        ]
        self.uploads = 0
        self.favourites: set[str] = set()
        self.slideshow: dict[str, str] = {"value": "off", "category_id": "", "content_list": ""}

    def supported(self) -> bool:
        return True

    def get_api_version(self) -> str:
        return "5.0.1"

    def get_device_info(self) -> dict[str, Any]:
        return {"version": "5.0.1", "frame_tv_support": "true"}

    def get_artmode(self) -> str:
        return "on"

    def get_artmode_settings(self, setting: str = "") -> list[dict[str, Any]]:
        return [{"brightness": 5}, {"color_temperature": 0}, {"motion_sensitivity": 3}]

    def get_brightness(self) -> dict[str, str]:
        return {"value": "5"}

    def get_color_temperature(self) -> dict[str, str]:
        return {"value": "0"}

    def get_rotation(self) -> dict[str, int]:
        return {"current_rotation_status": 1}

    def available(self, category: str | None = None) -> list[dict[str, Any]]:
        if category == "MY-C0004":
            return [i for i in self.items if i["content_id"] in self.favourites]
        return [i for i in self.items if not category or i["category_id"] == category]

    def get_current(self) -> dict[str, str]:
        return {"content_id": "MY-F0001"}

    def get_slideshow_status(self) -> dict[str, str]:
        return dict(self.slideshow)

    def get_auto_rotation_status(self) -> dict[str, str]:
        return {"value": "off"}

    def get_matte_list(self) -> list[dict[str, str]]:
        return [{"matte_type": "none"}, {"matte_type": "shadowbox"}]

    def get_photo_filter_list(self) -> list[dict[str, str]]:
        return [{"filter_id": "none"}, {"filter_id": "warm"}]

    def get_thumbnail(
        self, content_id_list: list[str], as_dict: bool = False
    ) -> dict[str, bytes] | bytes:
        thumbs = {cid: self._thumb() for cid in content_id_list}
        return thumbs if as_dict else next(iter(thumbs.values()))

    def get_thumbnail_list(self, content_id_list: list[str]) -> dict[str, bytes]:
        return {cid: self._thumb() for cid in content_id_list}

    @staticmethod
    def _thumb() -> bytes:
        import pyvips

        image = pyvips.Image.black(320, 180).new_from_image([80, 80, 80]).cast("uchar")
        buffer: bytes = image.copy(interpretation="srgb").jpegsave_buffer(Q=80)
        return buffer

    def upload(
        self,
        data: bytes,
        matte: str = "none",
        portrait_matte: str = "none",
        file_type: str = "jpg",
        date: str | None = None,
    ) -> str:
        self.uploads += 1
        content_id = f"MY-F10{self.uploads:02d}"
        self.items.append({"content_id": content_id, "category_id": "MY-C0002", "image_date": date})
        return content_id

    def select_image(self, content_id: str, category: str | None = None, show: bool = True) -> Any:
        return {"content_id": content_id, "show": show}

    def set_favourite(self, content_id: str, status: str = "on") -> Any:
        if status == "on":
            self.favourites.add(content_id)
        else:
            self.favourites.discard(content_id)
        return {"content_id": content_id, "status": status}

    def set_slideshow_status(
        self,
        duration: int = 0,
        type: bool = True,  # noqa: A002 — the library's own parameter name
        category: int = 2,
    ) -> Any:
        return self._request_json(
            "set_slideshow_status",
            value=str(duration) if duration else "off",
            category_id=f"MY-C000{category}",
            type="shuffleslideshow" if type else "slideshow",
            content_list=json.dumps(
                [
                    {"content_id": i["content_id"], "category_id": "MY-C0002"}
                    for i in self.items
                    if i["category_id"] == "MY-C0002"
                ]
            ),
        )

    def set_artmode(self, mode: bool) -> Any:
        return {"value": "on" if mode else "off"}

    def _request_json(self, request: str, **params: Any) -> Any:
        """Mimic a picky TV: only some value shapes are accepted, everything else is -7."""
        if request == "change_favorite":
            if params.get("status") != "true":
                raise RuntimeError(f"`{request}` request failed with error number -7")
            self.favourites.add(str(params.get("content_id")))
            return {"content_id": params.get("content_id"), "status": "true"}
        if request == "set_slideshow_status":
            value = params.get("value")
            if value not in {"3", "5", "10", "30", "60", "off"}:
                raise RuntimeError(f"`{request}` request failed with error number -7")
            if value != "off" and self.slideshow.get("value", "off") != "off":
                raise RuntimeError(f"`{request}` request failed with error number -7")
            entries = params.get("content_list")
            listed = entries if isinstance(entries, str) else json.dumps(entries or [])
            self.slideshow = {
                "value": str(value),
                "type": str(params.get("type", "")),
                "category_id": str(params.get("category_id", "")),
                "content_list": listed if value != "off" else "",
            }
            return dict(params)
        return {"request": request, **params}

    def delete_list(self, content_ids: list[str]) -> bool:
        doomed = set(content_ids)
        self.items = [i for i in self.items if i["content_id"] not in doomed]
        return True


FAKE_DEVICE = {
    "device": {
        "name": "Fake Frame",
        "modelName": "QE55LS03FAU",
        "model": "25_PTM_FTV",
        "FrameTVSupport": "true",
        "TokenAuthSupport": "true",
        "PowerState": "standby",
        "wifiMac": "aa:bb:cc:dd:ee:ff",
    }
}


PAIRING_HELP = """  The prompt is shown by the TV itself, and only when it can draw on screen:
  · Turn the TV fully ON (normal mode, any input). In art mode the panel is in standby and
    Samsung does not draw the dialog — this is the usual reason nothing appears.
  · Accept "Allow ... to connect?" with the remote within the timeout.
  · Nothing at all? Settings → General (& Privacy) → External Device Manager →
    Device Connection Manager: set *Access Notification* to First Time Only / On, then open
    *Device List* and delete any earlier entry for this device (a denial is remembered).
  · Then run this command again."""


def pair(args: argparse.Namespace) -> bool:
    """Get a token by opening the REMOTE-CONTROL channel.

    The art channel needs a token on current firmware but never raises the "allow this device"
    dialog itself (fork issue #15) — opening `samsung.remote.control` on 8002 is what does, and
    the token it stores is the one the art channel then uses.
    """
    from samsungtvws import SamsungTVWS

    timeout = max(args.timeout, 45.0)
    print(f"\nPairing on the remote-control channel (waiting up to {timeout:.0f} s)")
    print(PAIRING_HELP)
    tv = SamsungTVWS(
        host=args.host,
        port=args.port,
        token_file=str(args.token_file),
        timeout=timeout,
        name=args.name,
    )
    try:
        tv.open()
    except Exception as exc:
        print(f"  ✗ pairing failed: {type(exc).__name__}: {exc}")
        return False
    finally:
        with contextlib.suppress(Exception):
            tv.close()
    token = args.token_file.read_text().strip() if args.token_file.exists() else (tv.token or "")
    if token:
        print(f"  ✓ paired — token saved to {args.token_file}")
        return True
    print("  ✗ no token came back (the TV answered but did not hand one over)")
    return False


def make_art(args: argparse.Namespace) -> Any:
    """The art client for `--client`, falling back to sync when the fork is not installed."""
    if args.fake:
        return FakeArt()
    wanted = args.client
    if wanted == "auto":
        wanted = "async" if _has_async_art() else "sync"
    if wanted == "async":
        if not _has_async_art():
            sys.exit(
                "--client async needs the fork: re-run with\n"
                "  uv run --with 'samsungtvws @ git+https://github.com/NickWaterton/"
                "samsung-tv-ws-api' python ../scripts/tv_probe.py …"
            )
        return AsyncArt(args.host, str(args.token_file), args.port, args.timeout)
    from samsungtvws import SamsungTVWS

    tv = SamsungTVWS(
        host=args.host,
        port=args.port,
        token_file=str(args.token_file),
        timeout=args.timeout,
        name=args.name,
    )
    return tv.art()


def _has_async_art() -> bool:
    try:
        import samsungtvws.async_art  # noqa: F401
    except Exception:
        return False
    return True


# -------------------------------------------------------------------------------------- discovery


def rest_info(host: str, timeout: float = 1.0, fake: bool = False) -> dict[str, Any]:
    if fake:
        return dict(FAKE_DEVICE)
    with urllib.request.urlopen(f"http://{host}:8001/api/v2/", timeout=timeout) as response:
        payload: dict[str, Any] = json.loads(response.read().decode())
    return payload


def local_prefix() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip: str = sock.getsockname()[0]
    finally:
        sock.close()
    return ip.rsplit(".", 1)[0]


def scan(subnet: str | None = None) -> None:
    """Find Samsung TVs on a /24 by asking every address for `/api/v2/` (read-only)."""
    prefix = subnet.rstrip(".") if subnet else local_prefix()
    print(f"scanning {prefix}.1-254:8001 …")
    found = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        futures = {
            pool.submit(rest_info, f"{prefix}.{last}", 0.8): f"{prefix}.{last}"
            for last in range(1, 255)
        }
        for future in concurrent.futures.as_completed(futures):
            host = futures[future]
            try:
                info = future.result()
            except urllib.error.URLError, OSError, ValueError, json.JSONDecodeError:
                continue
            device = info.get("device", {})
            found += 1
            print(
                f"  {host:<16} {device.get('name', '?')} — {device.get('modelName', '?')} "
                f"(model code {device.get('model', '?')}, FrameTVSupport="
                f"{device.get('FrameTVSupport')}, "
                f"TokenAuthSupport={device.get('TokenAuthSupport')}, "
                f"PowerState={device.get('PowerState')})"
            )
    if not found:
        print("  nothing answered — is the TV on the same LAN, and awake at least once?")


# ----------------------------------------------------------------------------------- test images


def fidelity_chart(path: Path, width: int = 3840, height: int = 2160) -> Path:
    """A chart that shows what the panel does to our pixels: re-encode, crop, rescale, tint."""
    import pyvips

    margin, gap, caption_gap = 160, 90, 24
    image = (pyvips.Image.black(width, height).new_from_image([48, 48, 48]).cast("uchar")).copy(
        interpretation="srgb"
    )

    def label(text: str, x: int, y: int, points: int = 40) -> int:
        """Draw a caption, return its height (0 when pango is unavailable)."""
        try:
            mask = pyvips.Image.text(text, font=f"sans {points}", dpi=72)
        except Exception as exc:
            print(f"  (no text labels: {exc})")
            return 0
        nonlocal image
        overlay = mask.new_from_image([255, 235, 120]).copy(interpretation="srgb")
        image = rgb(image.composite2(overlay.bandjoin(mask), "over", x=x, y=y))
        return int(mask.height)

    def band(element: Any, y: int, caption: str) -> int:
        """Place an element at the left margin, caption it, return the next free y."""
        nonlocal image
        image = image.insert(element.copy(interpretation="srgb"), margin, y)
        bottom = y + element.height + caption_gap
        return bottom + label(caption, margin, bottom, 34) + gap

    cursor = margin // 2
    cursor += label(f"Frame It TV probe — {width}×{height}, sRGB", margin, cursor, 56) + gap

    checker_w, checker_h = 1400, 360
    cxy = pyvips.Image.xyz(checker_w, checker_h)
    checker_band = (((cxy[0] + cxy[1]) % 2) * 255).cast("uchar")
    checker = checker_band.bandjoin([checker_band, checker_band])
    cursor = band(
        checker,
        cursor,
        "1 px checkerboard — smooth grey from the sofa is right; up close it must stay a "
        "crisp checker. Smearing or blocking = the TV re-encoded the upload.",
    )

    ramp_w, ramp_h = 3200, 180
    rxy = pyvips.Image.xyz(ramp_w, ramp_h)
    ramp_band = (rxy[0] * 255 / ramp_w).cast("uchar")
    ramp = ramp_band.bandjoin([ramp_band, ramp_band])
    cursor = band(ramp, cursor, "grey ramp — visible steps/banding = re-encode or tone mapping")

    bar_colours = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (0, 255, 255),
        (255, 0, 255),
        (255, 255, 0),
        (255, 255, 255),
        (0, 0, 0),
    ]
    bar_w, bar_h = ramp_w // len(bar_colours), 180
    bar_row = pyvips.Image.black(ramp_w, bar_h).new_from_image([0, 0, 0]).cast("uchar")
    for index, colour in enumerate(bar_colours):
        bar = pyvips.Image.black(bar_w, bar_h).new_from_image(list(colour)).cast("uchar")
        bar_row = bar_row.insert(bar, index * bar_w, 0)
    cursor = band(
        bar_row,
        cursor,
        "colour bars — shifted hue or crushed white/black = a photo filter, art-mode colour "
        "temperature or brightness is on",
    )

    wedge_w, wedge_h = 3200, 200
    wxy = pyvips.Image.xyz(wedge_w, wedge_h)
    # Vertical line pairs whose period grows 2 → 12 px: rescaling shows up as moiré or as a
    # period that suddenly goes flat grey.
    period = (wxy[0] * 10 / wedge_w + 2).floor()
    wedge_band = (((wxy[0] / period).floor() % 2) * 255).cast("uchar")
    wedge = wedge_band.bandjoin([wedge_band, wedge_band])
    cursor = band(
        wedge,
        cursor,
        "line wedge, period 2 → 12 px — moiré or a band going flat grey = the panel rescaled",
    )

    for points in (10, 14, 20, 28):
        cursor += (
            label(
                f"{points} pt — pixel-perfect text stays sharp: the quick brown fox 0123456789",
                margin,
                cursor,
                points,
            )
            + 16
        )

    label(
        "1 px white frame + corner ticks — if any edge or tick is missing, the panel crops "
        "or overscans and nothing here is pixel-perfect.",
        margin,
        cursor + 40,
        34,
    )

    # 1 px frame + 240 px corner ticks: anything missing means the panel crops or overscans.
    white = pyvips.Image.black(1, 1).new_from_image([255, 255, 255]).cast("uchar")
    for x, y, w, h in (
        (0, 0, width, 1),
        (0, height - 1, width, 1),
        (0, 0, 1, height),
        (width - 1, 0, 1, height),
        (0, 0, 240, 8),
        (0, 0, 8, 240),
        (width - 240, 0, 240, 8),
        (width - 8, 0, 8, 240),
        (0, height - 8, 240, 8),
        (0, height - 240, 8, 240),
        (width - 240, height - 8, 240, 8),
        (width - 8, height - 240, 8, 240),
    ):
        tick = white.embed(0, 0, w, h, extend="copy").copy(interpretation="srgb")
        image = image.insert(tick, x, y)

    path.parent.mkdir(parents=True, exist_ok=True)
    save(image, path)
    print(f"  chart → {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return path


def numbered_image(path: Path, number: int, width: int = 3840, height: int = 2160) -> Path:
    """A big number on a distinct colour: for watching whether the TV keeps our order."""
    import pyvips

    hues = [(190, 60, 60), (60, 140, 90), (60, 90, 190), (190, 150, 60), (140, 60, 170)]
    colour = list(hues[(number - 1) % len(hues)])
    image = pyvips.Image.black(width, height).new_from_image(colour).cast("uchar")
    image = image.copy(interpretation="srgb")
    try:
        mask = pyvips.Image.text(str(number), font="sans bold 900", dpi=72)
        overlay = mask.new_from_image([255, 255, 255]).copy(interpretation="srgb")
        image = rgb(
            image.composite2(
                overlay.bandjoin(mask),
                "over",
                x=(width - mask.width) // 2,
                y=(height - mask.height) // 2,
            )
        )
    except Exception:
        block = pyvips.Image.black(200 * number, 400).new_from_image([255, 255, 255]).cast("uchar")
        image = image.insert(block.copy(interpretation="srgb"), 200, 200)
    path.parent.mkdir(parents=True, exist_ok=True)
    save(image, path)
    return path


def rgb(image: Any) -> Any:
    """Drop the alpha band `composite2` adds, so inserts and JPEG saving keep working."""
    return image.extract_band(0, n=3) if image.bands > 3 else image


def save(image: Any, path: Path) -> None:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        image.jpegsave(str(path), Q=95, subsample_mode="off", optimize_coding=True, strip=True)
    else:
        image.pngsave(str(path), compression=6, strip=True)


# ---------------------------------------------------------------------------------------- probing


def probe_reads(
    runner: Runner, art: Any, host: str, fake: bool = False, quick: bool = False
) -> dict[str, Any]:
    """Every read-only request, in the order that makes a failure easiest to interpret."""
    print("\nREST (no token needed)")
    ok, info = runner.step("device info", "GET /api/v2/", lambda: rest_info(host, fake=fake))
    device = (info or {}).get("device", {}) if ok else {}
    if device:
        print(
            f"      model {device.get('modelName')} / code {device.get('model')} · "
            f"FrameTVSupport={device.get('FrameTVSupport')} · "
            f"TokenAuthSupport={device.get('TokenAuthSupport')} · "
            f"PowerState={device.get('PowerState')} · wifiMac={device.get('wifiMac')}"
        )

    print("\nArt channel — capability & state")
    supported_ok, _ = runner.step("art supported", "supported", art.supported)
    version_ok, _ = runner.step("api version", "get_api_version", art.get_api_version)
    if not (ok or supported_ok or version_ok):
        raise UnreachableError(
            "neither the REST endpoint nor the art channel answered.\n"
            "  · right IP? try --scan (or --subnet 192.168.1 --scan)\n"
            "  · the TV must have been woken at least once since its last power cut\n"
            "  · first run: accept the 'allow this device' prompt on the TV, then run again\n"
            "  · a timeout on the art channel with no token file usually *is* that prompt"
        )
    runner.step("art device info", "get_device_info", art.get_device_info)
    art_ok, art_mode = runner.step("art mode on?", "get_artmode_status", art.get_artmode)
    runner.step("art mode settings", "get_artmode_settings", art.get_artmode_settings)
    runner.step("brightness", "get_brightness", art.get_brightness)
    runner.step("colour temperature", "get_color_temperature", art.get_color_temperature)
    runner.step("rotation", "get_current_rotation", art.get_rotation)

    print("\nArt channel — what is on the TV")
    listed, content = runner.step("content list", "get_content_list", lambda: art.available(None))
    mine: list[dict[str, Any]] = []
    if listed and isinstance(content, list):
        counts: dict[str, int] = {}
        for item in content:
            counts[str(item.get("category_id"))] = counts.get(str(item.get("category_id")), 0) + 1
        for category, count in sorted(counts.items()):
            print(f"      {category} ({CATEGORIES.get(category, '?')}): {count} items")
        mine = [i for i in content if i.get("category_id") == "MY-C0002"]
        if mine:
            print(f"      first of mine: {short(mine[0], 300)}")
    runner.step("current artwork", "get_current_artwork", art.get_current)
    runner.step("slideshow", "get_slideshow_status", art.get_slideshow_status)
    # Pre-2022 API: 5.x firmware answers `get_slideshow_status` instead and ignores this one.
    if not quick:
        runner.step(
            "auto rotation (legacy)", "get_auto_rotation_status", art.get_auto_rotation_status
        )
    runner.step("matte list", "get_matte_list", art.get_matte_list)
    runner.step("photo filters", "get_photo_filter_list", art.get_photo_filter_list)
    if mine and not quick:
        first = str(mine[0].get("content_id"))
        runner.step("thumbnail", "get_thumbnail", lambda: art.get_thumbnail([first]))

    if art_ok:
        state = str(art_mode)
        power = str(device.get("PowerState"))
        if "on" in state and power == "standby":
            runner.report.notes.append(
                "Confirmed the 2025 quirk (fork issue #33): REST PowerState=standby while "
                "get_artmode_status=on — never gate on PowerState."
            )
    return {"device": device, "mine": mine}


# ----------------------------------------------------------------------------------------- backup


def image_size(data: bytes) -> str:
    """WxH of an encoded image, best effort (pyvips is there in the backend venv)."""
    try:
        import pyvips

        image = pyvips.Image.new_from_buffer(bytes(data), "")
        return f"{image.width}×{image.height}"
    except Exception:
        return "?"


def backup(runner: Runner, art: Any, args: argparse.Namespace) -> Path | None:
    """Save what the TV can give back: the full inventory, plus a thumbnail per item.

    The art channel has **no request that returns a stored image**, only thumbnails — so this is a
    record of what is on the TV, not a way to recover the originals. Keep those where they came
    from (phone, SmartThings, USB).
    """
    ok, content = runner.step("inventory", "get_content_list", lambda: art.available(None))
    if not ok or not isinstance(content, list):
        return None

    category = None if args.backup_category == "all" else args.backup_category
    items = [i for i in content if not category or i.get("category_id") == category]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = args.out / f"backup-{stamp}"
    thumbs = folder / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    (folder / "inventory.json").write_text(json.dumps(content, indent=2, default=str))
    print(f"\n  inventory → {folder / 'inventory.json'} ({len(content)} items, all categories)")
    print(f"  thumbnails for {len(items)} item(s) in {args.backup_category}")

    ids = [str(i.get("content_id")) for i in items if i.get("content_id")]
    saved: dict[str, tuple[Path, int, str]] = {}

    def store(name: str, data: bytes) -> None:
        content_id = Path(name).stem or name
        path = thumbs / f"{_safe(content_id)}.jpg"
        path.write_bytes(bytes(data))
        saved[content_id] = (path, len(data), image_size(data))

    for start in range(0, len(ids), args.backup_batch):
        batch = ids[start : start + args.backup_batch]
        got, result = runner.step(
            f"thumbnails {start + 1}-{start + len(batch)} of {len(ids)}",
            "get_thumbnail_list",
            lambda b=batch: art.get_thumbnail_list(b),
        )
        if got and isinstance(result, dict) and result:
            for name, data in result.items():
                store(str(name), data)
            continue
        # Batch refused: one at a time, so a single bad item cannot cost the whole run.
        for content_id in batch:
            got, one = runner.step(
                f"thumbnail {content_id}",
                "get_thumbnail",
                lambda c=content_id: art.get_thumbnail([c], as_dict=True),
            )
            if got and isinstance(one, dict):
                for name, data in one.items():
                    store(str(name), data)

    by_id = {str(i.get("content_id")): i for i in items}
    lines = [
        f"# TV backup — {args.host}, {stamp}",
        "",
        f"{len(content)} items on the TV, {len(items)} in `{args.backup_category}`, "
        f"{len(saved)} thumbnail(s) saved.",
        "",
        "The art channel returns thumbnails only: this is a record of what the TV holds, **not** a "
        "copy of the originals.",
        "",
        "| content_id | category | size on TV | date | matte | thumbnail | thumb size |",
        "|---|---|---|---|---|---|---|",
    ]
    for content_id, item in sorted(by_id.items()):
        thumb = saved.get(content_id)
        lines.append(
            f"| `{content_id}` | {item.get('category_id', '?')} | "
            f"{item.get('width', '?')}×{item.get('height', '?')} | "
            f"{item.get('image_date', '?')} | {item.get('matte_id', '?')} | "
            f"{'thumbs/' + thumb[0].name if thumb else '—'} | "
            f"{(str(thumb[2]) + ', ' + f'{thumb[1] / 1024:.0f} kB') if thumb else '—'} |"
        )
    (folder / "index.md").write_text("\n".join(lines) + "\n")
    sizes = {t[2] for t in saved.values()}
    runner.report.notes.append(
        f"Backup: {len(content)} items inventoried, {len(saved)} thumbnails saved to {folder} "
        f"(thumbnail resolution: {', '.join(sorted(sizes)) or 'n/a'}). The art API cannot return "
        "the stored originals — only thumbnails."
    )
    print(f"  backup → {folder}")
    return folder


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:80] or "item"


# --------------------------------------------------------------------------------------- diagnose


def summarise_slideshow(payload: Any) -> str:
    """`get_slideshow_status` carries the TV's own playlist as a JSON string in `content_list`."""
    if not isinstance(payload, dict):
        return short(payload)
    entries = payload.get("content_list") or ""
    ids: list[str] = []
    if isinstance(entries, str) and entries.strip():
        with contextlib.suppress(Exception):
            ids = [str(i.get("content_id")) for i in json.loads(entries)]
    elif isinstance(entries, list):
        ids = [str(i.get("content_id")) if isinstance(i, dict) else str(i) for i in entries]
    tail = f" [{', '.join(ids[:4])}{'…' if len(ids) > 4 else ''}]" if ids else ""
    return (
        f"value={payload.get('value')} type={payload.get('type')} "
        f"category={payload.get('category_id')} · {len(ids)} in content_list{tail}"
    )


def diagnose(runner: Runner, art: Any, args: argparse.Namespace, uploaded: list[str]) -> None:
    """Find the shapes this firmware accepts for the calls that answered -7.

    -7 is the TV refusing a *value* (fork issue #20). Measured on a 2025 unit (API 5.0.1.0):
    `change_favorite` refuses every shape, and `set_slideshow_status` accepted "3 min, my pictures,
    shuffle" from a stopped slideshow but refused everything afterwards — hence the `off` before
    every attempt here. The prize is `content_list`: the TV reports one in `get_slideshow_status`,
    so it may also *accept* one, which would scope a slideshow to an explicit set of images.
    """
    if not hasattr(art, "_request_json"):
        print("  (this client exposes no raw request path — skipping)")
        return
    raw = art._request_json
    ids = list(args.diagnose_ids or uploaded or ([args.diagnose_id] if args.diagnose_id else []))
    if not ids:
        print("  (nothing to test with: pass --diagnose-ids <content_id> …)")
        return

    def stop() -> None:
        with contextlib.suppress(Exception):
            raw(
                "set_slideshow_status",
                value="off",
                category_id="MY-C0002",
                type="shuffleslideshow",
            )

    def read_back(label: str) -> None:
        ok, payload = runner.step(f"↳ {label}", "get_slideshow_status", art.get_slideshow_status)
        if ok:
            print(f"      {summarise_slideshow(payload)}")

    print("\nDiagnose — which durations and types this firmware accepts (stopped before each)")
    duration_variants = [
        ("3 min shuffle", {"value": "3", "type": "shuffleslideshow"}),
        ("3 min ordered", {"value": "3", "type": "slideshow"}),
        ("5 min shuffle", {"value": "5", "type": "shuffleslideshow"}),
        ("10 min shuffle", {"value": "10", "type": "shuffleslideshow"}),
        ("30 min shuffle", {"value": "30", "type": "shuffleslideshow"}),
        ("60 min shuffle", {"value": "60", "type": "shuffleslideshow"}),
    ]
    accepted: list[str] = []
    for label, params in duration_variants:
        stop()
        ok, _ = runner.step(
            label,
            "set_slideshow_status",
            lambda p=params: raw("set_slideshow_status", category_id="MY-C0002", **p),
            write=True,
        )
        if ok:
            accepted.append(label)
            read_back(label)
    runner.report.notes.append(f"Durations/types accepted: {accepted or 'none'}")

    print(f"\nDiagnose — can the slideshow be scoped to an explicit list? ({len(ids)} ids)")
    entries = [{"content_id": i, "category_id": "MY-C0002"} for i in ids]
    rich = [
        {
            "content_id": i,
            "category_id": "MY-C0002",
            "sub_category_id": "",
            "matte_id": "none",
            "portrait_matte_id": "none",
        }
        for i in ids
    ]
    list_variants: list[tuple[str, dict[str, Any]]] = [
        (
            "content_list = JSON string of {content_id, category_id}",
            {"content_list": json.dumps(entries)},
        ),
        ("content_list = list of {content_id, category_id}", {"content_list": entries}),
        ("content_list = JSON string, full item shape", {"content_list": json.dumps(rich)}),
        ("content_list = comma-separated ids", {"content_list": ",".join(ids)}),
        ("content_list = list of ids", {"content_list": ids}),
    ]
    scoped: list[str] = []
    for label, params in list_variants:
        stop()
        ok, _ = runner.step(
            label,
            "set_slideshow_status",
            lambda p=params: raw(
                "set_slideshow_status",
                value="3",
                category_id="MY-C0002",
                type="shuffleslideshow",
                **p,
            ),
            write=True,
        )
        if not ok:
            continue
        got, payload = runner.step("↳ read back", "get_slideshow_status", art.get_slideshow_status)
        if got:
            print(f"      {summarise_slideshow(payload)}")
            listed: list[str] = []
            entries_back = (payload or {}).get("content_list") or ""
            if isinstance(entries_back, str) and entries_back.strip():
                with contextlib.suppress(Exception):
                    listed = [str(i.get("content_id")) for i in json.loads(entries_back)]
            if listed and set(listed) == set(ids):
                scoped.append(label)
                print("      ★ the TV kept exactly our list")
    verdict = scoped or "nothing — the TV ignores or refuses it"
    runner.report.notes.append(f"content_list accepted and honoured by: {verdict}")

    if args.diagnose_favourites:
        print("\nDiagnose — favourites (every shape refused -7 on 2026-09-25)")
        for label, params in [
            ("status=on", {"status": "on"}),
            ("status=true", {"status": "true"}),
            ("status=on + category_id=MY-C0002", {"status": "on", "category_id": "MY-C0002"}),
        ]:
            runner.step(
                label,
                "change_favorite",
                lambda p=params: raw("change_favorite", content_id=ids[0], **p),
                write=True,
            )

    stop()


def diagnose_more(runner: Runner, art: Any, args: argparse.Namespace, ids: list[str]) -> None:
    """Round two: the real duration list, and any request that scopes without deleting.

    Measured 2026-09-25: `content_list` is *reported* by the TV but ignored when sent, so the
    slideshow always covers the whole category. Each item, however, carries a per-item
    `slideshow: "false"` flag — if a request exists to set it, a set can be scoped without
    deleting anybody's photos. These names are guesses probed with a short timeout; an unknown
    request simply never answers.
    """
    if not hasattr(art, "_request_json"):
        return
    raw = art._request_json
    target = ids[0] if ids else None

    def stop() -> None:
        with contextlib.suppress(Exception):
            raw(
                "set_slideshow_status", value="off", category_id="MY-C0002", type="shuffleslideshow"
            )

    print("\nDiagnose — the real list of accepted durations (minutes)")
    accepted: list[int] = []
    for minutes in (2, 3, 5, 10, 15, 20, 30, 45, 60, 120, 180, 360, 720, 1440):
        stop()
        ok, _ = runner.step(
            f"{minutes} min",
            "set_slideshow_status",
            lambda m=minutes: raw(
                "set_slideshow_status",
                value=str(m),
                category_id="MY-C0002",
                type="shuffleslideshow",
            ),
            write=True,
        )
        if ok:
            accepted.append(minutes)
    stop()
    runner.report.notes.append(f"Durations the TV accepts (minutes): {accepted or 'none'}")

    print("\nDiagnose — is there a request that scopes a set without deleting?")
    previous = runner.step_timeout
    runner.step_timeout = args.probe_timeout
    probes: list[tuple[str, dict[str, Any]]] = [
        ("get_slideshow_content_list", {}),
        ("get_slideshow_content", {}),
        ("get_sub_category_list", {}),
        ("get_album_list", {}),
        ("get_content_list_by_category", {"category_id": "MY-C0002"}),
    ]
    if target:
        probes += [
            ("set_slideshow_content", {"content_id": target, "status": "on"}),
            ("change_slideshow", {"content_id": target, "status": "on"}),
            ("change_slideshow_content", {"content_id": target, "status": "on"}),
            ("set_slideshow_content_status", {"content_id": target, "status": "on"}),
            ("change_slideshow_status", {"content_id": target, "status": "on"}),
        ]
    answered: list[str] = []
    for request, params in probes:
        ok, _ = runner.step(request, request, lambda r=request, p=params: raw(r, **p), write=True)
        if ok:
            answered.append(request)
    runner.step_timeout = previous
    runner.report.notes.append(
        f"Unknown requests that answered: {answered or 'none — no hidden scoping request found'}"
    )
    if target and answered:
        runner.step(
            "did the per-item slideshow flag move?",
            "get_content_list(MY-C0002)",
            lambda: [
                {i.get("content_id"): i.get("slideshow")}
                for i in art.available("MY-C0002")
                if str(i.get("content_id")) in set(ids)
            ],
        )


SLIDESHOW_MINUTES = (3, 15, 60, 720, 1440)  # measured on API 5.0.1.0; everything else is -7


def mirror(runner: Runner, art: Any, args: argparse.Namespace, keep: list[str]) -> None:
    """The real thing, rehearsed: make `MY-C0002` hold exactly `keep`, then start the slideshow.

    This is the only destructive path in this script, and it is a **dry run unless
    `--yes-delete-others` is passed**: the TV's slideshow cannot be scoped to a subset (measured
    2026-09-25 — `content_list` is ignored, favourites refuse, no per-item request exists), so
    "show only this set" means My Photos *is* the set.
    """
    if not keep:
        print("  (nothing to keep: --mirror needs uploads or --mirror-keep <content_id> …)")
        return

    ok, items = runner.step(
        "what is on the TV",
        "get_content_list(MY-C0002)",
        lambda: [str(i.get("content_id")) for i in art.available("MY-C0002")],
    )
    if not ok or not isinstance(items, list):
        return
    others = [i for i in items if i not in set(keep)]
    print(f"\n  keep {len(keep)}: {', '.join(keep)}")
    print(f"  not in the set: {len(others)} item(s)")
    if not args.yes_delete_others:
        print("  DRY RUN — pass --yes-delete-others to delete them (they cannot be recovered")
        print("  from the TV: the art channel returns thumbnails only, and not even those here)")
    elif others:
        runner.step(
            f"delete {len(others)} item(s) not in the set",
            "delete_image_list",
            lambda: art.delete_list(others),
            write=True,
        )

    if args.slideshow is None:
        return
    if args.slideshow not in SLIDESHOW_MINUTES and args.slideshow != 0:
        print(f"  ! {args.slideshow} min is not one of {SLIDESHOW_MINUTES} — the TV will answer -7")

    # Order matters, and it is the opposite of the obvious one: `select_image` STOPS a running
    # slideshow (measured 2026-09-25 — the status came back "off" right after). So jump to the
    # head of the set first, then start the slideshow, which leaves the panel where we put it and
    # the rotation armed.
    with contextlib.suppress(Exception):
        art.set_slideshow_status(duration=0, type=True, category=2)

    head = keep[-1] if args.newest_first else keep[0]
    if not args.no_select_first:
        runner.step(
            f"start the set at {head}",
            "select_image",
            lambda: art.select_image(head, show=True),
            write=True,
        )
        runner.step("↳ now showing", "get_current_artwork", art.get_current)

    runner.step(
        f"slideshow every {args.slideshow} min ({'ordered' if args.ordered else 'shuffle'})",
        "set_slideshow_status",
        lambda: art.set_slideshow_status(
            duration=args.slideshow, type=not args.ordered, category=2
        ),
        write=True,
    )
    got, payload = runner.step("↳ read back", "get_slideshow_status", art.get_slideshow_status)
    if not got:
        return
    print(f"      {summarise_slideshow(payload)}")
    listed: list[str] = []
    entries = (payload or {}).get("content_list") or ""
    if isinstance(entries, str) and entries.strip():
        with contextlib.suppress(Exception):
            listed = [str(i.get("content_id")) for i in json.loads(entries)]
    running = str((payload or {}).get("value", "?"))
    verdict = (
        f"playing exactly the set, every {running} min"
        if listed and set(listed) == set(keep)
        else f"playing {len(listed)} item(s) every {running} min, the set has {len(keep)}"
    )
    print(f"      {verdict}")
    runner.step("↳ now showing", "get_current_artwork", art.get_current)
    runner.report.notes.append(f"Mirror: {verdict}")
    if running == "off":
        runner.report.notes.append(
            "The slideshow is off after the push — something stopped it again; a push must be the "
            "last thing that touches the TV."
        )


def probe_writes(runner: Runner, art: Any, args: argparse.Namespace) -> None:
    uploads: list[Path] = []
    if args.order_test:
        print(f"\nBuilding {args.order_test} numbered images")
        uploads = [
            numbered_image(args.out / f"order-{n}.jpg", n) for n in range(1, args.order_test + 1)
        ]
    if args.upload:
        source = Path(args.upload)
        if args.file_type == "both":
            uploads.append(source)
            other = ".png" if source.suffix.lower() != ".png" else ".jpg"
            twin = args.out / (source.stem + other)
            print(f"\nRe-encoding the same image as {twin.suffix} for the format test")
            import pyvips

            save(pyvips.Image.new_from_file(str(source)), twin)
            uploads.append(twin)
        else:
            uploads.append(source)

    uploaded: list[dict[str, Any]] = []
    if uploads:
        print("\nArt channel — upload (the risky call on 2025 firmware, fork issue #19)")
    for index, path in enumerate(uploads):
        try:
            data = path.read_bytes()
        except OSError as exc:
            runner.step(
                f"upload {path.name}",
                "send_image",
                lambda e=exc: (_ for _ in ()).throw(e),
                write=True,
            )
            continue
        file_type = "png" if path.suffix.lower() == ".png" else "jpg"
        # Strictly increasing image_date, one minute apart, so the order test can tell whether the
        # TV's ordered slideshow follows the date we set or the order we uploaded in.
        date = datetime.now().replace(microsecond=0) + timedelta(minutes=index)
        stamp = date.strftime("%Y:%m:%d %H:%M:%S")
        label = f"upload {path.name} ({len(data) / 1e6:.1f} MB {file_type})"
        ok, content_id = runner.step(
            label,
            "send_image",
            lambda d=data, f=file_type, s=stamp: art.upload(
                d, matte="none", portrait_matte="none", file_type=f, date=s
            ),
            write=True,
        )
        if ok and content_id:
            uploaded.append(
                {
                    "content_id": str(content_id),
                    "file": str(path),
                    "file_type": file_type,
                    "image_date": stamp,
                    "index": index + 1,
                }
            )
        if not args.fake:
            time.sleep(args.upload_pause)

    runner.report.uploaded = uploaded
    if uploaded:
        ids = [u["content_id"] for u in uploaded]
        print(f"      uploaded: {', '.join(ids)}")
        runner.step(
            "uploaded items listed",
            "get_content_list(MY-C0002)",
            lambda: [i for i in art.available("MY-C0002") if str(i.get("content_id")) in ids],
        )

    target = uploaded[0]["content_id"] if uploaded else args.select
    if target and (args.select_uploaded or args.select):
        runner.step(
            "show it now",
            "select_image",
            lambda: art.select_image(target, show=not args.no_show),
            write=True,
        )
        # Fork issue #31: on some units select_image drags the TV out of art mode.
        time.sleep(0 if args.fake else 3)
        runner.step("still in art mode?", "get_artmode_status", art.get_artmode)
        runner.step("current artwork", "get_current_artwork", art.get_current)

    if args.favourite_uploaded and uploaded:
        ours = [u["content_id"] for u in uploaded]
        for content_id in ours:
            runner.step(
                f"favourite {content_id}",
                "change_favorite",
                lambda c=content_id: art.set_favourite(c, "on"),
                write=True,
            )
        got, favourites = runner.step(
            "favourites now hold",
            "get_content_list(MY-C0004)",
            lambda: [str(i.get("content_id")) for i in art.available("MY-C0004")],
        )
        if got and isinstance(favourites, list):
            extra = sorted(set(favourites) - set(ours))
            missing = sorted(set(ours) - set(favourites))
            verdict = (
                "favourites == exactly this run's uploads"
                if not extra and not missing
                else f"extra: {extra or '—'} · missing: {missing or '—'}"
            )
            print(f"      {verdict}")
            runner.report.notes.append(f"Favourites after marking the set: {verdict}")

    if args.favourite and uploaded:
        first = uploaded[0]["content_id"]
        runner.step(
            "favourite on", "change_favorite", lambda: art.set_favourite(first, "on"), write=True
        )
        runner.step(
            "favourites listed",
            "get_content_list(MY-C0004)",
            lambda: len(art.available("MY-C0004")),
        )
        runner.step(
            "favourite off", "change_favorite", lambda: art.set_favourite(first, "off"), write=True
        )

    if args.slideshow is not None:
        ordered = args.ordered
        category_label = "favourites" if args.slideshow_category == 4 else "my pictures"
        runner.step(
            f"slideshow {args.slideshow} min, {category_label}"
            f" ({'ordered' if ordered else 'shuffle'})",
            "set_slideshow_status",
            lambda: art.set_slideshow_status(
                duration=args.slideshow, type=not ordered, category=args.slideshow_category
            ),
            write=True,
        )
        runner.step("slideshow read back", "get_slideshow_status", art.get_slideshow_status)
        if uploaded:
            order = ", ".join(f"{u['index']}→{u['content_id']}" for u in uploaded)
            runner.report.notes.append(f"Expected order (upload order / image_date): {order}")
            print(f"      watch the TV: expected order {order}")

    if args.artmode:
        runner.step(
            f"art mode {args.artmode}",
            "set_artmode_status",
            lambda: art.set_artmode(args.artmode == "on"),
            write=True,
        )
        runner.step("art mode read back", "get_artmode_status", art.get_artmode)

    doomed = [u["content_id"] for u in uploaded] if not args.keep_uploaded else []
    doomed += list(args.delete or [])
    if doomed:
        runner.step(
            f"delete {len(doomed)} item(s) this run put there",
            "delete_image_list",
            lambda: art.delete_list(doomed),
            write=True,
        )


# ----------------------------------------------------------------------------------------- report


def write_report(report: Report, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.replace(":", "").replace("-", "").replace(" ", "-")
    (out / f"{stamp}-report.json").write_text(json.dumps(asdict(report), indent=2, default=str))
    lines = [
        f"# TV probe — {report.host} ({report.client} client), {report.started_at}",
        "",
        "| Feature | Request | Result | ms | Value |",
        "|---|---|---|---|---|",
    ]
    for result in report.results:
        mark = "✅" if result.ok else "❌"
        if result.write:
            mark += " ✍️"
        value = (result.value or result.error).replace("|", "\\|")
        lines.append(
            f"| {result.step} | `{result.request}` | {mark} | {result.ms} | {value[:300]} |"
        )
    if report.uploaded:
        lines += ["", "## Uploaded in this run", ""]
        lines += [
            f"- `{u['content_id']}` — {Path(u['file']).name} ({u['file_type']}, {u['image_date']})"
            for u in report.uploaded
        ]
    if report.notes:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in report.notes]
    path = out / f"{stamp}-report.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--host", help="TV IP address")
    parser.add_argument("--scan", action="store_true", help="find Samsung TVs on this /24 and exit")
    parser.add_argument("--subnet", help="prefix to scan, e.g. 192.168.1 (default: this machine's)")
    parser.add_argument("--port", type=int, default=8002, help="8002 = TLS + token (default)")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--name",
        default="Frame It",
        help="how this app appears in the TV's Device List (default: %(default)s)",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="save the TV's inventory + a thumbnail per item before touching anything",
    )
    parser.add_argument(
        "--backup-category",
        default="MY-C0002",
        choices=("MY-C0002", "MY-C0004", "MY-C0008", "all"),
        help="which category to pull thumbnails for (default: %(default)s = your own photos)",
    )
    parser.add_argument("--backup-batch", type=int, default=8, help="thumbnails per request")
    parser.add_argument(
        "--step-timeout",
        type=float,
        default=25.0,
        help="give up on one request after this many seconds and carry on (default: %(default)s)",
    )
    parser.add_argument(
        "--pair",
        action="store_true",
        help="force the pairing handshake even when a token file already exists",
    )
    parser.add_argument("--client", choices=("auto", "sync", "async"), default="sync")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where reports and charts go")
    parser.add_argument("--verbose", action="store_true", help="print full payloads")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="skip the requests known not to answer on API 5.x (saves 50 s of timeouts)",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="run against an in-process fake TV (no hardware, no network): see the output shape",
    )
    parser.add_argument("--make-chart", type=Path, help="write a fidelity chart and use it")
    parser.add_argument("--upload", help="image to upload (3840×2160 expected)")
    parser.add_argument(
        "--file-type",
        choices=("as-is", "both"),
        default="as-is",
        help="both = upload the image as JPEG *and* PNG (fork issue #19: units differ)",
    )
    parser.add_argument("--upload-pause", type=float, default=2.0, help="seconds between uploads")
    parser.add_argument("--order-test", type=int, metavar="N", help="upload N numbered images")
    parser.add_argument("--select-uploaded", action="store_true", help="show the first upload")
    parser.add_argument("--select", metavar="CONTENT_ID", help="show an existing item")
    parser.add_argument("--no-show", action="store_true", help="select_image(show=False)")
    parser.add_argument("--favourite", action="store_true", help="test the favourites category")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="try every payload shape for the calls that came back -7 (favourites, slideshow)",
    )
    parser.add_argument(
        "--diagnose-id",
        metavar="CONTENT_ID",
        help="single item to diagnose with (default: the first upload of this run)",
    )
    parser.add_argument(
        "--diagnose-ids",
        nargs="*",
        metavar="CONTENT_ID",
        help="the set to try scoping a slideshow to (default: this run's uploads)",
    )
    parser.add_argument(
        "--diagnose-more",
        action="store_true",
        help="round two: sweep the durations, and hunt a request that scopes without deleting",
    )
    parser.add_argument(
        "--probe-timeout",
        type=float,
        default=6.0,
        help="seconds to wait on a guessed request name (default: %(default)s)",
    )
    parser.add_argument(
        "--diagnose-favourites",
        action="store_true",
        help="also retry change_favorite (every shape refused -7 on 2025 firmware)",
    )
    parser.add_argument(
        "--favourite-uploaded",
        action="store_true",
        help="mark every upload of this run as favourite and leave it so (the O1-fav test)",
    )
    parser.add_argument(
        "--slideshow-category",
        type=int,
        choices=(2, 4),
        default=2,
        help="2 = my pictures (MY-C0002), 4 = favourites (MY-C0004). Default: %(default)s",
    )
    parser.add_argument(
        "--slideshow",
        type=int,
        metavar="MINUTES",
        help="0 = off; this firmware accepts 3, 15, 60, 720 or 1440",
    )
    parser.add_argument(
        "--mirror",
        action="store_true",
        help="rehearse the real thing: make My Photos hold exactly this run's set (dry run)",
    )
    parser.add_argument(
        "--mirror-keep",
        nargs="*",
        default=[],
        metavar="CONTENT_ID",
        help="items to keep besides this run's uploads",
    )
    parser.add_argument(
        "--newest-first",
        action="store_true",
        help="with --mirror: start at the LAST uploaded item (this TV lists newest first)",
    )
    parser.add_argument(
        "--no-select-first",
        action="store_true",
        help="with --mirror: do not jump to the first image of the playlist after pushing",
    )
    parser.add_argument(
        "--yes-delete-others",
        action="store_true",
        help="with --mirror: actually delete everything else in My Photos (irreversible)",
    )
    parser.add_argument("--ordered", action="store_true", help="ordered instead of shuffle")
    parser.add_argument("--artmode", choices=("on", "off"))
    parser.add_argument("--keep-uploaded", action="store_true", help="leave the uploads on the TV")
    parser.add_argument("--delete", nargs="*", metavar="CONTENT_ID", help="delete these ids too")
    args = parser.parse_args()

    if args.scan:
        scan(args.subnet)
        return 0
    if args.fake:
        args.host = args.host or "fake-tv"
    if not args.host:
        parser.error("--host is required (or --scan to find the TV, or --fake to self-test)")

    args.out.mkdir(parents=True, exist_ok=True)
    if args.upload and not args.make_chart and not Path(args.upload).is_file():
        parser.error(
            f"--upload {args.upload}: no such file. Build one with "
            f"--make-chart {args.upload} (a 3840×2160 fidelity chart), or point --upload at a "
            "render from .dev-data/cache/renders/<artwork>/<hash>.jpg"
        )
    if args.make_chart:
        print("Building the fidelity chart")
        args.upload = str(fidelity_chart(Path(args.make_chart)))

    report = Report(
        host=args.host,
        client=args.client,
        started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    runner = Runner(report, args.verbose, args.step_timeout)
    print(f"Frame It TV probe — {args.host}:{args.port} ({args.client} client)")
    print(f"token file: {args.token_file}")
    if not args.token_file.exists() and not args.fake:
        print("no token yet — pairing first (the TV must be ON, not in art mode)")

    if not args.fake and (args.pair or not args.token_file.exists()):
        pair(args)

    art = make_art(args)
    if hasattr(art, "close"):
        runner.reset = art.close
    try:
        probe_reads(runner, art, args.host, fake=args.fake, quick=args.quick)
        if args.backup:
            backup(runner, art, args)
        probe_writes(runner, art, args)
        uploaded_ids = [u["content_id"] for u in runner.report.uploaded]
        if args.diagnose:
            diagnose(runner, art, args, uploaded_ids)
        if args.mirror:
            mirror(
                runner,
                art,
                args,
                [u["content_id"] for u in runner.report.uploaded] + list(args.mirror_keep),
            )
        if args.diagnose_more:
            chosen = list(
                args.diagnose_ids
                or uploaded_ids
                or ([args.diagnose_id] if args.diagnose_id else [])
            )
            diagnose_more(runner, art, args, chosen)
    except UnreachableError as exc:
        print(f"\nstopped: {exc}")
    finally:
        if isinstance(art, AsyncArt):
            art.shutdown()
        elif hasattr(art, "close"):
            with contextlib.suppress(Exception):
                art.close()

    path = write_report(report, args.out)
    failed = [r for r in report.results if not r.ok]
    print(f"\n{len(report.results) - len(failed)}/{len(report.results)} requests worked")
    for note in report.notes:
        print(f"note: {note}")
    print(f"report → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
