"""How the library's exceptions become our problem codes (`tv/client.py`).

No TV here: the exceptions are the ones `samsungtvws` raises, built by hand — the first is the
frame a real push answered when the TV was not in art mode.
"""

from __future__ import annotations

from samsungtvws import exceptions

from the_frame_v2.tv.client import (
    TvArtUnavailableError,
    TvRejectedError,
    TvUnauthorizedError,
    TvUnreachableError,
    _art_error,
    _link_error,
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


def test_pairing_never_blames_art_mode() -> None:
    # The remote-control channel has no art app: an unexpected frame there (the prompt timing
    # out) says nothing about art mode.
    timed_out = exceptions.ConnectionFailure({"event": "ms.channel.timeOut"})
    assert isinstance(_link_error(timed_out), TvUnreachableError)
