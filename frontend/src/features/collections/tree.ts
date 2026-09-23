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
