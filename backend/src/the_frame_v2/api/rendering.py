"""Templates (read-only until Phase 7), bundled assets and region renders."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from the_frame_v2.api.deps import Admin, Ctx, DbSession
from the_frame_v2.api.schemas import FontOut, FrameStyleOut, LayoutOut, RegionRenderIn, TextureOut
from the_frame_v2.db.session import Database
from the_frame_v2.domain.geometry import Rect
from the_frame_v2.errors import not_found
from the_frame_v2.imaging.assets import catalog
from the_frame_v2.services import render, templates

router = APIRouter(tags=["templates"])
_ASSET_CACHE = {"Cache-Control": "private, max-age=86400"}


@router.get("/frame-styles")
def list_frame_styles(_: Admin, session: DbSession) -> list[FrameStyleOut]:
    return [FrameStyleOut.model_validate(s) for s in templates.list_styles(session)]


@router.get("/layouts")
def list_layouts(_: Admin, session: DbSession) -> list[LayoutOut]:
    return [LayoutOut.model_validate(layout) for layout in templates.list_layouts(session)]


@router.get("/fonts")
def list_fonts(_: Admin) -> list[FontOut]:
    return [
        FontOut(id=f.id, name=f.name, category=f.category, weights=list(f.weights))
        for f in catalog().fonts.values()
    ]


@router.get("/fonts/{font_id}/{weight}.ttf", response_class=FileResponse)
def font_file(
    font_id: Annotated[str, Path(pattern=r"^[a-z0-9-]{1,64}$")], weight: int, _: Admin
) -> FileResponse:
    """Font file for the editor preview (`@font-face`), identical to the renderer's."""
    font = catalog().fonts.get(font_id)
    if font is None or weight not in font.weights:
        raise not_found("Font")
    return FileResponse(font.path(weight), media_type="font/ttf", headers=_ASSET_CACHE)


@router.get("/textures")
def list_textures(_: Admin) -> list[TextureOut]:
    return [TextureOut(id=t.id, name=t.name, size=t.size) for t in catalog().textures.values()]


@router.get("/textures/{texture_id}.png", response_class=FileResponse)
def texture_file(
    texture_id: Annotated[str, Path(pattern=r"^[a-z0-9-]{1,64}$")], _: Admin
) -> FileResponse:
    """Grayscale tile for the editor preview (same formula as the renderer, §8.2)."""
    texture = catalog().textures.get(texture_id)
    if texture is None:
        raise not_found("Texture")
    return FileResponse(texture.path, media_type="image/png", headers=_ASSET_CACHE)


@router.post(
    "/render/region",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "PNG of the region"}},
)
async def render_region(body: RegionRenderIn, _: Admin, ctx: Ctx) -> Response:
    """Render a region (≤ 1024², TV px) of a possibly unsaved document (loupe, §11.4)."""
    rect = Rect(body.rect.x, body.rect.y, body.rect.w, body.rect.h)

    def run(db: Database) -> bytes:
        with db.session() as session:
            return render.region_png(ctx, session, body.document, rect)

    data = await run_in_threadpool(run, ctx.db)
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})
