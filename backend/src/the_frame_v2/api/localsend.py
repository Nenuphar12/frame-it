"""Admin endpoints for the LocalSend receiver (status, pending approvals, known devices)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from the_frame_v2.api.deps import Admin, Ctx, DbSession
from the_frame_v2.api.schemas import (
    LocalSendDecisionIn,
    LocalSendDeviceOut,
    LocalSendDeviceUpdateIn,
    LocalSendRequestOut,
    LocalSendStatusOut,
)
from the_frame_v2.services import localsend

router = APIRouter(prefix="/localsend", tags=["localsend"])


@router.get("/status")
def status(_: Admin, ctx: Ctx) -> LocalSendStatusOut:
    runner = ctx.localsend_runner
    return LocalSendStatusOut(
        enabled=ctx.settings.localsend_enabled,
        running=bool(runner and runner.running),
        discovery=bool(runner and runner.discovery_running),
        alias=ctx.settings.effective_localsend_alias,
        port=runner.port if runner else ctx.settings.localsend_port,
        fingerprint=runner.identity.fingerprint if runner and runner.identity else None,
        error=runner.error if runner else None,
    )


@router.get("/requests")
def pending_requests(_: Admin, ctx: Ctx) -> list[LocalSendRequestOut]:
    return [LocalSendRequestOut.model_validate(r.public()) for r in ctx.localsend.pending()]


@router.post("/requests/{request_id}/decision", status_code=204)
async def decide(request_id: str, body: LocalSendDecisionIn, _: Admin, ctx: Ctx) -> None:
    await run_in_threadpool(ctx.localsend.decide, ctx, request_id, body.approve)


@router.get("/devices")
def list_devices(_: Admin, session: DbSession) -> list[LocalSendDeviceOut]:
    return [LocalSendDeviceOut.model_validate(d) for d in localsend.list_devices(session)]


@router.patch("/devices/{device_id}")
def update_device(
    device_id: str, body: LocalSendDeviceUpdateIn, _: Admin, session: DbSession
) -> LocalSendDeviceOut:
    device = localsend.set_device_status(session, device_id, body.status)
    return LocalSendDeviceOut.model_validate(device)


@router.delete("/devices/{device_id}", status_code=204)
def forget_device(device_id: str, _: Admin, session: DbSession) -> None:
    localsend.forget_device(session, device_id)
