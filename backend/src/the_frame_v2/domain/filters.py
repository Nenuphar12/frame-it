"""Library filter AST (docs/data-model.md §5.2) — pure validation and normalization.

One structure powers the filter bar and smart collections. This module owns *what a filter may
say*; turning it into SQL is `services/library.py`, which is the only place that knows the schema.

A node is either a **group** (`and` / `or` / `not` over sub-nodes) or a **clause** (`field`, `op`,
`value`). Clauses name artwork columns (`favorite`, `status`, `worst_tier`, …) or, for `taken_at`
and `place`, a property of *a photo the artwork uses* — those compile to an EXISTS over
`artwork_photos`. `place` reads the place *names* (`contains`) or the GPS position (`near`: within
`km` of a point, `{"lat", "lon", "km", "label"}` — the label is what the chip shows, never matched).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator

MAX_DEPTH = 4
MAX_CLAUSES = 64
MAX_VALUES = 200

GroupOp = Literal["and", "or", "not"]
FilterField = Literal[
    "tag",
    "favorite",
    "collection",
    "taken_at",
    "created_at",
    "updated_at",
    "place",
    "title",
    "worst_tier",
    "status",
    "photo_count",
    "is_incomplete",
    "text",
]
ClauseOp = Literal[
    "eq",
    "ne",
    "in",
    "not_in",
    "has_any",
    "has_all",
    "none",
    "between",
    "before",
    "after",
    "contains",
    "match",
    "gte",
    "lte",
    "near",
]

TIERS = ("native", "downscaled", "upscaled")
MAX_NEAR_KM = 1000
"""Beyond this a radius is a continent, which the place names already say better."""
STATUSES = ("draft", "ready")

#: Operators each field accepts; the first one is what the UI offers by default.
FIELD_OPS: dict[str, tuple[ClauseOp, ...]] = {
    "tag": ("has_any", "has_all", "none"),
    "favorite": ("eq",),
    "collection": ("in", "not_in"),
    "taken_at": ("between", "before", "after"),
    "created_at": ("between", "before", "after"),
    "updated_at": ("between", "before", "after"),
    "place": ("contains", "near"),
    "title": ("contains",),
    "worst_tier": ("in",),
    "status": ("eq", "in"),
    "photo_count": ("eq", "gte", "lte"),
    "is_incomplete": ("eq",),
    "text": ("match",),
}

_ID_FIELDS = {"tag", "collection"}
_DATE_FIELDS = {"taken_at", "created_at", "updated_at"}
_TEXT_FIELDS = {"place", "title", "text"}
_BOOL_FIELDS = {"favorite", "is_incomplete"}
_ENUMS: dict[str, tuple[str, ...]] = {"worst_tier": TIERS, "status": STATUSES}


class FilterError(ValueError):
    """An AST the library refuses (surfaced as 422 `invalid_filter`)."""


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value]


def _check_ids(field: str, value: Any) -> list[str]:
    items = _as_list(value)
    if not items or len(items) > MAX_VALUES:
        raise FilterError(f"{field}: expected 1..{MAX_VALUES} ids")
    if not all(isinstance(i, str) and 0 < len(i) <= 64 for i in items):
        raise FilterError(f"{field}: expected ids")
    return [str(i) for i in items]


def parse_date(value: Any, *, end: bool = False) -> datetime:
    """`YYYY-MM-DD` (or a full ISO stamp) as an aware UTC bound; `end` = the day's last moment."""
    if not isinstance(value, str):
        raise FilterError("expected a date")
    try:
        if len(value) == 10:
            day = date.fromisoformat(value)
            time = datetime.max.time() if end else datetime.min.time()
            return datetime.combine(day, time, tzinfo=UTC)
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FilterError(f"invalid date {value!r}") from exc
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


class Clause(BaseModel):
    """One condition. `include_nested` only means something for `collection`."""

    model_config = ConfigDict(extra="forbid")

    field: FilterField
    op: ClauseOp
    value: Any = None
    include_nested: bool = False

    @model_validator(mode="after")
    def _check(self) -> Clause:
        allowed = FIELD_OPS[self.field]
        if self.op not in allowed:
            raise FilterError(f"{self.field} does not support {self.op} (try {allowed[0]})")
        object.__setattr__(self, "value", _checked_value(self.field, self.op, self.value))
        return self


def _number(value: Any, name: str, low: float, high: float) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or not low <= value <= high:
        raise FilterError(f"place near: {name} must be within [{low:g}, {high:g}]")
    return float(value)


def _checked_near(value: Any) -> dict[str, Any]:
    """`{"lat", "lon", "km", "label"}`: a point and a radius; the label only names the point."""
    if not isinstance(value, Mapping):
        raise FilterError('place near: expected {"lat", "lon", "km"}')
    extra = set(value) - {"lat", "lon", "km", "label"}
    if extra:
        raise FilterError(f"place near: unexpected {', '.join(sorted(extra))}")
    label = value.get("label", "")
    if not isinstance(label, str):
        raise FilterError("place near: label must be text")
    km = _number(value.get("km"), "km", 0, MAX_NEAR_KM)
    if km <= 0:
        raise FilterError("place near: km must be above 0")
    return {
        "lat": round(_number(value.get("lat"), "lat", -90, 90), 6),
        "lon": round(_number(value.get("lon"), "lon", -180, 180), 6),
        "km": km,
        "label": label.strip()[:200],
    }


def _checked_value(field: str, op: ClauseOp, value: Any) -> Any:
    if field == "place" and op == "near":
        return _checked_near(value)
    if field in _ID_FIELDS:
        return _check_ids(field, value)
    if field in _BOOL_FIELDS:
        if not isinstance(value, bool):
            raise FilterError(f"{field}: expected a boolean")
        return value
    if field in _DATE_FIELDS:
        if op == "between":
            pair = _as_list(value)
            if len(pair) != 2:
                raise FilterError(f"{field}: between takes [start, end]")
            parse_date(pair[0])
            parse_date(pair[1], end=True)
            return [str(pair[0]), str(pair[1])]
        parse_date(value)
        return str(value)
    if field in _TEXT_FIELDS:
        if not isinstance(value, str) or not value.strip():
            raise FilterError(f"{field}: expected a non-empty string")
        return value.strip()[:200]
    if field == "photo_count":
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1000:
            raise FilterError("photo_count: expected 0..1000")
        return value
    choices = _ENUMS[field]
    items = _as_list(value)
    if not items or not all(i in choices for i in items):
        raise FilterError(f"{field}: expected one of {', '.join(choices)}")
    return items[0] if op == "eq" else [str(i) for i in items]


class Group(BaseModel):
    """`and` / `or` over its clauses; `not` negates their conjunction."""

    model_config = ConfigDict(extra="forbid")

    op: GroupOp
    clauses: list[Node] = Field(default_factory=list, max_length=MAX_CLAUSES)


def _node_kind(value: Any) -> str:
    """A node carrying a `field` is a clause; anything else is a group (precise error messages)."""
    if isinstance(value, dict):
        return "clause" if "field" in value else "group"
    return "clause" if isinstance(value, Clause) else "group"


type Node = Annotated[
    Annotated["Group", Tag("group")] | Annotated[Clause, Tag("clause")],
    Discriminator(_node_kind),
]

Group.model_rebuild()


def _walk(node: Group | Clause, depth: int) -> int:
    if depth > MAX_DEPTH:
        raise FilterError(f"filter nested deeper than {MAX_DEPTH}")
    if isinstance(node, Clause):
        return 1
    return sum(_walk(child, depth + 1) for child in node.clauses)


def parse_filter(raw: Any) -> Group:
    """Validate an AST (a bare clause is wrapped in an `and`). Raises `FilterError`."""
    if not isinstance(raw, dict):
        raise FilterError("a filter is an object")
    try:
        node: Group | Clause = (
            Clause.model_validate(raw) if "field" in raw else Group.model_validate(raw)
        )
    except FilterError:
        raise
    except ValueError as exc:
        raise FilterError(_first_message(exc)) from exc
    group = node if isinstance(node, Group) else Group(op="and", clauses=[node])
    total = _walk(group, 1)
    if total > MAX_CLAUSES:
        raise FilterError(f"filter holds more than {MAX_CLAUSES} clauses")
    return group


def _first_message(exc: ValueError) -> str:
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    details = errors(include_url=False)
    if not details:
        return str(exc)
    first = details[0]
    location = ".".join(str(p) for p in first.get("loc", ()))
    message = str(first.get("msg", "")).removeprefix("Value error, ")
    return f"{location}: {message}" if location else message


def fields_used(node: Group | Clause) -> set[str]:
    if isinstance(node, Clause):
        return {node.field}
    return {f for child in node.clauses for f in fields_used(child)}


def collection_ids_used(node: Group | Clause) -> set[str]:
    """Every collection a filter references (a smart collection may not reference itself)."""
    if isinstance(node, Clause):
        return set(node.value) if node.field == "collection" else set()
    return {i for child in node.clauses for i in collection_ids_used(child)}


def is_empty(node: Group | Clause) -> bool:
    return isinstance(node, Group) and not node.clauses


def remap_ids(node: Group, tags: Mapping[str, str], collections: Mapping[str, str]) -> Group:
    """A filter travelling between libraries: rewrite the ids its clauses name (import, §12.2).

    A smart collection is the one entity whose *content* holds foreign keys, so an import that
    remaps a tag or a collection has to rewrite the AST too or the collection quietly empties.
    Ids with no mapping are left alone: the importer drops the clause only if it stays unknown.
    """
    clauses: list[Node] = []
    for child in node.clauses:
        if isinstance(child, Group):
            clauses.append(remap_ids(child, tags, collections))
            continue
        mapping = {"tag": tags, "collection": collections}.get(child.field)
        if mapping is None:
            clauses.append(child)
            continue
        clauses.append(child.model_copy(update={"value": [mapping.get(i, i) for i in child.value]}))
    return node.model_copy(update={"clauses": clauses})
