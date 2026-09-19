"""Frame styles and layouts: built-in presets (seeded at startup) and lookups.

Presets live in `assets/presets/*.json` with stable ids. Seeding inserts missing ones and updates
changed ones (revision + 1); artworks are unaffected because templates are copied on apply.
Editing UI and push updates: Phase 7.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from the_frame_v2.db.models import FrameStyle, Layout, Setting
from the_frame_v2.domain.templates import FrameStyleDocument, LayoutDocument
from the_frame_v2.errors import ProblemError

PRESETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "presets"
DEFAULT_STYLE_ID = "builtin-style-gallery-recessed"
DEFAULT_LAYOUT_ID = "builtin-layout-single"
DEFAULTS_SETTING = "artwork_defaults"


def _presets(name: str, key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = json.loads((PRESETS_DIR / name).read_text())[key]
    return items


def seed_builtins(session: Session) -> None:
    for item in _presets("frame_styles.json", "styles"):
        document = FrameStyleDocument.model_validate(item["document"]).model_dump(mode="json")
        style = session.get(FrameStyle, item["id"])
        if style is None:
            session.add(
                FrameStyle(id=item["id"], name=item["name"], document=document, builtin=True)
            )
        elif style.document != document or style.name != item["name"]:
            style.document, style.name, style.revision = document, item["name"], style.revision + 1
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
                    slot_count=len(layout_doc.slots),
                    builtin=True,
                )
            )
        elif layout.document != document or layout.name != item["name"]:
            layout.document, layout.name = document, item["name"]
            layout.slot_count, layout.revision = len(layout_doc.slots), layout.revision + 1


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


def defaults(session: Session) -> tuple[str, str]:
    """Default (style id, layout id) for new artworks (Settings UI: Phase 5)."""
    row = session.get(Setting, DEFAULTS_SETTING)
    value = row.value if row else {}
    return value.get("style_id", DEFAULT_STYLE_ID), value.get("layout_id", DEFAULT_LAYOUT_ID)


def set_defaults(session: Session, style_id: str, layout_id: str) -> tuple[str, str]:
    """Store the default (style, layout) for new artworks (both must exist)."""
    get_style(session, style_id)
    get_layout(session, layout_id)
    row = session.get(Setting, DEFAULTS_SETTING)
    value = {"style_id": style_id, "layout_id": layout_id}
    if row is None:
        session.add(Setting(key=DEFAULTS_SETTING, value=value))
    else:
        row.value = value
    return style_id, layout_id
