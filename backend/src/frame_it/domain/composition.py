"""Parametric compositions: recipe trees and the layout solver.

Spec: docs/simple-editor.md §3 and §4.

PURE. Mirrored by `frontend/src/editor/core/composition.ts`; parity pinned by
`conformance/geometry/composition.json`. Same rounding discipline as the rest of `domain/`: float
maths all the way down, `round_half_even` on the final integer edges only.

The solver works on **footprints** — the photo rect grown by the border on each side — because the
renderer draws bands outward from the slot rect (`rendering-spec.md` §3.19). So `gutter` is the gap
between two printed edges and `outer` the distance from the canvas edge to a printed edge, which is
what the eye sees. `Cell.rect` is the footprint already deflated: the slot rect to write down.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, model_validator

from frame_it.domain.document import (
    ArtworkDocument,
    Band,
    Caption,
    Composition,
    CropSpec,
    DocModel,
    MarginsSpec,
    QualityLock,
    RecipeSpec,
    RectSpec,
    Slot,
    SourceSpec,
)
from frame_it.domain.geometry import (
    CANVAS,
    Margins,
    Rect,
    Size,
    oriented_size,
    round_half_even,
)
from frame_it.domain.placement import crop_center, largest_crop, ratio_label

MIN_CELL = 40
"""Smallest acceptable photo rect on either axis; below it the solver relaxes (§3.6)."""
CAPTION_BAND_FACTOR = 1.5
"""Height reserved for a caption, in multiples of its font size (docs/simple-editor.md §10)."""
DEFAULT_CAPTION_SIZE = 48
"""Matches `templates.CaptionDefaults.size`; the caller passes the style's own value."""
RELAXATION_STEPS = 10
"""Ladder used to recover from an over-constrained document (§3.6): fixed, hence mirrorable."""
CAPTION_BASELINE_FACTOR = 1.05
"""Baseline of the derived caption inside its line, in multiples of the font size (§3.7).

`CAPTION_BAND_FACTOR − 1` of leading shared above and below, plus a ~0.8 em ascent: a pure
number, like the band itself, so both solvers place the caption identically without font metrics.
"""
DERIVED_CAPTION_ID = "caption"
"""Id of the caption a composition derives; an existing caption keeps its own id."""

CellKind = Literal["landscape", "portrait", "square", "auto"]


# ---- recipes ------------------------------------------------------------------------------------
class RecipeCell(DocModel):
    """A leaf: one cell. `auto` takes the photo's own orientation (1-cell recipes)."""

    cell: CellKind


class RecipeSplit(DocModel):
    """`row`: children left→right, separated by `gutter.x`. `col`: top→bottom, `gutter.y`."""

    split: Literal["row", "col"]
    weights: list[Annotated[float, Field(gt=0, le=1000)]] = Field(min_length=2, max_length=8)
    children: list[RecipeNode] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def _one_weight_per_child(self) -> RecipeSplit:
        if len(self.weights) != len(self.children):
            raise ValueError("one weight per child")
        return self


RecipeNode = RecipeCell | RecipeSplit
RecipeSplit.model_rebuild()


class BalanceRange(DocModel):
    min: float = Field(ge=0, le=1)
    max: float = Field(ge=0, le=1)
    default: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> BalanceRange:
        if not self.min <= self.default <= self.max:
            raise ValueError("balance default must be within [min, max]")
        return self


class Recipe(DocModel):
    id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    count: int = Field(ge=1, le=16)
    name_key: str = Field(pattern=r"^recipes\.[a-z0-9-]{1,64}$")
    balance: BalanceRange | None = None
    """Replaces the root split's weights by `[b, 1−b]`; only a 2-child root may declare it."""
    tree: RecipeNode

    @model_validator(mode="after")
    def _tree_rules(self) -> Recipe:
        if len(leaves(self.tree)) != self.count:
            raise ValueError(f"recipe {self.id}: tree does not hold {self.count} cells")
        if self.balance is not None and (
            isinstance(self.tree, RecipeCell) or len(self.tree.children) != 2
        ):
            raise ValueError(f"recipe {self.id}: balance needs a 2-child root split")
        return self

    def spec(self) -> RecipeSpec:
        balance = self.balance
        return RecipeSpec(
            count=self.count,
            balance_min=balance.min if balance else None,
            balance_max=balance.max if balance else None,
            splits=tuple(len(node.children) for node in splits(self.tree)),
        )


class RecipeCatalog(DocModel):
    version: int
    recipes: list[Recipe] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> RecipeCatalog:
        if len({r.id for r in self.recipes}) != len(self.recipes):
            raise ValueError("recipe ids must be unique")
        return self


def leaves(node: RecipeNode) -> list[RecipeCell]:
    """Cells in depth-first order — the reading order, and the slot order (§3.1)."""
    if isinstance(node, RecipeCell):
        return [node]
    return [leaf for child in node.children for leaf in leaves(child)]


def splits(node: RecipeNode) -> list[RecipeSplit]:
    """Split nodes in depth-first order, the root first — how `composition.weights` is indexed."""
    if isinstance(node, RecipeCell):
        return []
    return [node, *(inner for child in node.children for inner in splits(child))]


# ---- solving ------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Cell:
    id: str
    rect: Rect
    """The photo rect: the cell's footprint deflated by the border width."""
    ratio_label: str
    """`w:h` of `rect`, reduced — the slot's `crop_ratio`."""


@dataclass(frozen=True, slots=True)
class _Box:
    """A float rect during the walk; only the final edges become integers."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True, slots=True)
class _Affine:
    """`w = α·h + β` between a node's footprint dimensions under a ratio format (§3.5)."""

    alpha: float
    beta: float


@dataclass(frozen=True, slots=True)
class _Relation:
    """A subtree's affine relations, shaped like it (walked in lockstep with the tree)."""

    affine: _Affine
    children: list[_Relation]


def cell_id(index: int) -> str:
    return f"c{index + 1}"


def format_ratio(composition_format: str) -> float | None:
    """Aspect a ratio format asks for, **as written**; `None` for `fill` and `original`.

    `4:3` and `3:4` are different formats: the one the user picked is the one the cells take
    (§3.5). Only an `auto` leaf still turns the ratio the photo's way, and it uses
    `landscape_ratio` for that.
    """
    if ":" not in composition_format:
        return None
    width, height = (int(term) for term in composition_format.split(":"))
    return width / height


def landscape_ratio(ratio: float) -> float:
    """`r ≥ 1` form of an aspect — what an `auto` leaf turns the photo's way."""
    return ratio if ratio >= 1 else 1 / ratio


def caption_band(caption_size: int, gutter_y: int) -> int:
    """Height reserved on the caption's side, before solving (§3.3).

    A pure function of the font size — no font metrics — so both solvers agree without ever
    touching `editor/canvas/fonts.ts`.
    """
    return round_half_even(caption_size * CAPTION_BAND_FACTOR) + gutter_y


def block_area(
    composition: Composition, caption_size: int = DEFAULT_CAPTION_SIZE, canvas: Size = CANVAS
) -> Rect:
    """`A`: the canvas minus `outer` on each side, minus the caption band (§3.3)."""
    return _block_area(composition, composition.outer.x, composition.outer.y, caption_size, canvas)


def _block_area(
    composition: Composition, outer_x: int, outer_y: int, caption_size: int, canvas: Size
) -> Rect:
    area = Rect(outer_x, outer_y, max(1, canvas.w - 2 * outer_x), max(1, canvas.h - 2 * outer_y))
    place = composition.caption.place
    if place == "none":
        return area
    band = min(area.h - 1, caption_band(caption_size, composition.gutter.y))
    top = area.y + band if place == "above" else area.y
    return Rect(area.x, top, area.w, max(1, area.h - band))


def solve(
    recipe: Recipe,
    composition: Composition,
    photo_sizes: Sequence[Size | None] = (),
    caption_size: int = DEFAULT_CAPTION_SIZE,
    canvas: Size = CANVAS,
) -> list[Cell]:
    """Cells of `recipe` laid out for `composition`, in reading order (= slot order).

    Total: an over-constrained document (import, hand-edited JSON) is retried with the gutters
    scaled down, then `outer`, and finally clamped — it never raises (§3.6).
    """
    attempt = _attempt(recipe, composition, photo_sizes, caption_size, canvas, 1.0, 1.0)
    if _roomy(attempt):
        return attempt
    for step in range(1, RELAXATION_STEPS + 1):
        attempt = _attempt(
            recipe,
            composition,
            photo_sizes,
            caption_size,
            canvas,
            (RELAXATION_STEPS - step) / RELAXATION_STEPS,
            1.0,
        )
        if _roomy(attempt):
            return attempt
    for step in range(1, RELAXATION_STEPS + 1):
        attempt = _attempt(
            recipe,
            composition,
            photo_sizes,
            caption_size,
            canvas,
            0.0,
            (RELAXATION_STEPS - step) / RELAXATION_STEPS,
        )
        if _roomy(attempt):
            return attempt
    return attempt


def solve_strict(
    recipe: Recipe,
    composition: Composition,
    photo_sizes: Sequence[Size | None] = (),
    caption_size: int = DEFAULT_CAPTION_SIZE,
    canvas: Size = CANVAS,
) -> list[Cell]:
    """One attempt at the parameters as given — no relaxation ladder (§3.6).

    What the panel bisects on to bound its sliders: `solve` would hide an over-constrained value
    behind the ladder and report cells that honour *other* parameters.
    """
    return _attempt(recipe, composition, photo_sizes, caption_size, canvas, 1.0, 1.0)


def roomy(cells: Sequence[Cell]) -> bool:
    """Every cell clears `MIN_CELL` on both axes — the ladder's stopping rule (§3.6)."""
    return _roomy(cells)


def _roomy(cells: Sequence[Cell]) -> bool:
    return all(cell.rect.w >= MIN_CELL and cell.rect.h >= MIN_CELL for cell in cells)


def _attempt(
    recipe: Recipe,
    composition: Composition,
    photo_sizes: Sequence[Size | None],
    caption_size: int,
    canvas: Size,
    gutter_scale: float,
    outer_scale: float,
) -> list[Cell]:
    gutter_x = round_half_even(composition.gutter.x * gutter_scale)
    gutter_y = round_half_even(composition.gutter.y * gutter_scale)
    outer_x = round_half_even(composition.outer.x * outer_scale)
    outer_y = round_half_even(composition.outer.y * outer_scale)
    area = _block_area(composition, outer_x, outer_y, caption_size, canvas)
    border = composition.border.width if composition.border else 0

    box = _Box(float(area.x), float(area.y), float(area.w), float(area.h))
    boxes: list[_Box] = []
    if composition.format == "fill":
        _walk_fill(
            recipe.tree, box, split_weights(recipe, composition), 0, gutter_x, gutter_y, boxes
        )
    else:
        aspects = [
            _leaf_aspect(cell, cell_format(composition, index), _size_at(photo_sizes, index), area)
            for index, cell in enumerate(leaves(recipe.tree))
        ]
        relation, _ = _relate(recipe.tree, aspects, 0, border, gutter_x, gutter_y)
        block = _fit_block(relation.affine, box)
        _walk_ratio(recipe.tree, relation, block, gutter_x, gutter_y, boxes)
    return [_cell(index, footprint, border) for index, footprint in enumerate(boxes)]


def _size_at(photo_sizes: Sequence[Size | None], index: int) -> Size | None:
    return photo_sizes[index] if index < len(photo_sizes) else None


def cell_format(composition: Composition, index: int) -> str:
    """The format cell *index* is laid out with: its own override, else the block's (§3.5).

    Overrides are per-cell aspects, so they only mean something under a ratio format — `fill` is a
    property of the whole block (the cells tile the area exactly) and ignores them.
    """
    if composition.format == "fill":
        return "fill"
    if index < len(composition.cell_formats):
        return composition.cell_formats[index] or composition.format
    return composition.format


def _leaf_aspect(cell: RecipeCell, fmt: str, photo: Size | None, area: Rect) -> float:
    """Target aspect (w/h) of a leaf's **photo** under a ratio format (§3.5).

    `original` follows the photo; an unknown photo falls back to the available area's own aspect,
    which makes a single empty cell fill the mat exactly (today's `fit_in_mat`). An `auto` leaf
    takes the *format* turned the photo's way — otherwise picking `1:1` for a single photo would
    do nothing at all (§3.3 "the photo's own orientation").

    Every other leaf takes the format exactly as written, orientation included: `4:3` and `3:4`
    are different pictures, and reading them as the same one is what made half the chips inert.
    """
    if fmt == "original":
        return photo.w / photo.h if photo else area.w / area.h
    ratio = format_ratio(fmt)
    if ratio is None:
        return area.w / area.h
    if cell.cell == "auto":
        upright = landscape_ratio(ratio)
        return 1 / upright if photo is not None and photo.h > photo.w else upright
    # `landscape` and `portrait` leaves both take the format as written: the chip the user picked
    # is the shape they expect to see, and a per-cell override (§3.5) is how one cell differs.
    return 1.0 if cell.cell == "square" else ratio


def split_weights(recipe: Recipe, composition: Composition) -> list[list[float]]:
    """The weights every split is laid out with under `fill`, in depth-first order (§3.4).

    A split takes its entry of `composition.weights` when there is one **of its own shape**, else
    the recipe's. Where the recipe declares a `balance`, the root is `[b, 1−b]` whatever the block
    says: `balance` stays the one name of that division. An entry of the wrong length is ignored
    rather than raised on — the solver is total (§3.6), `validate_references` is what reports it.
    """
    result: list[list[float]] = []
    for index, node in enumerate(splits(recipe.tree)):
        override = composition.weights[index] if index < len(composition.weights) else None
        if index == 0 and recipe.balance is not None:
            share = (
                composition.balance if composition.balance is not None else recipe.balance.default
            )
            result.append([share, 1 - share])
        elif override is not None and len(override) == len(node.children):
            result.append(list(override))
        else:
            result.append(list(node.weights))
    return result


def _cell(index: int, footprint: _Box, border: int) -> Cell:
    """Round a footprint's float edges, then deflate it by the border to get the photo rect."""
    left = round_half_even(footprint.x) + border
    top = round_half_even(footprint.y) + border
    right = round_half_even(footprint.x + footprint.w) - border
    bottom = round_half_even(footprint.y + footprint.h) - border
    width, height = max(1, right - left), max(1, bottom - top)
    return Cell(cell_id(index), Rect(left, top, width, height), ratio_label(width, height))


# ---- fill format (§3.4) -------------------------------------------------------------------------
def _walk_fill(
    node: RecipeNode,
    box: _Box,
    weights_of: Sequence[Sequence[float]],
    split: int,
    gutter_x: int,
    gutter_y: int,
    out: list[_Box],
) -> int:
    """Weighted split filling `box`; gutters stay exact, the last child snaps to the far edge.

    `split` is this node's index in `weights_of` if it is a split; returns the next free index.
    """
    if isinstance(node, RecipeCell):
        out.append(box)
        return split
    weights = weights_of[split]
    following = split + 1
    total = sum(weights)
    count = len(node.children)
    row = node.split == "row"
    gutter = gutter_x if row else gutter_y
    span = (box.w if row else box.h) - (count - 1) * gutter
    origin = box.x if row else box.y
    accumulated = 0.0
    start = origin
    for index, child in enumerate(node.children):
        accumulated += span * weights[index] / total
        end = origin + accumulated + index * gutter
        if index == count - 1:
            end = origin + (box.w if row else box.h)
        child_box = (
            _Box(start, box.y, max(0.0, end - start), box.h)
            if row
            else _Box(box.x, start, box.w, max(0.0, end - start))
        )
        following = _walk_fill(child, child_box, weights_of, following, gutter_x, gutter_y, out)
        start = end + gutter
    return following


# ---- ratio format (§3.5) ------------------------------------------------------------------------
def _relate(
    node: RecipeNode,
    aspects: Sequence[float],
    start: int,
    border: int,
    gutter_x: int,
    gutter_y: int,
) -> tuple[_Relation, int]:
    """Bottom-up `w = α·h + β` on footprints; returns the subtree and the next leaf index."""
    if isinstance(node, RecipeCell):
        aspect = aspects[start]
        return _Relation(_Affine(aspect, 2 * border * (1 - aspect)), []), start + 1
    children: list[_Relation] = []
    index = start
    for child in node.children:
        relation, index = _relate(child, aspects, index, border, gutter_x, gutter_y)
        children.append(relation)
    parts = [child.affine for child in children]
    gaps = len(parts) - 1
    if node.split == "row":
        alpha = sum(part.alpha for part in parts)
        beta = sum(part.beta for part in parts) + gaps * gutter_x
    else:
        # Children share the width: hᵢ = (w − βᵢ)/αᵢ and h = Σhᵢ + gaps·gutter_y; invert.
        alpha = 1 / sum(1 / part.alpha for part in parts)
        beta = alpha * (sum(part.beta / part.alpha for part in parts) - gaps * gutter_y)
    return _Relation(_Affine(alpha, beta), children), index


def _fit_block(affine: _Affine, area: _Box) -> _Box:
    """Largest block honouring `relation` inside `area`, centred — `outer` is a minimum (§3.5)."""
    height = area.h
    width = affine.alpha * height + affine.beta
    if width > area.w:
        width = area.w
        height = (area.w - affine.beta) / affine.alpha
    width, height = max(1.0, width), max(1.0, height)
    return _Box(area.x + (area.w - width) / 2, area.y + (area.h - height) / 2, width, height)


def _walk_ratio(
    node: RecipeNode,
    relation: _Relation,
    box: _Box,
    gutter_x: int,
    gutter_y: int,
    out: list[_Box],
) -> None:
    """Top-down: child sizes come from the affine relations, edges still accumulate as floats."""
    if isinstance(node, RecipeCell):
        out.append(box)
        return
    row = node.split == "row"
    gutter = gutter_x if row else gutter_y
    count = len(node.children)
    origin = box.x if row else box.y
    accumulated = 0.0
    start = origin
    for index, child in enumerate(node.children):
        affine = relation.children[index].affine
        accumulated += (
            affine.alpha * box.h + affine.beta if row else (box.w - affine.beta) / affine.alpha
        )
        end = origin + accumulated + index * gutter
        if index == count - 1:
            end = origin + (box.w if row else box.h)
        child_box = (
            _Box(start, box.y, max(0.0, end - start), box.h)
            if row
            else _Box(box.x, start, box.w, max(0.0, end - start))
        )
        _walk_ratio(child, relation.children[index], child_box, gutter_x, gutter_y, out)
        start = end + gutter


# ---- what the solver writes back (§3.7, §4.1) ---------------------------------------------------
def block_margins(cells: Sequence[Cell], border: int, canvas: Size = CANVAS) -> Margins:
    """Effective insets of the block's footprint bounding box — written back to `margins` (§3.7).

    Keeps the Advanced panels and every existing helper reading a truthful document.
    """
    if not cells:
        return Margins(0, 0, 0, 0)
    left = min(cell.rect.x for cell in cells) - border
    top = min(cell.rect.y for cell in cells) - border
    right = max(cell.rect.x + cell.rect.w for cell in cells) + border
    bottom = max(cell.rect.y + cell.rect.h for cell in cells) + border
    return Margins(
        top=max(0, min(top, canvas.h - 1)),
        right=max(0, min(canvas.w - right, canvas.w - 1)),
        bottom=max(0, min(canvas.h - bottom, canvas.h - 1)),
        left=max(0, min(left, canvas.w - 1)),
    )


def refit_crop(previous: Rect | None, source: Size, ratio: float | None) -> Rect:
    """Crop for a cell that moved: previous centre and zoom kept, new aspect imposed (§4.1).

    Zoom is `previous.w` relative to the largest crop at the new ratio, so reframing a photo
    survives a margin drag — the invariant users notice first. No previous crop ⇒ centred cover.

    The height comes from the **width and the ratio**, never from scaling `full.h`: rounding two
    independent sides can leave the crop just outside `aspect_consistent`, and a document the
    server would reject is exactly what invariant 11 forbids.
    """
    full = largest_crop(source, ratio)
    if previous is None:
        return full
    zoom = min(1.0, max(0.0, previous.w / full.w))
    width = max(1, min(full.w, round_half_even(full.w * zoom)))
    height = (
        max(1, min(full.h, round_half_even(full.h * zoom)))
        if ratio is None
        else max(1, min(full.h, round_half_even(width / ratio)))
    )
    center_x, center_y = crop_center(previous)
    return Rect(
        min(max(0, round_half_even(center_x - width / 2)), source.w - width),
        min(max(0, round_half_even(center_y - height / 2)), source.h - height),
        width,
        height,
    )


@dataclass(frozen=True, slots=True)
class CaptionStyle:
    """Typography of the derived caption — the style's `caption_defaults` (§3.7)."""

    font: str = "cormorant-garamond"
    weight: int = 500
    size: int = 48
    color: str = "#3A3A3A"
    letter_spacing: float = 0.02


def caption_style_of(doc: ArtworkDocument) -> CaptionStyle:
    """The document's own caption typography, else the built-in defaults.

    A composition carries the caption *text and side*, never its font: re-solving must keep the
    typography the style gave the artwork at creation (and anything the user changed since).
    """
    if not doc.captions:
        return CaptionStyle()
    caption = doc.captions[0]
    return CaptionStyle(
        caption.font, caption.weight, caption.size, caption.color, caption.letter_spacing
    )


def caption_baseline(composition: Composition, caption_size: int, canvas: Size = CANVAS) -> int:
    """Baseline `y` of the derived caption, inside the band `block_area` reserved (§3.3).

    The band holds a line of `CAPTION_BAND_FACTOR × size` against the outer margin and the gutter
    on the block's side; the baseline sits `CAPTION_BASELINE_FACTOR × size` below the line's top.
    Uses the nominal `outer`, so an over-constrained document that made the solver relax (§3.6)
    keeps its caption where the parameters asked — the block moved, the text did not.
    """
    offset = round_half_even(caption_size * CAPTION_BASELINE_FACTOR)
    if composition.caption.place == "above":
        return composition.outer.y + offset
    line = round_half_even(caption_size * CAPTION_BAND_FACTOR)
    return canvas.h - composition.outer.y - line + offset


def _solved_slot(slot: Slot, cell: Cell, source: Size | None, border: Band | None) -> Slot:
    """One slot rewritten from its cell (§3.7): rect, crop, ratio, lock and the border band.

    `photo_id`, `orient`, `shadow` and the crop's framing (centre + zoom) come from the slot.
    An empty slot is a placeholder: crop = the cell, `free` lock — filling it takes `no_upscale`
    back, or an emptied slot would silently allow upscaling afterwards.
    """
    rect = cell.rect
    bands = [border.model_copy()] if border else []
    crop = Rect(0, 0, rect.w, rect.h)
    ratio = "free"
    lock: QualityLock = "free"
    if source is not None:
        bounds = oriented_size(source, slot.source.orient.geometry())
        crop = refit_crop(slot.source.crop.geometry(), bounds, rect.w / rect.h)
        ratio = cell.ratio_label
        lock = "free" if rect.w > crop.w or rect.h > crop.h else "no_upscale"
    return Slot(
        id=slot.id,
        photo_id=slot.photo_id,
        rect=RectSpec(x=rect.x, y=rect.y, w=rect.w, h=rect.h),
        rotation=0,
        source=SourceSpec(
            orient=slot.source.orient.model_copy(),
            crop=CropSpec(x=crop.x, y=crop.y, w=crop.w, h=crop.h),
            crop_ratio=ratio,
        ),
        quality_lock=lock,
        bands=bands,
        shadow=slot.shadow.model_copy() if slot.shadow else None,
    )


def _derived_caption(
    doc: ArtworkDocument,
    composition: Composition,
    style: CaptionStyle,
    margins: Margins,
    canvas: Size,
) -> list[Caption]:
    """The one caption a composition owns (§3.7); none when it is off or has no text yet.

    `align` puts it on the canvas' centre line or flush with the block's printed edge — `margins`
    are the block's effective insets, so the text lines up with what the eye sees, border included.
    """
    text = composition.caption.text.strip()
    if composition.caption.place == "none" or not text:
        return []
    previous = doc.captions[0] if doc.captions else None
    anchor: Literal["start", "middle", "end"] = "middle"
    x = canvas.w // 2
    if composition.caption.align == "left":
        anchor, x = "start", margins.left
    elif composition.caption.align == "right":
        anchor, x = "end", canvas.w - margins.right
    return [
        Caption(
            id=previous.id if previous else DERIVED_CAPTION_ID,
            text=text,
            font=style.font,
            weight=style.weight,
            size=style.size,
            color=style.color,
            letter_spacing=style.letter_spacing,
            x=x,
            y=caption_baseline(composition, style.size, canvas),
            anchor=anchor,
            rotation=0,
        )
    ]


def apply(
    doc: ArtworkDocument,
    recipe: Recipe,
    photo_sizes: Mapping[str, Size],
    caption: CaptionStyle | None = None,
    canvas: Size = CANVAS,
) -> ArtworkDocument:
    """`doc` with its geometry re-derived from its `composition` block — §3.7's table.

    The composition is the source of truth while `detached` is false, so this is what the server
    stores and what the editor previews (same function, both languages). Everything the block does
    not describe is carried over from `doc`: title-side data, mat, orient, shadows, photo ids.

    A document without a composition, or a detached one, is returned unchanged: the slots are then
    the truth (§5). `photo_sizes` maps photo ids to their **unoriented** size; a photo missing from
    it is treated as an empty slot, which is also what `validate_references` will report.
    """
    composition = doc.composition
    if composition is None or composition.detached:
        return doc
    style = caption if caption is not None else caption_style_of(doc)
    sizes = [photo_sizes.get(slot.photo_id or "") for slot in doc.slots]
    cells = solve(recipe, composition, sizes, style.size, canvas)
    border = (
        Band(
            width=composition.border.width,
            color=composition.border.color,
            bevel=composition.border.bevel,
        )
        if composition.border
        else None
    )
    slots = [
        _solved_slot(slot, cell, photo_sizes.get(slot.photo_id or ""), border)
        for slot, cell in zip(doc.slots, cells, strict=False)
    ]
    margins = block_margins(cells, composition.border.width if composition.border else 0, canvas)
    return ArtworkDocument(
        schema_version=doc.schema_version,
        canvas=doc.canvas.model_copy(),
        mat=doc.mat.model_copy(deep=True),
        placement="manual",
        margins=MarginsSpec(
            top=margins.top, right=margins.right, bottom=margins.bottom, left=margins.left
        ),
        composition=composition.model_copy(deep=True),
        slots=slots,
        captions=_derived_caption(doc, composition, style, margins, canvas),
        edge_shadow=doc.edge_shadow.model_copy() if doc.edge_shadow else None,
    )
