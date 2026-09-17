from __future__ import annotations

from fastapi import APIRouter

from the_frame_v2.api.deps import Admin, Ctx, DbSession
from the_frame_v2.api.schemas import DeviceOut, DeviceUpdateIn, PairingCodeIn, PairingCodeOut
from the_frame_v2.errors import ProblemError
from the_frame_v2.services import devices

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("")
def list_devices(_: Admin, session: DbSession) -> list[DeviceOut]:
    return [DeviceOut.model_validate(d) for d in devices.list_devices(session)]


@router.post("/pairing-codes")
def create_pairing_code(
    body: PairingCodeIn, _: Admin, ctx: Ctx, session: DbSession
) -> PairingCodeOut:
    issued = devices.issue_pairing_code(session, body.role)
    return PairingCodeOut(
        code=issued.code,
        role=body.role,
        url=f"{ctx.settings.effective_public_url}/pair#code={issued.code}",
        expires_in_seconds=issued.expires_in_seconds,
    )


@router.patch("/{device_id}")
def update_device(
    device_id: str, body: DeviceUpdateIn, principal: Admin, session: DbSession
) -> DeviceOut:
    if body.role == "uploader" and principal.device_id == device_id:
        raise ProblemError(409, "cannot_demote_self", "You cannot remove your own admin role")
    device = devices.update_device(session, device_id, body.name, body.role)
    return DeviceOut.model_validate(device)


@router.delete("/{device_id}", status_code=204)
def revoke_device(device_id: str, _: Admin, session: DbSession) -> None:
    devices.revoke_device(session, device_id)
