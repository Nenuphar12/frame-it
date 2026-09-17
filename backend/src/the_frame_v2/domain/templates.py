"""Frame styles, layouts and building an artwork document from photos.

Spec: docs/artwork-document.md (template documents) and docs/geometry-and-quality.md §7.4.
Templates are copied on apply: the resulting document does not reference them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from the_frame_v2.domain.document import (
    MAX_SLOTS,
    ArtworkDocument,
    AssetId,
    Band,
    CropSpec,
    DocModel,
    HexColor,
    ItemId,
    MarginsSpec,
    Mat,
    OrientSpec,
    Placement,
    QualityLock,
    RectSpec,
    Shadow,
    Slot,
    SourceSpec,
)
from the_frame_v2.domain.geometry import CANVAS, Margins, Rect, Size, round_half_even
from the_frame_v2.domain.placement import (
    SlotPlacement,
    available_area,
    fill,
    fill_slot,
    fit_in_mat,
    fit_slot,
    ratio_label,
)


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
    mat: Mat = Field(default_factory=Mat)
    margins: MarginsSpec = Field(default_factory=MarginsSpec)
    slot_defaults: SlotDefaults = Field(default_factory=SlotDefaults)
    caption_defaults: CaptionDefaults = Field(default_factory=CaptionDefaults)


class LayoutSlot(DocModel):
    id: ItemId
    rect: RectSpec
    """Canvas px for a canvas without margins; mapped into the style's available area on apply."""
    rotation: float = Field(default=0, ge=-180, le=180)
    quality_lock: QualityLock = "no_upscale"
    fill_mode: Literal["fill", "fit"] = "fill"


class LayoutCaption(DocModel):
    id: ItemId
    placeholder: str = Field(default="", max_length=500)
    x: int
    y: int
    anchor: Literal["start", "middle", "end"] = "middle"
    rotation: float = Field(default=0, ge=-180, le=180)


class LayoutDocument(DocModel):
    slots: list[LayoutSlot] = Field(min_length=1, max_length=MAX_SLOTS)
    captions: list[LayoutCaption] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def _unique_ids(self) -> LayoutDocument:
        if len({s.id for s in self.slots}) != len(self.slots):
            raise ValueError("slot ids must be unique")
        return self


@dataclass(frozen=True, slots=True)
class PhotoInput:
    id: str
    size: Size
    """EXIF-oriented size."""


def map_rect_to_area(rect: Rect, area: Rect, canvas: Size = CANVAS) -> Rect:
    """Scale a layout rect from the full canvas into `area` (edges mapped: gaps stay consistent)."""
    sx, sy = area.w / canvas.w, area.h / canvas.h
    left = area.x + round_half_even(rect.x * sx)
    top = area.y + round_half_even(rect.y * sy)
    right = area.x + round_half_even((rect.x + rect.w) * sx)
    bottom = area.y + round_half_even((rect.y + rect.h) * sy)
    return Rect(left, top, max(1, right - left), max(1, bottom - top))


def _slot(
    slot_id: str,
    photo: PhotoInput | None,
    placed: SlotPlacement,
    crop_ratio: str,
    rotation: float,
    defaults: SlotDefaults,
) -> Slot:
    rect, crop = placed.rect, placed.crop
    return Slot(
        id=slot_id,
        photo_id=photo.id if photo else None,
        rect=RectSpec(x=rect.x, y=rect.y, w=rect.w, h=rect.h),
        rotation=rotation if placed.quality_lock != "native" else 0,
        source=SourceSpec(
            orient=OrientSpec(),
            crop=CropSpec(x=crop.x, y=crop.y, w=crop.w, h=crop.h),
            crop_ratio=crop_ratio,
        ),
        quality_lock=placed.quality_lock,
        bands=[b.model_copy() for b in defaults.bands],
        shadow=defaults.shadow.model_copy() if defaults.shadow else None,
    )


def build_document(
    style: FrameStyleDocument,
    layout: LayoutDocument,
    photos: Sequence[PhotoInput | None],
    placement: Placement | None = None,
) -> ArtworkDocument:
    """New artwork document: style (mat, margins, decorations) + layout (slots) + photos in order.

    - One-slot layouts use `placement` (default `fit_in_mat`): `fit_in_mat` shows the whole photo
      inside the margins, `fill` covers the canvas. The style's quality lock applies.
    - Multi-slot layouts are `manual`: layout rects are mapped into the style's available area,
      `fill` slots crop the photo to the slot ratio, `fit` slots shrink to the photo ratio. The
      layout slot's quality lock applies.
    - A lock the photo cannot honour (e.g. `no_upscale` on a small photo in a `fill` slot) becomes
      `free`: the artwork is created as-is and shows its upscaled tier.
    - Missing photos (fewer photos than slots, or None) leave empty slots.
    """
    if len(photos) > len(layout.slots):
        raise ValueError("more photos than layout slots")
    defaults = style.slot_defaults
    m = style.margins
    margins = Margins(m.top, m.right, m.bottom, m.left)
    padded: list[PhotoInput | None] = [*photos, *[None] * (len(layout.slots) - len(photos))]
    mode: Placement = placement or "fit_in_mat"
    if len(layout.slots) != 1:
        mode = "manual"

    slots: list[Slot] = []
    area = available_area(margins)
    for layout_slot, photo in zip(layout.slots, padded, strict=True):
        target = map_rect_to_area(layout_slot.rect.geometry(), area) if mode == "manual" else area
        if photo is None:
            empty = SlotPlacement(target, Rect(0, 0, target.w, target.h), "free")
            slots.append(_slot(layout_slot.id, None, empty, "free", layout_slot.rotation, defaults))
            continue
        full = Rect(0, 0, photo.size.w, photo.size.h)
        if mode == "fit_in_mat":
            placed = fit_in_mat(photo.size, full, "original", margins, defaults.quality_lock)
            slots.append(_slot(layout_slot.id, photo, placed, "original", 0, defaults))
        elif mode == "fill":
            placed = fill(photo.size, defaults.quality_lock)
            ratio = ratio_label(placed.rect.w, placed.rect.h)
            slots.append(_slot(layout_slot.id, photo, placed, ratio, 0, defaults))
        elif layout_slot.fill_mode == "fill":
            placed = fill_slot(target, photo.size, layout_slot.quality_lock)
            ratio = ratio_label(target.w, target.h)
            slots.append(
                _slot(layout_slot.id, photo, placed, ratio, layout_slot.rotation, defaults)
            )
        else:
            placed = fit_slot(target, photo.size, layout_slot.quality_lock)
            slots.append(
                _slot(layout_slot.id, photo, placed, "original", layout_slot.rotation, defaults)
            )

    return ArtworkDocument(
        mat=style.mat.model_copy(deep=True),
        placement=mode,
        margins=style.margins.model_copy(),
        slots=slots,
    )
