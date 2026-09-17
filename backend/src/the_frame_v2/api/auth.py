from __future__ import annotations

from fastapi import APIRouter, Request, Response

from the_frame_v2.api.deps import Ctx, DbSession
from the_frame_v2.api.schemas import CodeRedeemIn, DeviceOut
from the_frame_v2.auth.principal import COOKIE_NAME
from the_frame_v2.errors import ProblemError
from the_frame_v2.services import devices

router = APIRouter(prefix="/auth", tags=["auth"])
_COOKIE_MAX_AGE = 10 * 365 * 24 * 3600


def _check_rate(ctx: Ctx, request: Request) -> None:
    key = request.client.host if request.client else "unknown"
    if not ctx.auth_limiter.hit(key):
        raise ProblemError(429, "rate_limited", "Too many attempts", headers={"Retry-After": "60"})


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )


def _default_name(request: Request, name: str) -> str:
    if name.strip():
        return name
    ua = request.headers.get("user-agent", "")
    if "Android" in ua:
        return "Android device"
    return "Browser"


@router.post("/setup")
def redeem_setup_code(
    body: CodeRedeemIn, request: Request, response: Response, ctx: Ctx, session: DbSession
) -> DeviceOut:
    """Register this browser as an admin device using the setup code printed at startup."""
    _check_rate(ctx, request)
    registered = devices.redeem_setup_code(
        session,
        body.code,
        _default_name(request, body.device_name),
        request.headers.get("user-agent", ""),
    )
    _set_cookie(request, response, registered.token)
    return DeviceOut.model_validate(registered.device)


@router.post("/pair")
def redeem_pairing_code(
    body: CodeRedeemIn, request: Request, response: Response, ctx: Ctx, session: DbSession
) -> DeviceOut:
    """Register this browser with the role attached to a pairing code (QR flow)."""
    _check_rate(ctx, request)
    registered = devices.redeem_pairing_code(
        session,
        body.code,
        _default_name(request, body.device_name),
        request.headers.get("user-agent", ""),
    )
    _set_cookie(request, response, registered.token)
    return DeviceOut.model_validate(registered.device)


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    """Forget the device cookie in this browser (the device stays registered until revoked)."""
    response.delete_cookie(COOKIE_NAME, path="/")
