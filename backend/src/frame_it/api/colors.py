"""Colour tools of the editor: photo palettes, curated presets and saved swatches (§11.3)."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from frame_it.api.deps import Admin, Ctx, DbSession
from frame_it.api.schemas import (
    ColorPresetOut,
    PaletteEntryOut,
    SwatchCreateIn,
    SwatchOut,
    SwatchReorderIn,
    SwatchUpdateIn,
)
from frame_it.db.session import Database
from frame_it.services import colors

router = APIRouter(tags=["colors"])


@router.get("/photos/{photo_id}/palette")
async def photo_palette(photo_id: str, _: Admin, ctx: Ctx) -> list[PaletteEntryOut]:
    """Mat colours suggested from the photo (dominant, muted and complementary; cached)."""

    def run(db: Database) -> list[PaletteEntryOut]:
        with db.session() as session:
            entries = colors.photo_palette(ctx, session, photo_id)
        return [PaletteEntryOut.model_validate(e) for e in entries]

    return await run_in_threadpool(run, ctx.db)


@router.get("/presets/colors")
def color_presets(_: Admin) -> list[ColorPresetOut]:
    return [ColorPresetOut(name=name, color=color) for name, color in colors.CURATED]


@router.get("/swatches")
def list_swatches(_: Admin, session: DbSession) -> list[SwatchOut]:
    return [SwatchOut.model_validate(s) for s in colors.list_swatches(session)]


@router.post("/swatches", status_code=201)
def create_swatch(body: SwatchCreateIn, _: Admin, session: DbSession) -> SwatchOut:
    """Save a colour (an existing swatch with the same colour is returned unchanged)."""
    return SwatchOut.model_validate(colors.create_swatch(session, body.color, body.name))


@router.patch("/swatches/{swatch_id}")
def update_swatch(swatch_id: str, body: SwatchUpdateIn, _: Admin, session: DbSession) -> SwatchOut:
    return SwatchOut.model_validate(colors.update_swatch(session, swatch_id, name=body.name))


@router.delete("/swatches/{swatch_id}", status_code=204)
def delete_swatch(swatch_id: str, _: Admin, session: DbSession) -> None:
    colors.delete_swatch(session, swatch_id)


@router.post("/swatches/reorder")
def reorder_swatches(body: SwatchReorderIn, _: Admin, session: DbSession) -> list[SwatchOut]:
    return [SwatchOut.model_validate(s) for s in colors.reorder_swatches(session, body.ids)]
