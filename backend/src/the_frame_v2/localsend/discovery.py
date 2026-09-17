"""LocalSend multicast discovery (UDP 224.0.0.167).

- At startup the server announces itself (burst of three messages).
- When a device announces itself (`announce: true`), the server answers with an HTTP register
  request to that device — presenting its certificate as client certificate, because recent
  LocalSend apps only trust registrations whose fingerprint matches the TLS client certificate —
  and falls back to a multicast answer (`announce: false`).
"""

from __future__ import annotations

import asyncio
import contextlib
import http.client
import json
import logging
import socket
import ssl
import struct
from collections.abc import Callable, Coroutine
from typing import Any, cast

from pydantic import ValidationError

from the_frame_v2.localsend.dto import Announcement, DeviceInfo
from the_frame_v2.localsend.identity import Identity

log = logging.getLogger(__name__)

MULTICAST_GROUP = "224.0.0.167"
ANNOUNCE_DELAYS = (0.1, 0.5, 2.0)
REGISTER_TIMEOUT = 2.0

Register = Callable[[str, int, str, dict[str, object]], bool]


def register_over_http(identity: Identity) -> Register:
    """Blocking `POST /register` to a peer; True when it answered 2xx."""

    def register(host: str, port: int, protocol: str, body: dict[str, object]) -> bool:
        payload = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        conn: http.client.HTTPConnection
        if protocol == "https":
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE  # self-signed peers; the peer pins us, not we them
            context.load_cert_chain(identity.cert_path, identity.key_path)
            conn = http.client.HTTPSConnection(
                host, port, timeout=REGISTER_TIMEOUT, context=context
            )
        else:
            conn = http.client.HTTPConnection(host, port, timeout=REGISTER_TIMEOUT)
        try:
            conn.request("POST", "/api/localsend/v2/register", payload, headers)
            return 200 <= conn.getresponse().status < 300
        except OSError, http.client.HTTPException:
            return False
        finally:
            conn.close()

    return register


class Discovery(asyncio.DatagramProtocol):
    def __init__(
        self,
        info: DeviceInfo,
        register: Register,
        *,
        port: int,
        interface_ip: str | None,
    ) -> None:
        self.info = info
        self.register = register
        self.port = port
        self.interface_ip = interface_ip
        self.transport: asyncio.DatagramTransport | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    # ---- lifecycle -------------------------------------------------------------------------------
    async def start(self) -> None:
        sock = self._socket()
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: self, sock=sock)
        self._spawn(self.announce())

    def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self.transport is not None:
            self.transport.close()

    def _socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):  # coexist with a LocalSend app on the same machine
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        try:
            sock.bind(("", self.port))
            group = socket.inet_aton(MULTICAST_GROUP)
            joined = False
            for iface in dict.fromkeys([self.interface_ip, "0.0.0.0"]):  # noqa: S104
                if iface is None:
                    continue
                with contextlib.suppress(OSError):
                    mreq = group + socket.inet_aton(iface)
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                    joined = True
            if not joined:
                raise OSError("could not join the LocalSend multicast group")
            if self.interface_ip:
                with contextlib.suppress(OSError):
                    sock.setsockopt(
                        socket.IPPROTO_IP,
                        socket.IP_MULTICAST_IF,
                        socket.inet_aton(self.interface_ip),
                    )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack("b", 1))
            sock.setblocking(False)
        except OSError:
            sock.close()
            raise
        return sock

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- sending ---------------------------------------------------------------------------------
    def message(self, *, announce: bool) -> bytes:
        body = {**self.info.wire(), "announce": announce, "announcement": announce}
        return json.dumps(body).encode()

    def _send(self, data: bytes) -> None:
        if self.transport is not None and not self.transport.is_closing():
            with contextlib.suppress(OSError):
                self.transport.sendto(data, (MULTICAST_GROUP, self.port))

    async def announce(self) -> None:
        previous = 0.0
        for delay in ANNOUNCE_DELAYS:
            await asyncio.sleep(delay - previous)
            previous = delay
            self._send(self.message(announce=True))

    # ---- receiving -------------------------------------------------------------------------------
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        # uvloop's UDP transport does not subclass asyncio.DatagramTransport: no isinstance check.
        self.transport = cast(asyncio.DatagramTransport, transport)

    def datagram_received(self, data: bytes, addr: tuple[str | object, int]) -> None:
        peer = self.parse(data)
        if peer is None or not (peer.announce or peer.announcement):
            return
        host = str(addr[0])
        log.debug("LocalSend announcement from %s (%s)", peer.alias, host)
        self._spawn(self._answer(host, peer))

    def parse(self, data: bytes) -> Announcement | None:
        try:
            peer = Announcement.model_validate_json(data)
        except ValidationError:
            return None
        return None if peer.fingerprint == self.info.fingerprint else peer

    async def _answer(self, host: str, peer: Announcement) -> None:
        body = self.info.wire()
        registered = await asyncio.to_thread(self.register, host, peer.port, peer.protocol, body)
        if not registered:
            self._send(self.message(announce=False))
