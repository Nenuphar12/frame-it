"""Editor assets (fonts, textures) and region renders. Templates live in `api/templates.py`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from frame_it.api.deps import Admin, Ctx
from frame_it.api.schemas import (
    FontMetricsOut,
    FontOut,
    RegionRenderIn,
    TextureOut,
)
from frame_it.db.session import Database
from frame_it.domain.geometry import Rect
from frame_it.errors import not_found
from frame_it.imaging.assets import catalog
from frame_it.services import render

router = APIRouter(tags=["assets"])
_ASSET_CACHE = {"Cache-Control": "private, max-age=86400"}


@router.get("/fonts")
def list_fonts(_: Admin) -> list[FontOut]:
    return [
        FontOut(
            id=f.id,
            name=f.name,
            category=f.category,
            weights=list(f.weights),
            metrics=[
                FontMetricsOut(
                    weight=weight,
                    units_per_em=m.units_per_em,
                    ascender=m.ascender,
                    descender=m.descender,
                )
                for weight, m in sorted(f.metrics.items())
            ],
        )
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
