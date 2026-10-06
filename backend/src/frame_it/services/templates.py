"""Frame styles and layouts: built-in presets, CRUD, template files and artwork defaults.

Spec: docs/templates.md (Phase 8). Presets live in `assets/presets/*.json` with stable ids;
seeding inserts missing ones and updates changed ones (revision + 1). Templates are **copied on
apply**: an artwork never changes because a template changed — only a push update does that
(`services/artworks.push_template_update`, which is where the artwork-writing half lives).

A layout is a recipe and its parameters since Phase 8, so `slot_count` is the recipe's cell count
rather than a number of hand-placed rects.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from frame_it.db.models import Artwork, FrameStyle, Layout, Setting
from frame_it.domain.composition import Recipe
from frame_it.domain.document import Composition
from frame_it.domain.templates import FrameStyleDocument, LayoutDocument
from frame_it.errors import ProblemError
from frame_it.ids import new_id, utcnow
from frame_it.services import recipes

PRESETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "presets"
DEFAULT_STYLE_ID = "builtin-style-gallery-recessed"
DEFAULTS_SETTING = "artwork_defaults"
TemplateKind = Literal["frame_style", "layout"]
FILE_KIND: dict[TemplateKind, str] = {"frame_style": "tfstyle", "layout": "tflayout"}
FILE_VERSION = 1
MAX_NAME = 128


def _presets(name: str, key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = json.loads((PRESETS_DIR / name).read_text())[key]
    return items


def _slot_count(document: LayoutDocument) -> int:
    recipe = recipes.find(document.recipe)
    return recipe.count if recipe else 1


def _same_template(
    model: type[FrameStyleDocument] | type[LayoutDocument],
    stored: Mapping[str, Any],
    document: Mapping[str, Any],
) -> bool:
    """`stored` says what `document` says, read by today's schema.

    A template stored before an optional field existed lacks that key, yet it describes the same
    look: re-serialising it must not count as an edit. Comparing the raw JSON did, so every schema
    addition bumped every built-in's `revision` and flagged each artwork made from one as
    outdated — with a push update that would have changed nothing.
    """
    try:
        return bool(model.model_validate(dict(stored)).model_dump(mode="json") == document)
    except ValidationError:
        return False


def seed_builtins(session: Session) -> None:
    for item in _presets("frame_styles.json", "styles"):
        document = FrameStyleDocument.model_validate(item["document"]).model_dump(mode="json")
        style = session.get(FrameStyle, item["id"])
        if style is None:
            session.add(
                FrameStyle(id=item["id"], name=item["name"], document=document, builtin=True)
            )
        elif style.name != item["name"] or not _same_template(
            FrameStyleDocument, style.document, document
        ):
            style.document, style.name, style.revision = document, item["name"], style.revision + 1
        elif style.document != document:
            style.document = document  # the same look, written with today's keys
    for item in _presets("layouts.json", "layouts"):
        layout_doc = LayoutDocument.model_validate(item["document"])
        document = layout_doc.model_dump(mode="json")
        layout = session.get(Layout, item["id"])
        if layout is None:
            session.add(
                Layout(
                    id=item["id"],
                    name=item["name"],
                    document=document,
                    slot_count=_slot_count(layout_doc),
                    builtin=True,
                )
            )
        elif layout.name != item["name"] or not _same_template(
            LayoutDocument, layout.document, document
        ):
            layout.document, layout.name = document, item["name"]
            layout.slot_count, layout.revision = _slot_count(layout_doc), layout.revision + 1
        elif layout.document != document:
            layout.document = document


# ---- lookups ------------------------------------------------------------------------------------
def list_styles(session: Session) -> list[FrameStyle]:
    return list(
        session.scalars(select(FrameStyle).order_by(FrameStyle.builtin.desc(), FrameStyle.name))
    )


def list_layouts(session: Session) -> list[Layout]:
    return list(
        session.scalars(
            select(Layout).order_by(Layout.slot_count, Layout.builtin.desc(), Layout.name)
        )
    )


def get_style(session: Session, style_id: str) -> tuple[FrameStyle, FrameStyleDocument]:
    style = session.get(FrameStyle, style_id)
    if style is None:
        raise ProblemError(422, "unknown_style", "Unknown frame style", style_id)
    return style, FrameStyleDocument.model_validate(style.document)


def get_layout(session: Session, layout_id: str) -> tuple[Layout, LayoutDocument]:
    layout = session.get(Layout, layout_id)
    if layout is None:
        raise ProblemError(422, "unknown_layout", "Unknown layout", layout_id)
    return layout, LayoutDocument.model_validate(layout.document)


def layout_recipe(document: LayoutDocument) -> Recipe:
    """The catalogue entry a layout is built on (its cell count is the layout's slot count)."""
    recipe = recipes.find(document.recipe)
    if recipe is None:
        raise ProblemError(422, "unknown_recipe", "Unknown composition", document.recipe)
    return recipe


# ---- CRUD ---------------------------------------------------------------------------------------
def _invalid(kind: TemplateKind, exc: ValidationError) -> ProblemError:
    first = exc.errors(include_url=False)[0]
    location = ".".join(str(part) for part in first["loc"])
    return ProblemError(
        422,
        "invalid_template",
        "Invalid template document",
        f"{location}: {first['msg']}" if location else first["msg"],
        extra={"kind": kind},
    )


def parse_style(document: Mapping[str, Any]) -> FrameStyleDocument:
    try:
        return FrameStyleDocument.model_validate(dict(document))
    except ValidationError as exc:
        raise _invalid("frame_style", exc) from exc


def parse_layout(document: Mapping[str, Any]) -> LayoutDocument:
    try:
        parsed = LayoutDocument.model_validate(dict(document))
    except ValidationError as exc:
        raise _invalid("layout", exc) from exc
    # A layout that names no catalogue entry could never be applied — nor one whose per-split
    # weights describe another recipe's divisions: every artwork it reached would be refused.
    shape = layout_recipe(parsed).spec().splits
    for index, entry in enumerate(parsed.weights):
        if entry is not None and (index >= len(shape) or len(entry) != shape[index]):
            raise ProblemError(
                422,
                "invalid_template",
                "Invalid template document",
                f"weights.{index}: does not fit the recipe's splits",
                extra={"kind": "layout"},
            )
    return parsed


def _editable(template: FrameStyle | Layout) -> None:
    if template.builtin:
        raise ProblemError(
            422, "builtin_template", "Built-in templates cannot be changed", template.name
        )


def _clean_name(name: str) -> str:
    cleaned = name.strip()[:MAX_NAME]
    if not cleaned:
        raise ProblemError(422, "invalid_name", "A template needs a name")
    return cleaned


def create_style(session: Session, name: str, document: Mapping[str, Any]) -> FrameStyle:
    style = FrameStyle(
        id=new_id(),
        name=_clean_name(name),
        document=parse_style(document).model_dump(mode="json"),
        builtin=False,
    )
    session.add(style)
    session.flush()
    return style


def create_layout(session: Session, name: str, document: Mapping[str, Any]) -> Layout:
    parsed = parse_layout(document)
    layout = Layout(
        id=new_id(),
        name=_clean_name(name),
        document=parsed.model_dump(mode="json"),
        slot_count=_slot_count(parsed),
        builtin=False,
    )
    session.add(layout)
    session.flush()
    return layout


def update_style(
    session: Session,
    style_id: str,
    *,
    name: str | None = None,
    document: Mapping[str, Any] | None = None,
) -> FrameStyle:
    """Rename or re-document a style. A changed document bumps `revision` (the outdated badge)."""
    style, _ = get_style(session, style_id)
    _editable(style)
    if name is not None:
        style.name = _clean_name(name)
    if document is not None:
        new = parse_style(document).model_dump(mode="json")
        if not _same_template(FrameStyleDocument, style.document, new):
            style.revision += 1
        style.document = new
    style.updated_at = utcnow()
    return style


def update_layout(
    session: Session,
    layout_id: str,
    *,
    name: str | None = None,
    document: Mapping[str, Any] | None = None,
) -> Layout:
    layout, _ = get_layout(session, layout_id)
    _editable(layout)
    if name is not None:
        layout.name = _clean_name(name)
    if document is not None:
        parsed = parse_layout(document)
        new = parsed.model_dump(mode="json")
        if not _same_template(LayoutDocument, layout.document, new):
            layout.revision += 1
        layout.document, layout.slot_count = new, _slot_count(parsed)
    layout.updated_at = utcnow()
    return layout


def duplicate_style(session: Session, style_id: str, name: str | None = None) -> FrameStyle:
    style, document = get_style(session, style_id)
    return create_style(session, name or f"{style.name} copy", document.model_dump(mode="json"))


def duplicate_layout(session: Session, layout_id: str, name: str | None = None) -> Layout:
    layout, document = get_layout(session, layout_id)
    return create_layout(session, name or f"{layout.name} copy", document.model_dump(mode="json"))


def delete_style(session: Session, style_id: str) -> None:
    """Delete a user style. Artworks keep their look: templates are copied on apply."""
    style, _ = get_style(session, style_id)
    _editable(style)
    session.delete(style)
    current = _defaults_value(session)
    if current.get("style_id") == style_id:
        current["style_id"] = DEFAULT_STYLE_ID
        _store_defaults(session, current)


def delete_layout(session: Session, layout_id: str) -> None:
    layout, _ = get_layout(session, layout_id)
    _editable(layout)
    session.delete(layout)


# ---- template files -----------------------------------------------------------------------------
def template_file(kind: TemplateKind, name: str, document: Mapping[str, Any]) -> dict[str, Any]:
    """A `.tfstyle.json` / `.tflayout.json` payload (docs/templates.md §6)."""
    return {
        "kind": FILE_KIND[kind],
        "version": FILE_VERSION,
        "name": name,
        "document": dict(document),
    }


def parse_template_file(kind: TemplateKind, raw: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Validate an imported template file and return its (name, document)."""
    if raw.get("kind") != FILE_KIND[kind]:
        raise ProblemError(
            422,
            "wrong_template_kind",
            "This file holds another kind of template",
            str(raw.get("kind")),
        )
    if raw.get("version") != FILE_VERSION:
        raise ProblemError(
            422,
            "unsupported_template_version",
            "Unsupported template file",
            str(raw.get("version")),
        )
    document = raw.get("document")
    if not isinstance(document, dict):
        raise ProblemError(422, "invalid_template", "The file carries no document")
    name = str(raw.get("name") or "Imported")
    return name, document


# ---- artwork defaults ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ArtworkDefaults:
    """What a new artwork starts from when the dialog asks for nothing special (§5).

    `recipe_id` and `format` are optional: `None` means *follow the photos* — the first catalogue
    entry for that many photos, `original` for one photo and `fill` above (docs/simple-editor.md
    §7). A recipe whose cell count does not match the selection is ignored the same way.
    """

    style_id: str
    recipe_id: str | None = None
    format: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"style_id": self.style_id, "recipe_id": self.recipe_id, "format": self.format}


def _defaults_value(session: Session) -> dict[str, Any]:
    row = session.get(Setting, DEFAULTS_SETTING)
    return dict(row.value) if row else {}


def _store_defaults(session: Session, value: Mapping[str, Any]) -> None:
    row = session.get(Setting, DEFAULTS_SETTING)
    if row is None:
        session.add(Setting(key=DEFAULTS_SETTING, value=dict(value)))
    else:
        row.value = dict(value)


def defaults(session: Session) -> ArtworkDefaults:
    value = _defaults_value(session)
    style_id = value.get("style_id") or DEFAULT_STYLE_ID
    if session.get(FrameStyle, style_id) is None:
        style_id = DEFAULT_STYLE_ID
    recipe_id = value.get("recipe_id")
    return ArtworkDefaults(
        style_id=style_id,
        recipe_id=recipe_id if recipe_id and recipes.find(recipe_id) else None,
        format=value.get("format"),
    )


def set_defaults(
    session: Session, style_id: str, recipe_id: str | None, composition_format: str | None
) -> ArtworkDefaults:
    """Store the default style, recipe and format for new artworks (all must be usable)."""
    get_style(session, style_id)
    if recipe_id is not None and recipes.find(recipe_id) is None:
        raise ProblemError(422, "unknown_recipe", "Unknown composition", recipe_id)
    if composition_format is not None:
        try:
            Composition(recipe="single", format=composition_format)
        except ValidationError as exc:
            raise ProblemError(
                422, "invalid_format", "Unsupported format", composition_format
            ) from exc
    value = ArtworkDefaults(style_id, recipe_id, composition_format)
    _store_defaults(session, value.as_dict())
    return value


# ---- usage --------------------------------------------------------------------------------------
def users_of(session: Session, kind: TemplateKind, template_id: str) -> list[Artwork]:
    """Artworks created from (or last given) this template, newest first."""
    column = Artwork.origin_style_id if kind == "frame_style" else Artwork.origin_layout_id
    return list(
        session.scalars(
            select(Artwork)
            .where(column == template_id, Artwork.deleted_at.is_(None))
            .order_by(Artwork.created_at.desc(), Artwork.id.desc())
        )
    )


def outdated(artwork: Artwork, kind: TemplateKind, revision: int) -> bool:
    current = (
        artwork.origin_style_revision if kind == "frame_style" else artwork.origin_layout_revision
    )
    return current is not None and current < revision
