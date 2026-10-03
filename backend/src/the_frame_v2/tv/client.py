"""The Frame's art channel, reduced to what this app needs.

Everything here was measured against a 2025 Frame (`TQ55LS03FAUXXC`, art API 5.0.1.0) — see
`docs/research/tv-display.md`. The three findings that shape this module:

- **Pairing happens on the remote-control channel**, not the art channel: the art channel needs a
  token but never raises the TV's "allow this device" dialog. The TV must be ON (not art mode) to
  draw it.
- **The slideshow cannot be scoped**: `content_list` is reported but ignored, favourites refuse
  every shape (`-7`), and no per-item request exists. A category is all you can point it at.
- **`select_image` stops a running slideshow**, and setting a slideshow never moves the panel. A
  push is therefore: stop → select the first image → start.

`-7` from the TV means it refused a *value* (an interval outside `SLIDESHOW_MINUTES`, say), which
is why `TvRejectedError` is separate from `TvUnreachableError`. And a TV that is **off** still
accepts the websocket — its art app just never says it is ready — which is why
`TvArtUnavailableError` is separate too: "is it on the network?" is the wrong question there.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

log = logging.getLogger(__name__)

#: Intervals this firmware accepts, in minutes; anything else answers `-7` (measured).
SLIDESHOW_MINUTES: tuple[int, ...] = (3, 15, 60, 720, 1440)

MY_PICTURES = "MY-C0002"
FAVOURITES = "MY-C0004"
STORE = "MY-C0008"

FileType = Literal["jpg", "png"]


class TvError(Exception):
    """Something went wrong with the TV. `code` is the stable problem code clients see."""

    code = "tv_error"


class TvUnreachableError(TvError):
    """No answer: TV off the network, wrong address, or deep standby."""

    code = "tv_unreachable"


class TvArtUnavailableError(TvError):
    """The TV took the connection but its art app stayed silent: it is off, or not showing art."""

    code = "tv_art_unavailable"


class TvUnauthorizedError(TvError):
    """The TV has forgotten us (a power cut clears tokens) — pair again."""

    code = "tv_unauthorized"


class TvRejectedError(TvError):
    """The TV refused the request, usually a value it does not accept (`-7`)."""

    code = "tv_rejected"


@dataclass(frozen=True, slots=True)
class ArtItem:
    """One item in the TV's own store."""

    content_id: str
    category_id: str
    width: int | None = None
    height: int | None = None
    image_date: str | None = None
    matte_id: str | None = None

    @property
    def is_mine(self) -> bool:
        """In `MY-C0002` — i.e. a photo somebody uploaded, not Art Store content."""
        return self.category_id == MY_PICTURES


@dataclass(frozen=True, slots=True)
class TvInfo:
    """What a probe of the TV tells us."""

    model: str | None = None
    model_code: str | None = None
    name: str | None = None
    mac: str | None = None
    """Wi-Fi MAC (`wifiMac`): what identifies the TV when DHCP gives it another address."""
    api_version: str | None = None
    frame_support: bool = False
    token_auth: bool = False
    art_mode: bool = False
    my_pictures: int = 0
    store_items: int = 0
    slideshow_minutes: int | None = None
    slideshow_ordered: bool = False
    current_content_id: str | None = None
    warnings: list[str] = field(default_factory=list)


class TvClient(Protocol):
    """What the display service needs from a TV. `FakeTv` implements it for tests."""

    def info(self) -> TvInfo: ...

    def items(self, category: str | None = MY_PICTURES) -> list[ArtItem]: ...

    def upload(self, data: bytes, file_type: FileType, image_date: str | None = None) -> str: ...

    def delete(self, content_ids: list[str]) -> None: ...

    def select(self, content_id: str) -> None: ...

    def stop_slideshow(self) -> None: ...

    def start_slideshow(self, minutes: int, ordered: bool = True) -> None: ...

    def close(self) -> None: ...


def _link_error(exc: Exception) -> TvError:
    """Map whatever the library raised onto our cases, on either channel."""
    name = type(exc).__name__
    text = str(exc)
    lowered = text.lower()
    if "unauthorized" in lowered or ("token" in lowered and "fail" in lowered):
        return TvUnauthorizedError(text)
    if name in {"ResponseError", "MessageError"} or "error number" in text:
        return TvRejectedError(text)
    return TvUnreachableError(f"{name}: {text}" if text else name)


def _art_is_silent(exc: Exception) -> bool:
    """The websocket opened (the TV is there), then the art app did not answer.

    The library says so in two ways, both a `ConnectionFailure`: the frame it got while waiting
    for `ms.channel.ready` (in practice `ms.channel.clientConnect`: another connection of ours
    joining the channel — what a push answered on 2026-10-02 with the TV out of art mode), or
    `Websocket Time out` when nothing came at all. A TV that is off the network never gets that
    far: it fails in the socket, with another exception.
    """
    if type(exc).__name__ != "ConnectionFailure":
        return False
    frame = exc.args[0] if exc.args else None
    if isinstance(frame, dict):
        return str(frame.get("event", "")).startswith("ms.channel.")
    return str(frame).startswith("Websocket Time out")


def _art_error(exc: Exception) -> TvError:
    """`_link_error` for the art channel, where a silent art app is a case of its own.

    Its message is ours: the library's is the raw frame, which carries the pairing token.
    """
    if _art_is_silent(exc):
        return TvArtUnavailableError(
            "the TV answered but its art mode did not: turn it on, or switch it to art mode"
        )
    return _link_error(exc)


class SamsungTvClient:
    """`TvClient` over `samsungtvws` (sync API — our jobs are threads, not a loop).

    One instance holds one websocket: build it for a push, close it after. Nothing here retries;
    the job lane does that, so a failure is visible in `/activity` rather than hidden in a loop.
    """

    def __init__(self, host: str, token: str | None = None, *, timeout: float = 30.0) -> None:
        self.host = host
        self.token = token
        self._timeout = timeout
        self._tv: Any | None = None
        self._art: Any | None = None

    # ---- plumbing ----------------------------------------------------------------------------
    def _connect(self) -> Any:
        if self._art is not None:
            return self._art
        try:
            from samsungtvws import SamsungTVWS
        except ImportError as exc:  # pragma: no cover - the dependency is declared
            raise TvError("samsungtvws is not installed") from exc
        self._tv = SamsungTVWS(
            host=self.host,
            port=8002,
            token=self.token,
            timeout=self._timeout,
            name="the_frame_v2",
        )
        self._art = self._tv.art()
        return self._art

    def _rest(self) -> dict[str, Any]:
        import json
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(f"http://{self.host}:8001/api/v2/", timeout=5) as response:
                payload: dict[str, Any] = json.loads(response.read().decode())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TvUnreachableError(str(exc)) from exc
        return payload

    def close(self) -> None:
        for handle in (self._art, self._tv):
            if handle is None:
                continue
            try:
                handle.close()
            except Exception:
                log.debug("closing the TV connection failed", exc_info=True)
        self._art = None
        self._tv = None

    def __enter__(self) -> SamsungTvClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- reads -------------------------------------------------------------------------------
    def info(self) -> TvInfo:
        device = self._rest().get("device", {})
        art = self._connect()
        warnings: list[str] = []
        try:
            api_version = str(art.get_api_version())
            art_mode = str(art.get_artmode()).lower() in {"on", "true", "1"}
            items = self.items(None)
            status = art.get_slideshow_status() or {}
            current = art.get_current() or {}
        except Exception as exc:
            raise _art_error(exc) from exc
        value = str(status.get("value", "off"))
        return TvInfo(
            model=str(device.get("modelName") or "") or None,
            model_code=str(device.get("model") or "") or None,
            name=str(device.get("name") or "") or None,
            mac=normalize_mac(device.get("wifiMac")),
            api_version=api_version,
            frame_support=str(device.get("FrameTVSupport", "")).lower() == "true",
            token_auth=str(device.get("TokenAuthSupport", "")).lower() == "true",
            art_mode=art_mode,
            my_pictures=sum(1 for i in items if i.category_id == MY_PICTURES),
            store_items=sum(1 for i in items if i.category_id == STORE),
            slideshow_minutes=int(value) if value.isdigit() else None,
            slideshow_ordered=str(status.get("type", "")) == "slideshow",
            current_content_id=str(current.get("content_id") or "") or None,
            warnings=warnings,
        )

    def items(self, category: str | None = MY_PICTURES) -> list[ArtItem]:
        art = self._connect()
        try:
            raw = art.available(None) or []
        except Exception as exc:
            raise _art_error(exc) from exc
        items = [
            ArtItem(
                content_id=str(row.get("content_id")),
                category_id=str(row.get("category_id") or ""),
                width=_int_or_none(row.get("width")),
                height=_int_or_none(row.get("height")),
                image_date=str(row.get("image_date") or "") or None,
                matte_id=str(row.get("matte_id") or "") or None,
            )
            for row in raw
            if row.get("content_id")
        ]
        if category is None:
            return items
        return [i for i in items if i.category_id == category]

    # ---- writes ------------------------------------------------------------------------------
    def upload(self, data: bytes, file_type: FileType, image_date: str | None = None) -> str:
        art = self._connect()
        try:
            content_id = art.upload(
                data,
                matte="none",
                portrait_matte="none",
                file_type=file_type,
                date=image_date,
            )
        except Exception as exc:
            raise _art_error(exc) from exc
        if not content_id:
            raise TvRejectedError("the TV accepted the upload but returned no content id")
        return str(content_id)

    def delete(self, content_ids: list[str]) -> None:
        if not content_ids:
            return
        art = self._connect()
        try:
            art.delete_list(list(content_ids))
        except Exception as exc:
            raise _art_error(exc) from exc

    def select(self, content_id: str) -> None:
        art = self._connect()
        try:
            art.select_image(content_id, show=True)
        except Exception as exc:
            raise _art_error(exc) from exc

    def stop_slideshow(self) -> None:
        art = self._connect()
        try:
            art.set_slideshow_status(duration=0, type=True, category=2)
        except Exception as exc:
            raise _art_error(exc) from exc

    def start_slideshow(self, minutes: int, ordered: bool = True) -> None:
        if minutes not in SLIDESHOW_MINUTES:
            raise TvRejectedError(
                f"{minutes} min is not an interval this TV accepts {SLIDESHOW_MINUTES}"
            )
        art = self._connect()
        try:
            art.set_slideshow_status(duration=minutes, type=not ordered, category=2)
        except Exception as exc:
            raise _art_error(exc) from exc


def pair_with_tv(host: str, timeout: float = 45.0) -> str:
    """Open the **remote-control** channel to get a token, which is what raises the TV's dialog.

    The art channel needs the token but never asks for it (fork issue #15), and the TV can only
    draw the dialog while it is properly on — in art mode nothing appears (measured 2026-09-25).
    """
    try:
        from samsungtvws import SamsungTVWS
    except ImportError as exc:  # pragma: no cover - the dependency is declared
        raise TvError("samsungtvws is not installed") from exc

    tv = SamsungTVWS(host=host, port=8002, timeout=timeout, name="the_frame_v2")
    try:
        tv.open()
    except Exception as exc:
        raise _link_error(exc) from exc
    finally:
        try:
            tv.close()
        except Exception:
            log.debug("closing the pairing connection failed", exc_info=True)
    token = str(tv.token or "")
    if not token:
        raise TvUnauthorizedError("the TV did not hand over a token — was the prompt accepted?")
    return token


def normalize_mac(value: Any) -> str | None:
    """`04:CB:…`, `04-cb-…` and `04cb…` are one TV: lower case, colon separated, or None."""
    digits = "".join(ch for ch in str(value or "").lower() if ch in "0123456789abcdef")
    if len(digits) != 12:
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except TypeError, ValueError:
        return None
