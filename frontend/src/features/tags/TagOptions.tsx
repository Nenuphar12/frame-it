import { useTranslation } from "react-i18next";

import type { TagWithCount } from "@/api/client";

import { useTagCategoryIndex } from "./useTagCategories";

/**
 * `<option>`s for a native `<select>` of tags, grouped by category (`<optgroup>`), "Other" last.
 * `count` adds the per-kind usage after the name ("Alice (12)").
 */
export function TagOptions({
  tags,
  count,
}: {
  tags: readonly TagWithCount[];
  count?: (tag: TagWithCount) => number;
}) {
  const { t } = useTranslation();
  const { group } = useTagCategoryIndex();
  const label = (tag: TagWithCount) => (count ? `${tag.name} (${count(tag)})` : tag.name);
  return (
    <>
      {group(tags).map(({ category, tags: inGroup }) => (
        <optgroup key={category?.id ?? "other"} label={category?.name ?? t("tags.other")}>
          {inGroup.map((tag) => (
            <option key={tag.id} value={tag.id}>
              {label(tag)}
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );
}
