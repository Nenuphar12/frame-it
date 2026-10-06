"""Runs the LocalSend receiver (TLS HTTP server + multicast discovery) inside the app lifespan."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from collections.abc import Iterator

import uvicorn

from frame_it.context import AppContext
from frame_it.localsend.app import create_localsend_app, own_info
from frame_it.localsend.discovery import Discovery, register_over_http
from frame_it.localsend.identity import Identity, ensure_identity

log = logging.getLogger(__name__)
PORT_FALLBACKS = 10


class _EmbeddedServer(uvicorn.Server):
    """Leaves signal handling to the main server."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


class LocalSendRunner:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.identity: Identity | None = None
        self.port = ctx.settings.localsend_port
        self.running = False
        self.discovery_running = False
        self.error: str | None = None
        self._server: _EmbeddedServer | None = None
        self._task: asyncio.Task[None] | None = None
        self._discovery: Discovery | None = None

    async def start(self) -> None:
        settings = self.ctx.settings
        self.identity = await asyncio.to_thread(ensure_identity, settings.localsend_dir)
        sock = self._bind()
        if sock is None:
            return
        self.port = sock.getsockname()[1]
        if self.port != settings.localsend_port:
            log.warning(
                "LocalSend port %d is in use (LocalSend app on this computer?): using %d instead",
                settings.localsend_port,
                self.port,
            )
        config = uvicorn.Config(
            create_localsend_app(self.ctx, self.identity, self.port),
            ssl_certfile=str(self.identity.cert_path),
            ssl_keyfile=str(self.identity.key_path),
            lifespan="off",
            proxy_headers=False,
            access_log=False,
            log_level="warning",
        )
        self._server = _EmbeddedServer(config)
        self._task = asyncio.create_task(self._server.serve(sockets=[sock]))
        for _ in range(100):  # wait until it accepts connections (startup is quick)
            if self._server.started or self._task.done():
                break
            await asyncio.sleep(0.05)
        if not self._server.started:
            self.error = "LocalSend server failed to start"
            log.error(self.error)
            return
        self.running = True
        log.info(
            "LocalSend receiver '%s' on port %d (fingerprint %s…)",
            settings.effective_localsend_alias,
            self.port,
            self.identity.fingerprint[:12],
        )
        if settings.localsend_discovery:
            await self._start_discovery()

    def _bind(self) -> socket.socket | None:
        """Bind the TLS port. With discovery (which announces the real port), fall back to the next
        free ports when the configured one is taken (e.g. by a LocalSend app on this computer)."""
        settings = self.ctx.settings
        attempts = PORT_FALLBACKS if settings.localsend_discovery else 1
        error: OSError | None = None
        for port in range(settings.localsend_port, settings.localsend_port + attempts):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((settings.host, port))
            except OSError as exc:
                sock.close()
                error = error or exc
                continue
            return sock
        detail = error.strerror if error and error.strerror else str(error)
        self.error = f"port {settings.localsend_port} unavailable: {detail}"
        log.error("LocalSend receiver disabled: %s (set FRAME_IT_LOCALSEND_PORT)", self.error)
        return None

    async def _start_discovery(self) -> None:
        assert self.identity is not None
        settings = self.ctx.settings
        discovery = Discovery(
            own_info(self.ctx, self.identity, self.port),
            register_over_http(self.identity),
            port=settings.localsend_multicast_port,
            interface_ip=settings.lan_ip,
        )
        try:
            await discovery.start()
        except OSError as exc:
            log.warning("LocalSend discovery disabled (%s): add the server by IP in LocalSend", exc)
            return
        self._discovery = discovery
        self.discovery_running = True

    async def stop(self) -> None:
        if self._discovery is not None:
            self._discovery.close()
        if self._server is not None and self._task is not None:
            self._server.should_exit = True
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._task, timeout=5)
        self.running = self.discovery_running = False
