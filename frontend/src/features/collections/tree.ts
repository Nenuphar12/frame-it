import type { Collection } from "@/api/client";

export interface TreeNode {
  collection: Collection;
  children: TreeNode[];
}

/** Rows come flat, ordered by `position` among siblings; the tree is rebuilt from `parent_id`. */
export function buildTree(rows: Collection[]): TreeNode[] {
  const nodes = new Map<string, TreeNode>(
    rows.map((collection) => [collection.id, { collection, children: [] }]),
  );
  const roots: TreeNode[] = [];
  for (const row of rows) {
    const node = nodes.get(row.id)!;
    const parent = row.parent_id ? nodes.get(row.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

/** A collection and every descendant — what a parent picker must not offer as a new parent. */
export function subtreeIds(rows: Collection[], rootId: string): string[] {
  const byParent = new Map<string, Collection[]>();
  for (const row of rows) {
    const key = row.parent_id ?? "";
    byParent.set(key, [...(byParent.get(key) ?? []), row]);
  }
  const out: string[] = [];
  const walk = (id: string) => {
    out.push(id);
    for (const child of byParent.get(id) ?? []) walk(child.id);
  };
  walk(rootId);
  return out;
}

/** Where, relative to a row, a dragged collection would land. */
export type DropWhere = "before" | "inside" | "after";

/**
 * Which part of a row the pointer is over: `ratio` is 0 at its top edge, 1 at its bottom. A row
 * that can hold collections (a manual one) has three bands — above it, into it, below it; a smart
 * one only the two halves, since nothing goes inside it.
 */
export function dropWhere(ratio: number, canHold: boolean): DropWhere {
  if (!canHold) return ratio < 0.5 ? "before" : "after";
  if (ratio < 0.3) return "before";
  return ratio > 0.7 ? "after" : "inside";
}

export interface CollectionMove {
  parentId: string | null;
  /** The sibling it goes in front of; `null` = last. */
  beforeId: string | null;
}

/**
 * The move a drop asks for (`POST /collections/{id}/move`), or `null` when the drop would change
 * nothing or cannot be: onto itself, or into its own subtree (the server would refuse a cycle).
 *
 * "After" an **open** row that has children lands first among those children — that is where the
 * line is drawn, between the row and its first child. `before_id` never names the moved
 * collection itself: the server looks it up among the *other* siblings.
 */
export function moveFor(
  rows: Collection[],
  movedId: string,
  targetId: string,
  where: DropWhere,
  targetOpen: boolean,
): CollectionMove | null {
  const moved = rows.find((c) => c.id === movedId);
  const target = rows.find((c) => c.id === targetId);
  if (!moved || !target || movedId === targetId) return null;
  if (subtreeIds(rows, movedId).includes(targetId)) return null;
  const childrenOf = (parentId: string | null) =>
    rows.filter((c) => (c.parent_id ?? null) === parentId && c.id !== movedId);
  let move: CollectionMove;
  if (where === "inside") {
    if (target.kind !== "manual") return null;
    move = { parentId: target.id, beforeId: null };
  } else if (where === "before") {
    move = { parentId: target.parent_id ?? null, beforeId: target.id };
  } else {
    const children = childrenOf(target.id);
    if (targetOpen && target.kind === "manual" && children.length > 0) {
      move = { parentId: target.id, beforeId: children[0]!.id };
    } else {
      const siblings = childrenOf(target.parent_id ?? null);
      const index = siblings.findIndex((c) => c.id === target.id);
      move = { parentId: target.parent_id ?? null, beforeId: siblings[index + 1]?.id ?? null };
    }
  }
  // Same parent, same neighbour after it: nothing would move.
  const current = rows.filter((c) => (c.parent_id ?? null) === (moved.parent_id ?? null));
  const next = current[current.findIndex((c) => c.id === movedId) + 1]?.id ?? null;
  if (move.parentId === (moved.parent_id ?? null) && move.beforeId === next) return null;
  return move;
}
