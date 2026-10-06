"""Frame styles and layouts: CRUD, "save as", usage, push update and template files.

Spec: docs/templates.md (Phase 8). Built-in templates are read-only; everything else is a normal
user row. Nothing here touches an artwork except the two push-update routes and `apply-template`
on the artworks router — templates are copied on apply (`PLAN.md` §4, rule 6).
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy.orm import Session

from frame_it.api.deps import Admin, Ctx, DbSession
from frame_it.api.schemas import (
    ArtworkDefaultsIn,
    ArtworkDefaultsOut,
    ArtworkSummaryOut,
    FrameStyleIn,
    FrameStyleOut,
    FrameStyleUpdateIn,
    LayoutIn,
    LayoutOut,
    LayoutUpdateIn,
    PushUpdateOut,
    RecipeOut,
    SaveAsTemplateIn,
    TagOut,
    TemplateApplicationOut,
    TemplateFileOut,
    TemplateImportIn,
    TemplateNameIn,
)
from frame_it.context import AppContext
from frame_it.events import Event
from frame_it.services import artworks, recipes, render, templates

router = APIRouter(tags=["templates"])


def _changed(ctx: AppContext, session: Session, kind: templates.TemplateKind, id_: str) -> None:
    session.commit()
    ctx.broker.publish(Event("entity.changed", {"entity": kind, "id": id_}, audience="all"))


def _push(
    ctx: AppContext,
    session: Session,
    kind: templates.TemplateKind,
    template_id: str,
    *,
    dry_run: bool,
) -> PushUpdateOut:
    results = artworks.push_template_update(session, kind, template_id, dry_run=dry_run)
    if not dry_run:
        session.commit()
        for result in results:
            if result.applied:
                ctx.broker.publish(
                    Event(
                        "entity.changed",
                        {"entity": "artwork", "id": result.artwork_id},
                        audience="all",
                    )
                )
                render.enqueue_render(ctx, result.artwork_id)
    return PushUpdateOut(
        dry_run=dry_run,
        applied=sum(1 for r in results if r.applied),
        skipped=sum(1 for r in results if not r.applied),
        items=[TemplateApplicationOut.model_validate(r, from_attributes=True) for r in results],
    )


# ---- frame styles -------------------------------------------------------------------------------
@router.get("/frame-styles")
def list_frame_styles(_: Admin, session: DbSession) -> list[FrameStyleOut]:
    return [FrameStyleOut.model_validate(s) for s in templates.list_styles(session)]


@router.post("/frame-styles", status_code=201)
def create_frame_style(body: FrameStyleIn, _: Admin, ctx: Ctx, session: DbSession) -> FrameStyleOut:
    style = templates.create_style(session, body.name, body.document.model_dump(mode="json"))
    _changed(ctx, session, "frame_style", style.id)
    return FrameStyleOut.model_validate(style)


@router.patch("/frame-styles/{style_id}")
def update_frame_style(
    style_id: str, body: FrameStyleUpdateIn, _: Admin, ctx: Ctx, session: DbSession
) -> FrameStyleOut:
    """Rename or re-document a style. Artworks are untouched until a push update (§5)."""
    style = templates.update_style(
        session,
        style_id,
        name=body.name,
        document=body.document.model_dump(mode="json") if body.document else None,
    )
    _changed(ctx, session, "frame_style", style.id)
    return FrameStyleOut.model_validate(style)


@router.delete("/frame-styles/{style_id}", status_code=204)
def delete_frame_style(style_id: str, _: Admin, ctx: Ctx, session: DbSession) -> None:
    templates.delete_style(session, style_id)
    _changed(ctx, session, "frame_style", style_id)


@router.post("/frame-styles/{style_id}/duplicate", status_code=201)
def duplicate_frame_style(
    style_id: str, body: TemplateNameIn, _: Admin, ctx: Ctx, session: DbSession
) -> FrameStyleOut:
    style = templates.duplicate_style(session, style_id, body.name)
    _changed(ctx, session, "frame_style", style.id)
    return FrameStyleOut.model_validate(style)


@router.post("/frame-styles/from-artwork", status_code=201)
def frame_style_from_artwork(
    body: SaveAsTemplateIn, _: Admin, ctx: Ctx, session: DbSession
) -> FrameStyleOut:
    """ "Save as style": the artwork's mat, decorations and caption typography become a template."""
    style = artworks.style_from_artwork(session, body.artwork_id, body.name)
    _changed(ctx, session, "frame_style", style.id)
    return FrameStyleOut.model_validate(style)


@router.post("/frame-styles/import", status_code=201)
def import_frame_style(
    body: TemplateImportIn, _: Admin, ctx: Ctx, session: DbSession
) -> FrameStyleOut:
    name, document = templates.parse_template_file("frame_style", body.model_dump())
    style = templates.create_style(session, name, document)
    _changed(ctx, session, "frame_style", style.id)
    return FrameStyleOut.model_validate(style)


@router.get("/frame-styles/{style_id}/export")
def export_frame_style(style_id: str, _: Admin, session: DbSession) -> TemplateFileOut:
    style, document = templates.get_style(session, style_id)
    return TemplateFileOut.model_validate(
        templates.template_file("frame_style", style.name, document.model_dump(mode="json"))
    )


@router.get("/frame-styles/{style_id}/usage")
def frame_style_usage(style_id: str, _: Admin, session: DbSession) -> list[ArtworkSummaryOut]:
    """Artworks made from this style (compare `origin_style_revision` to spot outdated ones)."""
    templates.get_style(session, style_id)
    return _usage(session, "frame_style", style_id)


@router.post("/frame-styles/{style_id}/push-update/preview")
def preview_frame_style_push(
    style_id: str, _: Admin, ctx: Ctx, session: DbSession
) -> PushUpdateOut:
    templates.get_style(session, style_id)
    return _push(ctx, session, "frame_style", style_id, dry_run=True)


@router.post("/frame-styles/{style_id}/push-update")
def push_frame_style_update(style_id: str, _: Admin, ctx: Ctx, session: DbSession) -> PushUpdateOut:
    """Re-dress every artwork made from this style, each snapshotted first (undoable, §5)."""
    templates.get_style(session, style_id)
    return _push(ctx, session, "frame_style", style_id, dry_run=False)


# ---- layouts ------------------------------------------------------------------------------------
@router.get("/layouts")
def list_layouts(_: Admin, session: DbSession) -> list[LayoutOut]:
    return [LayoutOut.model_validate(layout) for layout in templates.list_layouts(session)]


@router.post("/layouts", status_code=201)
def create_layout(body: LayoutIn, _: Admin, ctx: Ctx, session: DbSession) -> LayoutOut:
    layout = templates.create_layout(session, body.name, body.document.model_dump(mode="json"))
    _changed(ctx, session, "layout", layout.id)
    return LayoutOut.model_validate(layout)


@router.patch("/layouts/{layout_id}")
def update_layout(
    layout_id: str, body: LayoutUpdateIn, _: Admin, ctx: Ctx, session: DbSession
) -> LayoutOut:
    layout = templates.update_layout(
        session,
        layout_id,
        name=body.name,
        document=body.document.model_dump(mode="json") if body.document else None,
    )
    _changed(ctx, session, "layout", layout.id)
    return LayoutOut.model_validate(layout)


@router.delete("/layouts/{layout_id}", status_code=204)
def delete_layout(layout_id: str, _: Admin, ctx: Ctx, session: DbSession) -> None:
    templates.delete_layout(session, layout_id)
    _changed(ctx, session, "layout", layout_id)


@router.post("/layouts/{layout_id}/duplicate", status_code=201)
def duplicate_layout(
    layout_id: str, body: TemplateNameIn, _: Admin, ctx: Ctx, session: DbSession
) -> LayoutOut:
    layout = templates.duplicate_layout(session, layout_id, body.name)
    _changed(ctx, session, "layout", layout.id)
    return LayoutOut.model_validate(layout)


@router.post("/layouts/from-artwork", status_code=201)
def layout_from_artwork(
    body: SaveAsTemplateIn, _: Admin, ctx: Ctx, session: DbSession
) -> LayoutOut:
    """ "Save as layout": the artwork's recipe and parameters, not its rects (§3)."""
    layout = artworks.layout_from_artwork(session, body.artwork_id, body.name)
    _changed(ctx, session, "layout", layout.id)
    return LayoutOut.model_validate(layout)


@router.post("/layouts/import", status_code=201)
def import_layout(body: TemplateImportIn, _: Admin, ctx: Ctx, session: DbSession) -> LayoutOut:
    name, document = templates.parse_template_file("layout", body.model_dump())
    layout = templates.create_layout(session, name, document)
    _changed(ctx, session, "layout", layout.id)
    return LayoutOut.model_validate(layout)


@router.get("/layouts/{layout_id}/export")
def export_layout(layout_id: str, _: Admin, session: DbSession) -> TemplateFileOut:
    layout, document = templates.get_layout(session, layout_id)
    return TemplateFileOut.model_validate(
        templates.template_file("layout", layout.name, document.model_dump(mode="json"))
    )


@router.get("/layouts/{layout_id}/usage")
def layout_usage(layout_id: str, _: Admin, session: DbSession) -> list[ArtworkSummaryOut]:
    templates.get_layout(session, layout_id)
    return _usage(session, "layout", layout_id)


@router.post("/layouts/{layout_id}/push-update/preview")
def preview_layout_push(layout_id: str, _: Admin, ctx: Ctx, session: DbSession) -> PushUpdateOut:
    templates.get_layout(session, layout_id)
    return _push(ctx, session, "layout", layout_id, dry_run=True)


@router.post("/layouts/{layout_id}/push-update")
def push_layout_update(layout_id: str, _: Admin, ctx: Ctx, session: DbSession) -> PushUpdateOut:
    """Re-solve every artwork made from this layout that still holds its number of photos (§5)."""
    templates.get_layout(session, layout_id)
    return _push(ctx, session, "layout", layout_id, dry_run=False)


# ---- recipes & defaults -------------------------------------------------------------------------
@router.get("/recipes")
def list_recipes(_: Admin) -> list[RecipeOut]:
    """Bundled composition recipes (docs/simple-editor.md §6.4). Static: not user-editable."""
    return [RecipeOut.model_validate(r, from_attributes=True) for r in recipes.all_recipes()]


@router.get("/artwork-defaults")
def artwork_defaults(_: Admin, session: DbSession) -> ArtworkDefaultsOut:
    """Style, recipe and format used when creating artworks without an explicit choice."""
    return ArtworkDefaultsOut.model_validate(templates.defaults(session), from_attributes=True)


@router.put("/artwork-defaults")
def set_artwork_defaults(
    body: ArtworkDefaultsIn, _: Admin, session: DbSession
) -> ArtworkDefaultsOut:
    value = templates.set_defaults(session, body.style_id, body.recipe_id, body.format)
    return ArtworkDefaultsOut.model_validate(value, from_attributes=True)


def _usage(
    session: Session, kind: templates.TemplateKind, template_id: str
) -> list[ArtworkSummaryOut]:
    rows = templates.users_of(session, kind, template_id)
    tags = artworks.tags_for(session, [artwork.id for artwork in rows])
    items = []
    for artwork in rows:
        out = ArtworkSummaryOut.model_validate(artwork)
        out.tags = [TagOut.model_validate(t) for t in tags[artwork.id]]
        items.append(out)
    return items
