"""Artwork document v1: Pydantic schema, structural validation, migrations.

Spec: docs/artwork-document.md. JSON Schema: docs/schemas/artwork-document.v1.json
(`frame-it schemas`). Checks that need the library (photo sizes, fonts, textures) live in
`validate_references`, called by the artworks service.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from frame_it.domain.geometry import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    Orient,
    Rect,
    Size,
    aspect_consistent,
    crop_within,
    oriented_size,
)
from frame_it.domain.quality import ArtworkQuality, SlotGeometry, artwork_quality

SCHEMA_VERSION = 1
MAX_SLOTS = 32
MAX_CAPTIONS = 32
MAX_COORD = 20_000
"""Canvas coordinates/sizes (slots may extend beyond the canvas)."""
MAX_SOURCE = 100_000
"""Source (crop) coordinates/sizes; real bounds come from the photo."""

HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
ItemId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
AssetId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,64}$")]
Coord = Annotated[int, Field(ge=-MAX_COORD, le=MAX_COORD)]
Length = Annotated[int, Field(ge=1, le=MAX_COORD)]
CropRatio = Annotated[
    str, StringConstraints(pattern=r"^(original|free|[1-9][0-9]{0,4}:[1-9][0-9]{0,4})$")
]
CompositionFormat = Annotated[
    str, StringConstraints(pattern=r"^(fill|original|[1-9][0-9]{0,3}:[1-9][0-9]{0,3})$")
]
"""`fill`, `original` (1-cell recipes only) or `w:h` with `w, h` ∈ [1, 1000] (checked below)."""
CellFormat = Annotated[
    str, StringConstraints(pattern=r"^(original|[1-9][0-9]{0,3}:[1-9][0-9]{0,3})$")
]
"""A per-cell format: a ratio or the photo's own aspect. `fill` is a property of the whole block."""
MAX_FORMAT_TERM = 1000
MAX_SPLITS = 16
"""Split nodes a recipe tree can hold (one fewer than its cells, at most)."""
SplitWeights = Annotated[
    list[Annotated[float, Field(gt=0, le=1000)]], Field(min_length=2, max_length=8)
]
"""The shares of one split's children — same bounds as a recipe's own `weights`."""
CaptionAlign = Literal["left", "center", "right"]
QualityLock = Literal["native", "no_upscale", "free"]
Placement = Literal["fit_in_mat", "fill", "manual"]


class DocModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class CanvasSpec(DocModel):
    width: Literal[3840] = 3840
    height: Literal[2160] = 2160


class TextureRef(DocModel):
    id: AssetId
    strength: float = Field(ge=0, le=1)


class Mat(DocModel):
    color: HexColor = "#F2EFE8"
    texture: TextureRef | None = None


class MarginsSpec(DocModel):
    top: int = Field(default=0, ge=0, le=CANVAS_HEIGHT - 1)
    right: int = Field(default=0, ge=0, le=CANVAS_WIDTH - 1)
    bottom: int = Field(default=0, ge=0, le=CANVAS_HEIGHT - 1)
    left: int = Field(default=0, ge=0, le=CANVAS_WIDTH - 1)
    linked: bool = False
    """All four margins move together."""
    mirror_x: bool = False
    """`left` and `right` stay equal."""
    mirror_y: bool = False
    """`top` and `bottom` stay equal."""

    @model_validator(mode="after")
    def _leaves_room(self) -> MarginsSpec:
        if self.left + self.right >= CANVAS_WIDTH or self.top + self.bottom >= CANVAS_HEIGHT:
            raise ValueError("margins leave no room for the photo")
        return self


class RectSpec(DocModel):
    x: Coord
    y: Coord
    w: Length
    h: Length

    def geometry(self) -> Rect:
        return Rect(self.x, self.y, self.w, self.h)


class CropSpec(DocModel):
    x: Annotated[int, Field(ge=0, le=MAX_SOURCE)]
    y: Annotated[int, Field(ge=0, le=MAX_SOURCE)]
    w: Annotated[int, Field(ge=1, le=MAX_SOURCE)]
    h: Annotated[int, Field(ge=1, le=MAX_SOURCE)]

    def geometry(self) -> Rect:
        return Rect(self.x, self.y, self.w, self.h)


class OrientSpec(DocModel):
    rotate: Literal[0, 90, 180, 270] = 0
    flip_h: bool = False

    def geometry(self) -> Orient:
        return Orient(self.rotate, self.flip_h)


class SourceSpec(DocModel):
    orient: OrientSpec = Field(default_factory=OrientSpec)
    crop: CropSpec
    crop_ratio: CropRatio = "original"


class Band(DocModel):
    width: int = Field(ge=1, le=1000)
    color: HexColor
    bevel: bool = False
    """Drawn as the cut edge of a mat window: four mitred faces shaded from `color`, the top and
    left ones in shade, the bottom and right ones lit (rendering-spec.md §8.1, step 3.5)."""


class Shadow(DocModel):
    type: Literal["inner", "drop"]
    offset_x: int = Field(default=0, ge=-500, le=500)
    offset_y: int = Field(default=0, ge=-500, le=500)
    blur: float = Field(default=0, ge=0, le=200)
    color: HexColor = "#000000"
    opacity: float = Field(default=0.35, ge=0, le=1)


class EdgeShadow(DocModel):
    """The shadow the TV's frame casts onto the artwork (rendering-spec.md §8.1, step 5).

    An inner shadow of the whole canvas, drawn last — it falls on a photo that fills the screen
    just as a real frame's would. The offset is the light's direction: `offset_y > 0` darkens the
    top edge and leaves the bottom one clear.
    """

    offset_x: int = Field(default=0, ge=-500, le=500)
    offset_y: int = Field(default=0, ge=-500, le=500)
    blur: float = Field(default=0, ge=0, le=200)
    color: HexColor = "#000000"
    opacity: float = Field(default=0.25, ge=0, le=1)


class Slot(DocModel):
    id: ItemId
    photo_id: str | None = Field(default=None, max_length=64)
    rect: RectSpec
    rotation: float = Field(default=0, ge=-180, le=180)
    """Degrees clockwise around the rect centre, stored rounded to 0.1°."""
    source: SourceSpec
    quality_lock: QualityLock = "no_upscale"
    bands: list[Band] = Field(default_factory=list, max_length=3)
    """Inner → outer."""
    shadow: Shadow | None = None

    @model_validator(mode="after")
    def _geometry_rules(self) -> Slot:
        self.rotation = round(self.rotation, 1) + 0.0  # normalise -0.0
        rect, crop = self.rect, self.source.crop
        if not aspect_consistent(rect.w, rect.h, crop.w, crop.h):
            raise ValueError("slot and crop aspect ratios differ")
        if self.quality_lock == "native" and (
            rect.w != crop.w or rect.h != crop.h or self.rotation != 0
        ):
            raise ValueError("native lock requires slot size = crop size and no rotation")
        if self.quality_lock == "no_upscale" and (rect.w > crop.w or rect.h > crop.h):
            raise ValueError("no_upscale lock forbids a slot larger than its crop")
        return self

    def quality_input(self) -> SlotGeometry:
        crop = self.source.crop
        return SlotGeometry(
            self.rect.w, self.rect.h, crop.w, crop.h, self.rotation, self.photo_id is not None
        )


class Caption(DocModel):
    id: ItemId
    text: str = Field(min_length=1, max_length=500)
    font: AssetId
    weight: int = Field(default=400, ge=100, le=900)
    size: int = Field(ge=4, le=1000)
    """Font size in canvas px."""
    color: HexColor = "#3A3A3A"
    letter_spacing: float = Field(default=0, ge=-0.5, le=2)
    """Extra space between characters, in em."""
    x: Coord
    y: Coord
    """(x, y) = baseline anchor point."""
    anchor: Literal["start", "middle", "end"] = "start"
    rotation: float = Field(default=0, ge=-180, le=180)

    @model_validator(mode="after")
    def _single_line(self) -> Caption:
        if any(ch in self.text for ch in "\r\n\t"):
            raise ValueError("captions are single-line")
        self.rotation = round(self.rotation, 1) + 0.0
        return self


class CompositionAxis(DocModel):
    """A per-axis length in canvas px (`x` = horizontal, `y` = vertical)."""

    x: int = Field(ge=0, le=800)
    y: int = Field(ge=0, le=450)


class CompositionGutter(DocModel):
    x: int = Field(ge=0, le=400)
    y: int = Field(ge=0, le=400)


class CompositionBorder(DocModel):
    width: int = Field(ge=1, le=200)
    color: HexColor = "#FFFFFF"
    bevel: bool = False
    """The border is a mat bevel rather than a flat band (`Band.bevel`)."""


class CompositionCaption(DocModel):
    text: str = Field(default="", max_length=500)
    place: Literal["none", "above", "below"] = "none"
    align: CaptionAlign = "center"
    """Centred on the canvas, or flush with the block's left / right printed edge (§3.7)."""

    @model_validator(mode="after")
    def _single_line(self) -> CompositionCaption:
        if any(ch in self.text for ch in "\r\n\t"):
            raise ValueError("captions are single-line")
        return self


class Composition(DocModel):
    """Parametric layout (Phase 7, docs/simple-editor.md §2).

    Source of truth for `slots` and the derived caption while `detached` is false. Absent on legacy
    or hand-built artworks — `schema` stays 1, so there is nothing to migrate.
    """

    recipe: AssetId
    balance: float | None = Field(default=None, ge=0, le=1)
    """Share of the root split's first child; `None` = the recipe's default. Fill format only."""
    weights: list[SplitWeights | None] = Field(default_factory=list, max_length=MAX_SPLITS)
    """Per-split override of the recipe's `weights`, splits in depth-first order; `None` inherits.

    Fill format only, like `balance` — which stays the root's share wherever the recipe declares
    one (§3.4). An entry must hold one weight per child of its split (`weights_shape`).
    """
    outer: CompositionAxis = Field(default_factory=lambda: CompositionAxis(x=120, y=120))
    """Minimum margin around the block, per axis."""
    gutter: CompositionGutter = Field(default_factory=lambda: CompositionGutter(x=80, y=80))
    """Exact gap between two printed edges, per axis."""
    format: CompositionFormat = "fill"
    cell_formats: list[CellFormat | None] = Field(default_factory=list, max_length=MAX_SLOTS)
    """Per-cell override of `format`, in slot order; `None` inherits.

    Ignored under `fill`, where the cells tile the area exactly and have no aspect of their own.
    """
    border: CompositionBorder | None = None
    caption: CompositionCaption = Field(default_factory=CompositionCaption)
    detached: bool = False
    """The slots have been hand-edited: they are the truth and this block is memory only (§5)."""

    @model_validator(mode="after")
    def _format_terms(self) -> Composition:
        for value in [self.format, *self.cell_formats]:
            if value is None or ":" not in value:
                continue
            width, height = (int(term) for term in value.split(":"))
            if width > MAX_FORMAT_TERM or height > MAX_FORMAT_TERM:
                raise ValueError(f"format terms must be ≤ {MAX_FORMAT_TERM}")
        return self


class ArtworkDocument(DocModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    schema_version: Literal[1] = Field(default=1, alias="schema")
    canvas: CanvasSpec = Field(default_factory=CanvasSpec)
    mat: Mat = Field(default_factory=Mat)
    placement: Placement = "fit_in_mat"
    margins: MarginsSpec = Field(default_factory=MarginsSpec)
    composition: Composition | None = None
    """Parametric layout driving `slots` and the derived caption (Phase 7); absent = hand-built."""
    slots: list[Slot] = Field(default_factory=list, max_length=MAX_SLOTS)
    """Array order = z-order (first is back-most)."""
    captions: list[Caption] = Field(default_factory=list, max_length=MAX_CAPTIONS)
    edge_shadow: EdgeShadow | None = None
    """The frame's shadow on the artwork, drawn over everything else; absent = none."""

    @model_validator(mode="after")
    def _document_rules(self) -> ArtworkDocument:
        slot_ids = [s.id for s in self.slots]
        if len(set(slot_ids)) != len(slot_ids):
            raise ValueError("slot ids must be unique")
        caption_ids = [c.id for c in self.captions]
        if len(set(caption_ids)) != len(caption_ids):
            raise ValueError("caption ids must be unique")
        if self.placement != "manual" and len(self.slots) != 1:
            raise ValueError(f"placement {self.placement} requires exactly one slot")
        composition = self.composition
        if composition is not None and len(composition.cell_formats) > len(self.slots):
            raise ValueError("more cell formats than slots")
        return self

    def photo_ids(self) -> list[str]:
        return [s.photo_id for s in self.slots if s.photo_id is not None]

    def quality(self) -> ArtworkQuality:
        return artwork_quality(s.quality_input() for s in self.slots)

    def canonical(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)

    def render_identity(self) -> dict[str, Any]:
        """The canonical document as the **render hash** reads it.

        Optional fields added after schema 1 shipped are left out while they hold their default,
        so a document that does not use a feature hashes exactly as it did before the feature
        existed. Without this, adding any defaulted field changes every artwork's hash: the whole
        render cache is thrown away and the next push re-uploads the whole set to the TV, for
        pictures whose pixels did not change. A field added to the document later belongs in
        `_LATER_DEFAULTS` — unless the same document is now meant to render differently, which is
        what `RENDERER_VERSION` is for.
        """
        data = self.canonical()
        _drop_defaults(data, _LATER_DEFAULTS)
        return data


_LATER_DEFAULTS: dict[str, Any] = {
    "edge_shadow": None,
    "composition": {
        "weights": [],
        "caption": {"align": "center"},
        "border": {"bevel": False},
    },
    "slots": [{"bands": [{"bevel": False}]}],
}
"""Fields added to schema 1 after it shipped, with the default each one is omitted at
(`render_identity`). A dict descends into an object, a one-item list into every item of a list."""


def _drop_defaults(data: Any, defaults: Any) -> None:
    if isinstance(defaults, list):
        for item in data if isinstance(data, list) else []:
            _drop_defaults(item, defaults[0])
        return
    if not isinstance(data, dict):
        return
    for key, default in defaults.items():
        if key not in data:
            continue
        if isinstance(default, dict) or (isinstance(default, list) and default):
            _drop_defaults(data[key], default)
        elif data[key] == default:
            del data[key]


# ---- references (need library data) -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RecipeSpec:
    """What validating a `composition` needs from the recipe catalogue (`domain/composition.py`)."""

    count: int
    balance_min: float | None = None
    balance_max: float | None = None
    splits: tuple[int, ...] = ()
    """Children per split node, depth-first — the shape `composition.weights` must fit."""


@dataclass(frozen=True, slots=True)
class DocumentIssue:
    loc: tuple[str | int, ...]
    msg: str
    type: str

    def as_dict(self) -> dict[str, Any]:
        return {"loc": list(self.loc), "msg": self.msg, "type": self.type}


def _composition_issues(
    doc: ArtworkDocument, recipe_spec: Callable[[str], RecipeSpec | None]
) -> list[DocumentIssue]:
    """Catalogue checks of §2: the recipe exists, matches the slot count, balance is in range and
    the per-split weights have the recipe's shape."""
    composition = doc.composition
    if composition is None:
        return []
    spec = recipe_spec(composition.recipe)
    if spec is None:
        return [DocumentIssue(("composition", "recipe"), "unknown recipe", "unknown_recipe")]
    issues: list[DocumentIssue] = []
    if not composition.detached and spec.count != len(doc.slots):
        issues.append(
            DocumentIssue(
                ("composition", "recipe"),
                f"recipe holds {spec.count} cells but the document has {len(doc.slots)} slots",
                "recipe_slot_count",
            )
        )
    balance, low, high = composition.balance, spec.balance_min, spec.balance_max
    if balance is not None and (low is None or high is None):
        issues.append(
            DocumentIssue(
                ("composition", "balance"), "recipe has no balance", "balance_not_supported"
            )
        )
    elif (
        balance is not None
        and low is not None
        and high is not None
        and not (low <= balance <= high)
    ):
        issues.append(
            DocumentIssue(
                ("composition", "balance"),
                f"balance must be within [{low}, {high}]",
                "balance_out_of_range",
            )
        )
    for index, entry in enumerate(composition.weights):
        if entry is None:
            continue
        if index >= len(spec.splits) or len(entry) != spec.splits[index]:
            issues.append(
                DocumentIssue(
                    ("composition", "weights", index),
                    "weights do not fit the recipe's splits",
                    "weights_shape",
                )
            )
            break
    return issues


def validate_references(
    doc: ArtworkDocument,
    photo_sizes: Mapping[str, Size],
    font_weights: Callable[[str], frozenset[int] | None],
    texture_exists: Callable[[str], bool],
    recipe_spec: Callable[[str], RecipeSpec | None] = lambda _: None,
) -> list[DocumentIssue]:
    """Photos exist and crops lie inside their oriented source; fonts, weights and textures exist.

    `photo_sizes` maps usable photo ids to their EXIF-oriented size (missing = unknown or trashed).
    `recipe_spec` resolves a composition's recipe id in the bundled catalogue (default: no
    catalogue, so compositions are not checked — callers that have one pass it).
    """
    issues: list[DocumentIssue] = []
    if doc.mat.texture is not None and not texture_exists(doc.mat.texture.id):
        issues.append(DocumentIssue(("mat", "texture", "id"), "unknown texture", "unknown_texture"))
    issues.extend(_composition_issues(doc, recipe_spec))
    for index, slot in enumerate(doc.slots):
        if slot.photo_id is None:
            continue
        size = photo_sizes.get(slot.photo_id)
        if size is None:
            issues.append(
                DocumentIssue(("slots", index, "photo_id"), "unknown photo", "unknown_photo")
            )
            continue
        bounds = oriented_size(size, slot.source.orient.geometry())
        if not crop_within(slot.source.crop.geometry(), bounds):
            issues.append(
                DocumentIssue(
                    ("slots", index, "source", "crop"),
                    f"crop exceeds the {bounds.w}×{bounds.h} oriented photo",
                    "crop_out_of_bounds",
                )
            )
    for index, caption in enumerate(doc.captions):
        weights = font_weights(caption.font)
        if weights is None:
            issues.append(
                DocumentIssue(("captions", index, "font"), "unknown font", "unknown_font")
            )
        elif caption.weight not in weights:
            available = ", ".join(str(w) for w in sorted(weights))
            issues.append(
                DocumentIssue(
                    ("captions", index, "weight"),
                    f"weight not available (available: {available})",
                    "unknown_font_weight",
                )
            )
    return issues


# ---- evolution ----------------------------------------------------------------------------------
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}
"""`MIGRATIONS[n]` migrates a raw schema-n document to schema n+1 (pure). None yet."""


def migrate(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Bring a raw document to the current schema (documents are migrated on read)."""
    data = dict(raw)
    version = data.get("schema", SCHEMA_VERSION)
    if not isinstance(version, int) or version > SCHEMA_VERSION or version < 1:
        raise ValueError(f"unsupported document schema {version!r}")
    while version < SCHEMA_VERSION:
        data = MIGRATIONS[version](data)
        version = int(data["schema"])
    return data


def parse_document(raw: Mapping[str, Any]) -> ArtworkDocument:
    return ArtworkDocument.model_validate(migrate(raw))


def json_schema() -> dict[str, Any]:
    schema = ArtworkDocument.model_json_schema(by_alias=True, mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://frame-it/schemas/artwork-document.v1.json"
    schema["title"] = "Artwork document v1"
    return schema
