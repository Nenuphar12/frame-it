"""Frame styles, layouts and building an artwork document from photos.

Spec: docs/templates.md (Phase 8) · docs/simple-editor.md §3 (the composition a layout stores).
Templates are copied on apply: the resulting document does not reference them.

A **layout is a recipe and its parameters** since Phase 8 — never absolute rects. Building an
artwork from a layout is therefore the same code path as the Simple editor's: the layout's block
goes into the document and `composition.apply` writes the geometry.

`restyle` and `relayout` are PURE and mirrored by `frontend/src/editor/core/templates.ts`
(parity pinned by `conformance/geometry/templates*.json`): the editor applies a template to the
working document and the server applies the same one during a push update, so the two must agree
field by field.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from the_frame_v2.domain.composition import CaptionStyle, Recipe, apply, cell_id
from the_frame_v2.domain.document import (
    MAX_SLOTS,
    ArtworkDocument,
    AssetId,
    Band,
    Caption,
    CellFormat,
    Composition,
    CompositionAxis,
    CompositionBorder,
    CompositionCaption,
    CompositionFormat,
    CompositionGutter,
    CropSpec,
    DocModel,
    HexColor,
    MarginsSpec,
    Mat,
    OrientSpec,
    QualityLock,
    RectSpec,
    Shadow,
    Slot,
    SourceSpec,
)
from the_frame_v2.domain.geometry import CANVAS, Rect, Size
from the_frame_v2.domain.placement import SlotPlacement, fit_slot

CaptionPlace = Literal["none", "above", "below"]


class SlotDefaults(DocModel):
    bands: list[Band] = Field(default_factory=list, max_length=3)
    shadow: Shadow | None = None
    quality_lock: QualityLock = "no_upscale"


class CaptionDefaults(DocModel):
    font: AssetId = "cormorant-garamond"
    weight: int = Field(default=500, ge=100, le=900)
    size: int = Field(default=48, ge=4, le=1000)
    color: HexColor = "#3A3A3A"
    letter_spacing: float = Field(default=0.02, ge=-0.5, le=2)


class FrameStyleDocument(DocModel):
    """A *look*: the mat, what is drawn around each photo, the caption's typography.

    `margins` are kept for a hand-built artwork; a composition derives its own (§3.7), which is
    why `restyle` never writes them — re-dressing must not disturb a layout.
    """

    mat: Mat = Field(default_factory=Mat)
    margins: MarginsSpec = Field(default_factory=MarginsSpec)
    slot_defaults: SlotDefaults = Field(default_factory=SlotDefaults)
    caption_defaults: CaptionDefaults = Field(default_factory=CaptionDefaults)


class LayoutDocument(DocModel):
    """A saved layout: the `composition` block minus what belongs to one artwork.

    The caption's *text* and `detached` are artwork state, so a layout carries only the side the
    caption sits on. Everything else is exactly the block the Simple editor edits.
    """

    recipe: AssetId
    balance: float | None = Field(default=None, ge=0, le=1)
    outer: CompositionAxis = Field(default_factory=lambda: CompositionAxis(x=120, y=120))
    gutter: CompositionGutter = Field(default_factory=lambda: CompositionGutter(x=80, y=80))
    format: CompositionFormat = "fill"
    cell_formats: list[CellFormat | None] = Field(default_factory=list, max_length=MAX_SLOTS)
    border: CompositionBorder | None = None
    caption_place: CaptionPlace = "none"

    def block(self, text: str = "") -> Composition:
        """The composition an artwork starts from, carrying its own caption text."""
        return Composition(
            recipe=self.recipe,
            balance=self.balance,
            outer=self.outer.model_copy(),
            gutter=self.gutter.model_copy(),
            format=self.format,
            cell_formats=list(self.cell_formats),
            border=self.border.model_copy() if self.border else None,
            caption=CompositionCaption(text=text, place=self.caption_place),
        )

    @classmethod
    def of(cls, block: Composition) -> LayoutDocument:
        """ "Save as layout": the artwork's parameters, without its caption text (§2)."""
        return cls(
            recipe=block.recipe,
            balance=block.balance,
            outer=block.outer.model_copy(),
            gutter=block.gutter.model_copy(),
            format=block.format,
            cell_formats=list(block.cell_formats),
            border=block.border.model_copy() if block.border else None,
            caption_place=block.caption.place,
        )


@dataclass(frozen=True, slots=True)
class PhotoInput:
    id: str
    size: Size
    """EXIF-oriented size."""


def _slot(slot_id: str, photo: PhotoInput | None, placed: SlotPlacement, crop_ratio: str) -> Slot:
    rect, crop = placed.rect, placed.crop
    return Slot(
        id=slot_id,
        photo_id=photo.id if photo else None,
        rect=RectSpec(x=rect.x, y=rect.y, w=rect.w, h=rect.h),
        rotation=0,
        source=SourceSpec(
            orient=OrientSpec(),
            crop=CropSpec(x=crop.x, y=crop.y, w=crop.w, h=crop.h),
            crop_ratio=crop_ratio,
        ),
        quality_lock=placed.quality_lock,
    )


def caption_style(style: FrameStyleDocument) -> CaptionStyle:
    """The style's caption typography, as `domain/composition` wants it (§3.7)."""
    defaults = style.caption_defaults
    return CaptionStyle(
        font=defaults.font,
        weight=defaults.weight,
        size=defaults.size,
        color=defaults.color,
        letter_spacing=defaults.letter_spacing,
    )


def _dressed_slot(slot: Slot, defaults: SlotDefaults, *, bands: bool) -> Slot:
    """`slot` wearing the style's decorations. `bands` is false while a block owns them (§3.7)."""
    copy = slot.model_copy(deep=True)
    copy.shadow = defaults.shadow.model_copy() if defaults.shadow else None
    if bands:
        copy.bands = [band.model_copy() for band in defaults.bands]
    return copy


def _dressed_caption(caption: Caption, defaults: CaptionDefaults) -> Caption:
    copy = caption.model_copy(deep=True)
    copy.font = defaults.font
    copy.weight = defaults.weight
    copy.size = defaults.size
    copy.color = defaults.color
    copy.letter_spacing = defaults.letter_spacing
    return copy


def _with(
    doc: ArtworkDocument,
    *,
    mat: Mat | None = None,
    composition: Composition | None = None,
    slots: Sequence[Slot] | None = None,
    captions: Sequence[Caption] | None = None,
) -> ArtworkDocument:
    return ArtworkDocument(
        schema_version=doc.schema_version,
        canvas=doc.canvas.model_copy(),
        mat=mat if mat is not None else doc.mat.model_copy(deep=True),
        placement=doc.placement,
        margins=doc.margins.model_copy(),
        composition=composition if composition is not None else doc.composition,
        slots=list(slots if slots is not None else doc.slots),
        captions=list(captions if captions is not None else doc.captions),
    )


def restyle(
    doc: ArtworkDocument,
    style: FrameStyleDocument,
    recipe: Recipe | None,
    photo_sizes: Mapping[str, Size],
) -> ArtworkDocument:
    """Re-dress `doc` in `style` — mat, shadow, band, caption typography — keeping its layout.

    The style's `margins` are deliberately left out: under a composition the block owns them
    (§3.7), and re-dressing must never move a photo the user placed. The band becomes
    `composition.border` while a block is attached, since that is who writes `bands` from then on;
    a hand-built or detached document takes the bands directly.

    A document that has no caption yet is solved with the style's typography, so a caption typed
    afterwards is the style's; one that already has captions keeps nothing of its own but its
    position (the block re-derives it).
    """
    block = doc.composition
    attached = block is not None and not block.detached
    defaults = style.slot_defaults
    slots = [_dressed_slot(slot, defaults, bands=not attached) for slot in doc.slots]
    captions = [_dressed_caption(caption, style.caption_defaults) for caption in doc.captions]
    mat = style.mat.model_copy(deep=True)
    if not attached or block is None:
        return _with(doc, mat=mat, slots=slots, captions=captions)
    band = defaults.bands[0] if defaults.bands else None
    restyled = block.model_copy(deep=True)
    restyled.border = (
        CompositionBorder(width=max(1, band.width), color=band.color) if band else None
    )
    dressed = _with(doc, mat=mat, composition=restyled, slots=slots, captions=captions)
    if recipe is None:
        return dressed
    return apply(dressed, recipe, photo_sizes, caption_style(style) if not captions else None)


def relayout(
    doc: ArtworkDocument,
    layout: LayoutDocument,
    recipe: Recipe,
    photo_sizes: Mapping[str, Size],
    caption: CaptionStyle | None = None,
) -> ArtworkDocument:
    """Give `doc` the layout's recipe and parameters, then re-solve (§3.7).

    The artwork's caption text moves into the new block — a layout carries the side, never the
    words — and a detached artwork is re-attached: applying a layout is exactly the "Re-apply
    layout" of `docs/simple-editor.md` §5 with someone else's parameters.
    """
    block = doc.composition
    text = block.caption.text if block else (doc.captions[0].text if doc.captions else "")
    return apply(_with(doc, composition=layout.block(text)), recipe, photo_sizes, caption)


def style_of_document(doc: ArtworkDocument) -> FrameStyleDocument:
    """ "Save as style": the look of `doc`, without its geometry (docs/templates.md §3)."""
    slot = doc.slots[0] if doc.slots else None
    block = doc.composition
    bands: list[Band] = []
    if block is not None and not block.detached:
        if block.border is not None:
            bands = [Band(width=block.border.width, color=block.border.color)]
    elif slot is not None:
        bands = [band.model_copy() for band in slot.bands]
    caption = doc.captions[0] if doc.captions else None
    return FrameStyleDocument(
        mat=doc.mat.model_copy(deep=True),
        margins=doc.margins.model_copy(),
        slot_defaults=SlotDefaults(
            bands=bands,
            shadow=slot.shadow.model_copy() if slot is not None and slot.shadow else None,
        ),
        caption_defaults=(
            CaptionDefaults(
                font=caption.font,
                weight=caption.weight,
                size=caption.size,
                color=caption.color,
                letter_spacing=caption.letter_spacing,
            )
            if caption
            else CaptionDefaults()
        ),
    )


def layout_of_document(doc: ArtworkDocument) -> LayoutDocument | None:
    """ "Save as layout": the parameters of `doc`, or None when it has no attached block."""
    block = doc.composition
    if block is None or block.detached:
        return None
    return LayoutDocument.of(block)


def build_composition_document(
    style: FrameStyleDocument,
    recipe: Recipe,
    composition: Composition,
    photos: Sequence[PhotoInput | None],
) -> ArtworkDocument:
    """New parametric artwork: the style's mat and decorations, the composition's geometry.

    The slots start as whole photos fitted in the canvas — a valid document, and the framing
    `apply` preserves (§4.1): a full-photo crop keeps zoom 1, so every cell gets the centred cover
    crop a new artwork wants. `apply` then writes the real geometry, captions and margins (§3.7).

    The style's band becomes the block's `border` unless the composition already names one: a
    block owns `bands` (§3.7), so a style that draws a white edge around each photo has to say so
    where the solver can see it — that is what keeps the gutter a gap between *printed* edges.
    """
    block = composition.model_copy(deep=True)
    band = style.slot_defaults.bands[0] if style.slot_defaults.bands else None
    if block.border is None and band is not None:
        block.border = CompositionBorder(width=max(1, band.width), color=band.color)
    canvas = Rect(0, 0, CANVAS.w, CANVAS.h)
    slots: list[Slot] = []
    for index, photo in enumerate(photos):
        slot_id = cell_id(index)
        if photo is None:
            empty = SlotPlacement(canvas, Rect(0, 0, canvas.w, canvas.h), "free")
            slots.append(_slot(slot_id, None, empty, "free"))
        else:
            slots.append(_slot(slot_id, photo, fit_slot(canvas, photo.size, "free"), "original"))
    skeleton = ArtworkDocument(
        mat=style.mat.model_copy(deep=True),
        placement="manual",
        margins=style.margins.model_copy(),
        composition=block,
        slots=[_dressed_slot(slot, style.slot_defaults, bands=False) for slot in slots],
    )
    sizes = {photo.id: photo.size for photo in photos if photo is not None}
    return apply(skeleton, recipe, sizes, caption_style(style))
