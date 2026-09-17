"""LocalSend v2 HTTP API, served on its own TLS port (`localsend_port`).

Not part of the main API: no cookies, no Host/CSRF guard; access is decided per sender device
(services/localsend.py). Errors use the protocol status codes with a `{"message"}` body.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from the_frame_v2.context import AppContext
from the_frame_v2.db.models import LocalSendDevice
from the_frame_v2.localsend.dto import (
    PROTOCOL_VERSION,
    DeviceInfo,
    PrepareUploadRequest,
    PrepareUploadResponse,
)
from the_frame_v2.localsend.identity import Identity
from the_frame_v2.services import localsend as service
from the_frame_v2.services.localsend import LocalSendRejection

log = logging.getLogger(__name__)
PREFIX = "/api/localsend/v2"


def own_info(ctx: AppContext, identity: Identity, port: int) -> DeviceInfo:
    return DeviceInfo(
        alias=ctx.settings.effective_localsend_alias,
        version=PROTOCOL_VERSION,
        device_model="the_frame_v2",
        device_type="server",
        fingerprint=identity.fingerprint,
        port=port,
        protocol="https",
        download=False,
    )


def _peer(request: Request) -> str:
    return request.client.host if request.client else ""


def create_localsend_app(ctx: AppContext, identity: Identity, port: int) -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    hub = ctx.localsend

    @app.exception_handler(LocalSendRejection)
    async def rejection(_: Request, exc: LocalSendRejection) -> JSONResponse:
        return JSONResponse({"message": exc.message}, status_code=exc.status)

    def info_body() -> dict[str, object]:
        body = own_info(ctx, identity, port).wire()
        del body["port"], body["protocol"]
        return body

    @app.get(f"{PREFIX}/info")
    async def info() -> dict[str, object]:
        return info_body()

    @app.post(f"{PREFIX}/register")
    async def register() -> dict[str, object]:
        # Nothing to remember: senders are recorded when they actually send (prepare-upload).
        return info_body()

    @app.post(f"{PREFIX}/prepare-upload", response_model=None)
    async def prepare_upload(request: Request) -> Response | dict[str, object]:
        try:
            body = PrepareUploadRequest.model_validate_json(await request.body())
        except ValidationError as exc:
            raise LocalSendRejection(400, "Invalid body") from exc
        ip = _peer(request)
        if body.info.fingerprint == identity.fingerprint:
            raise LocalSendRejection(400, "Cannot send to itself")

        def prepare() -> tuple[LocalSendDevice, service.Selection]:
            with ctx.db.session() as s:
                device = service.touch_device(s, body.info, ip)
                selection = service.select_files(s, body.files, ctx.settings.max_upload_bytes)
                s.expunge(device)
                return device, selection

        device, selection = await run_in_threadpool(prepare)
        log.info(
            "LocalSend offer from %s (%s): %d accepted, %d duplicates, %d unsupported",
            device.alias,
            device.status,
            len(selection.accepted),
            selection.duplicates,
            selection.unsupported,
        )
        if device.status == "blocked":
            raise LocalSendRejection(403, "Rejected")
        if not selection.accepted:
            if selection.duplicates:
                return Response(status_code=204)  # everything already in the library
            raise LocalSendRejection(403, "Only JPEG, PNG and AVIF photos are accepted")
        if device.status != "approved" and not await hub.request_approval(ctx, device, selection):
            raise LocalSendRejection(403, "Rejected")
        session = hub.open_session(device.id, ip, selection.accepted)
        return PrepareUploadResponse(
            session_id=session.id, files={fid: f.token for fid, f in session.files.items()}
        ).wire()

    @app.post(f"{PREFIX}/upload")
    async def upload(request: Request) -> Response:
        params = request.query_params
        session_id, file_id, token = (params.get(k) for k in ("sessionId", "fileId", "token"))
        if not (session_id and file_id and token):
            raise LocalSendRejection(400, "Missing parameters")
        session, item = hub.claim_file(session_id, file_id, token, _peer(request))
        offer = item.offer
        upload_id, temp = service.temp_path_for(ctx)
        digest = hashlib.sha256()
        size = 0
        done = False
        try:
            with temp.open("wb") as fh:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > offer.size:
                        raise LocalSendRejection(400, "More data than announced")
                    digest.update(chunk)
                    await run_in_threadpool(fh.write, chunk)
            if size != offer.size:
                raise LocalSendRejection(400, "Incomplete file")
            sha256 = digest.hexdigest()
            if offer.sha256 and offer.sha256.lower() != sha256:
                raise LocalSendRejection(422, "Checksum mismatch")
            await run_in_threadpool(
                service.hand_off,
                ctx,
                upload_id=upload_id,
                device_id=session.device_id,
                offer=offer,
                sha256=sha256,
                size=size,
            )
            done = True
        except ClientDisconnect:
            raise LocalSendRejection(400, "Transfer interrupted") from None
        finally:
            if not done:
                temp.unlink(missing_ok=True)
            hub.release_file(session, item, done=done)
        return Response(status_code=200)

    @app.post(f"{PREFIX}/cancel")
    async def cancel(request: Request) -> Response:
        session_id = request.query_params.get("sessionId", "")
        hub.cancel(session_id, _peer(request))
        return Response(status_code=200)

    return app
