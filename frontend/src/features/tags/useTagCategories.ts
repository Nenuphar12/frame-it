import { useMemo } from "react";

import type { Tag, TagCategory } from "@/api/client";
import { useTagCategories } from "@/api/queries";

export interface TagGroup<T extends Tag> {
  /** `null` is "Other": the tags with no category. */
  category: TagCategory | null;
  tags: T[];
}

/**
 * Categories as the UI reads them (docs/organization.md §1): one level, in their order, and
 * "Other" last for the tags that have none. A tag's colour is its own, else its category's.
 */
export function useTagCategoryIndex() {
  const categories = useTagCategories();
  return useMemo(() => {
    const list = categories.data ?? [];
    const byId = new Map(list.map((category) => [category.id, category]));
    const colorOf = (tag: Tag): string | null =>
      tag.color ?? (tag.category_id ? (byId.get(tag.category_id)?.color ?? null) : null);
    /** The tags split by category, keeping the order they came in within each group. */
    function group<T extends Tag>(tags: readonly T[]): TagGroup<T>[] {
      const buckets = new Map<string | null, T[]>();
      for (const tag of tags) {
        const key = tag.category_id && byId.has(tag.category_id) ? tag.category_id : null;
        buckets.set(key, [...(buckets.get(key) ?? []), tag]);
      }
      const groups: TagGroup<T>[] = [];
      for (const category of list) {
        const found = buckets.get(category.id);
        if (found) groups.push({ category, tags: found });
      }
      const other = buckets.get(null);
      if (other) groups.push({ category: null, tags: other });
      return groups;
    }
    return { categories: list, byId, colorOf, group, isLoading: categories.isLoading };
  }, [categories.data, categories.isLoading]);
}
