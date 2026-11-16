"""How the library's exceptions become our problem codes (`tv/client.py`).

No TV here: the exceptions are the ones `samsungtvws` raises, built by hand — the first is the
frame a real push answered when the TV was not in art mode.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import websocket
from samsungtvws import exceptions

from frame_it.tv.client import (
    ArtNotReadyError,
    TvArtUnavailableError,
    TvRejectedError,
    TvUnauthorizedError,
    TvUnreachableError,
    _art_error,
    _link_error,
    art_channel_class,
)

CLIENT_CONNECT = {
    "data": {
        "attributes": {"name": "dGhlX2ZyYW1lX3Yy", "token": "12345678"},
        "connectTime": 1790947638522,
        "deviceName": "dGhlX2ZyYW1lX3Yy",
        "id": "728e56c8-721f-4e97-9472-306fb6dd7e4",
        "isHost": False,
    },
    "event": "ms.channel.clientConnect",
}


def test_a_frame_instead_of_ready_means_the_art_app_is_silent() -> None:
    error = _art_error(exceptions.ConnectionFailure(CLIENT_CONNECT))
    assert isinstance(error, TvArtUnavailableError)
    assert error.code == "tv_art_unavailable"
    # The library's message is the frame itself, pairing token included: ours must not be.
    assert "12345678" not in str(error)


def test_a_websocket_timeout_means_the_art_app_is_silent() -> None:
    error = _art_error(exceptions.ConnectionFailure("Websocket Time out: timed out"))
    assert isinstance(error, TvArtUnavailableError)


def test_a_tv_off_the_network_is_still_unreachable() -> None:
    assert isinstance(_art_error(TimeoutError("timed out")), TvUnreachableError)
    assert isinstance(_art_error(ConnectionRefusedError(111, "refused")), TvUnreachableError)
    # A data socket closing mid-transfer is a lost TV, not a silent art app.
    closed = exceptions.ConnectionFailure({"reason": "socket closed"})
    assert isinstance(_art_error(closed), TvUnreachableError)


def test_the_other_cases_keep_their_codes() -> None:
    unauthorized = exceptions.UnauthorizedError({"event": "ms.channel.unauthorized"})
    assert isinstance(_art_error(unauthorized), TvUnauthorizedError)
    refused = exceptions.ResponseError("`set_slideshow_status` request failed with error number -7")
    assert isinstance(_art_error(refused), TvRejectedError)


class FakeSocket:
    """What `websocket.create_connection` returns, replaying frames; `None` = a recv timeout."""

    def __init__(self, frames: list[dict[str, Any] | None]) -> None:
        self.frames = list(frames)
        self.closed = False
        self.timeouts: list[float | None] = []

    def recv(self) -> str:
        if not self.frames or self.frames[0] is None:
            if self.frames:
                self.frames.pop(0)
            raise websocket.WebSocketTimeoutException("timed out")
        return json.dumps(self.frames.pop(0))

    def settimeout(self, value: float | None) -> None:
        self.timeouts.append(value)

    def close(self) -> None:
        self.closed = True


CONNECT = {"event": "ms.channel.connect", "data": {}}
READY = {"event": "ms.channel.ready", "data": {}}


def _channel(monkeypatch: pytest.MonkeyPatch, frames: list[dict[str, Any] | None]) -> Any:
    socket = FakeSocket(frames)
    monkeypatch.setattr(
        "samsungtvws.connection.websocket.create_connection", lambda *a, **k: socket
    )
    channel = art_channel_class()("192.0.2.1", token="12345678", port=8002, timeout=5)
    return channel, socket


def test_the_art_channel_lets_client_announcements_go_by(monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure in the job history: `clientConnect` before `ready` is a race, not a TV off."""
    channel, socket = _channel(monkeypatch, [CONNECT, CLIENT_CONNECT, READY])
    assert channel.open() is socket
    assert not socket.closed
    assert socket.timeouts[-1] == 5  # the request timeout is back once ready


def test_an_art_app_that_never_answers_is_art_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    channel, socket = _channel(monkeypatch, [CONNECT, CLIENT_CONNECT, None])
    with pytest.raises(ArtNotReadyError) as caught:
        channel.open()
    assert caught.value.events == ["ms.channel.clientConnect"]
    assert socket.closed
    error = _art_error(caught.value)
    assert isinstance(error, TvArtUnavailableError)
    assert "ms.channel.clientConnect" in str(error)
    assert "12345678" not in str(error)


def test_the_wait_for_ready_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    channel, socket = _channel(monkeypatch, [CONNECT, *[CLIENT_CONNECT] * 50])
    channel.ready_seconds = 0.0
    with pytest.raises(ArtNotReadyError):
        channel.open()
    assert socket.closed


def test_unauthorized_while_waiting_for_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    channel, _ = _channel(monkeypatch, [CONNECT, {"event": "ms.channel.unauthorized"}])
    with pytest.raises(exceptions.UnauthorizedError) as caught:
        channel.open()
    assert isinstance(_art_error(caught.value), TvUnauthorizedError)


def test_pairing_never_blames_art_mode() -> None:
    # The remote-control channel has no art app: an unexpected frame there (the prompt timing
    # out) says nothing about art mode.
    timed_out = exceptions.ConnectionFailure({"event": "ms.channel.timeOut"})
    assert isinstance(_link_error(timed_out), TvUnreachableError)
