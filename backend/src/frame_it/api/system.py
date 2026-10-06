from __future__ import annotations

from fastapi import APIRouter

from frame_it import __version__
from frame_it.api.deps import Ctx, CurrentPrincipal
from frame_it.api.schemas import Capabilities, Me, SystemInfo
from frame_it.imaging import capabilities
from frame_it.services import devices
from frame_it.services.uploads import MAX_CHUNK_BYTES

router = APIRouter(prefix="/system", tags=["system"])
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
assert UPLOAD_CHUNK_BYTES <= MAX_CHUNK_BYTES


@router.get("/info")
def system_info(ctx: Ctx) -> SystemInfo:
    caps = capabilities.detect()
    return SystemInfo(
        name="Frame It",
        version=__version__,
        public_url=ctx.settings.effective_public_url,
        capabilities=Capabilities(
            libvips_version=caps.libvips_version,
            avif=caps.avif,
            ultra_hdr=caps.ultra_hdr,
            color_management=caps.color_management,
        ),
        max_upload_bytes=ctx.settings.max_upload_bytes,
        upload_chunk_bytes=UPLOAD_CHUNK_BYTES,
    )


@router.get("/me")
def me(ctx: Ctx, principal: CurrentPrincipal) -> Me:
    setup_required = False
    if not principal.is_authenticated:
        with ctx.db.session() as s:
            setup_required = not devices.has_admin_device(s)
    return Me(
        authenticated=principal.is_authenticated,
        role=principal.role,
        via=principal.via,
        device_id=principal.device_id,
        device_name=principal.device_name,
        setup_required=setup_required,
    )
