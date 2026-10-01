/**
 * The library filter AST, client side (docs/data-model.md §5.2).
 *
 * The server owns the meaning — `domain/filters.py` validates it and `services/library.py`
 * compiles it — so this module stays a *shape*: the chips the filter bar edits, and the plain
 * object they serialize to. Anything the server refuses comes back as `invalid_filter`, which is
 * why the smart-collection editor validates through `POST /filters/validate` rather than here.
 */

export type FilterField =
  | "tag"
  | "favorite"
  | "collection"
  | "taken_at"
  | "created_at"
  | "place"
  | "title"
  | "worst_tier"
  | "status"
  | "photo_count"
  | "is_incomplete"
  | "text";

export type ClauseOp =
  | "eq"
  | "in"
  | "not_in"
  | "has_any"
  | "has_all"
  | "none"
  | "between"
  | "before"
  | "after"
  | "contains"
  | "match"
  | "gte"
  | "lte"
  | "near";

/**
 * `place near`: a point and a radius. The label names the point for the chip (and for a smart
 * collection shown later); the server never matches on it. Being picked, it has no point yet.
 */
export interface NearValue {
  lat?: number;
  lon?: number;
  km: number;
  label: string;
}

export type FilterValue = string | number | boolean | string[] | NearValue;

export interface FilterClause {
  field: FilterField;
  op: ClauseOp;
  value: FilterValue;
  include_nested?: boolean;
}

export interface FilterGroup {
  op: "and" | "or" | "not";
  clauses: (FilterGroup | FilterClause)[];
}

/** The filter bar is a flat conjunction: one chip per clause. Nesting comes from smart filters. */
export type ChipFilter = FilterClause[];

export const FIELD_OPS: Record<FilterField, ClauseOp[]> = {
  tag: ["has_any", "has_all", "none"],
  favorite: ["eq"],
  collection: ["in", "not_in"],
  taken_at: ["between", "before", "after"],
  created_at: ["between", "before", "after"],
  place: ["contains", "near"],
  title: ["contains"],
  worst_tier: ["in"],
  status: ["eq"],
  photo_count: ["eq", "gte", "lte"],
  is_incomplete: ["eq"],
  text: ["match"],
};

/** Fields the chip bar offers, in the order they appear in the "Add filter" menu. */
export const CHIP_FIELDS: FilterField[] = [
  "tag",
  "favorite",
  "status",
  "collection",
  "place",
  "taken_at",
  "worst_tier",
  "photo_count",
  "title",
];

export const TIERS = ["native", "downscaled", "upscaled"] as const;

/** The radii the `place near` chip offers, in km (the server accepts up to 1000). */
export const NEAR_KM = [1, 5, 10, 25, 50, 100, 250, 500] as const;
export const DEFAULT_NEAR_KM = 25;

export function isNear(value: FilterValue): value is NearValue {
  return typeof value === "object" && !Array.isArray(value);
}

/** "Near this point": what a photo's drawer and a `?near=` link open the grid with. */
export function nearClause(lat: number, lon: number, km: number, label: string): FilterClause {
  return { field: "place", op: "near", value: { lat, lon, km, label } };
}

export function defaultClause(field: FilterField): FilterClause {
  const op = FIELD_OPS[field][0]!;
  switch (field) {
    case "tag":
    case "collection":
      return { field, op, value: [] };
    case "favorite":
    case "is_incomplete":
      return { field, op, value: true };
    case "worst_tier":
      return { field, op, value: ["upscaled"] };
    case "status":
      return { field, op, value: "ready" };
    case "photo_count":
      return { field, op, value: 1 };
    case "taken_at":
    case "created_at":
      return { field, op, value: ["", ""] };
    default:
      return { field, op, value: "" };
  }
}

/** A clause the server would reject (an empty tag list, a half-typed date) is simply dropped. */
export function isComplete(clause: FilterClause): boolean {
  const { value } = clause;
  if (isNear(value)) {
    return Number.isFinite(value.lat) && Number.isFinite(value.lon) && value.km > 0;
  }
  if (Array.isArray(value)) {
    return value.length > 0 && value.every((v) => v !== "");
  }
  if (typeof value === "string") return value.trim().length > 0;
  return true;
}

export function toGroup(chips: ChipFilter): FilterGroup | undefined {
  const clauses = chips.filter(isComplete);
  return clauses.length > 0 ? { op: "and", clauses } : undefined;
}

/** A stored AST back into chips; anything nested stays on the server side of the fence. */
export function toChips(group: FilterGroup | null | undefined): ChipFilter {
  if (!group || group.op !== "and") return [];
  return group.clauses.filter((c): c is FilterClause => "field" in c);
}

export function isGroup(node: FilterGroup | FilterClause): node is FilterGroup {
  return !("field" in node);
}

/**
 * The AST as the plain JSON object the API declares (`{ [k: string]: unknown }`).
 * The generated type is an open record; our shape is a closed one, so the cast is the seam.
 */
export function asJson(group: FilterGroup | undefined | null): Record<string, unknown> | undefined {
  return (group ?? undefined) as unknown as Record<string, unknown> | undefined;
}
