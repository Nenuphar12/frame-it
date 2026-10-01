import { Plus, X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Tag } from "@/api/client";
import { useCreateTag, useTags } from "@/api/queries";

import { TagDot } from "./TagDot";
import { useTagCategoryIndex } from "./useTagCategories";

interface TagPickerProps {
  value: Tag[];
  onChange: (tags: Tag[]) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  /** `Escape` in the input (the caller closes the picker; the key goes no further). */
  onEscape?: () => void;
}

const SUGGESTIONS = 8;

/**
 * Chips + autocomplete input; Enter picks the first suggestion or creates the tag.
 *
 * With nothing typed it offers the tags used **most recently** — what you tagged the previous
 * photo with is what you want on this one; once you type, the matches are grouped by category.
 */
export function TagPicker({ value, onChange, disabled, autoFocus, onEscape }: TagPickerProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const trimmed = query.trim();
  const suggestions = useTags(trimmed, { sort: trimmed ? "usage" : "recent", limit: 30 });
  const createTag = useCreateTag();
  const { group, colorOf } = useTagCategoryIndex();
  const chosen = new Set(value.map((tag) => tag.id));
  const options = (suggestions.data ?? [])
    .filter((tag) => !chosen.has(tag.id))
    .filter((tag) => trimmed || tag.last_used_at)
    .slice(0, SUGGESTIONS);
  const exactMatch = options.some((tag) => tag.name.toLowerCase() === trimmed.toLowerCase());

  const add = (tag: Tag) => {
    onChange([
      ...value,
      { id: tag.id, name: tag.name, color: tag.color, category_id: tag.category_id },
    ]);
    setQuery("");
  };
  const create = async () => {
    if (!trimmed) return;
    add(await createTag.mutateAsync(trimmed));
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const first = options[0];
      if (first && (exactMatch || !trimmed)) add(first);
      else void create();
    } else if (event.key === "Backspace" && !query && value.length > 0) {
      onChange(value.slice(0, -1));
    } else if (event.key === "Escape" && onEscape) {
      event.preventDefault();
      event.stopPropagation();
      onEscape();
    }
  };

  const suggestion = (tag: Tag) => (
    <button
      key={tag.id}
      type="button"
      onClick={() => add(tag)}
      className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs text-muted hover:bg-panel-2 hover:text-text"
    >
      <TagDot color={colorOf(tag)} />
      {tag.name}
    </button>
  );

  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-border bg-bg p-1.5">
        {value.map((tag) => (
          <span
            key={tag.id}
            className="inline-flex items-center gap-1 rounded bg-panel-2 px-2 py-0.5 text-xs"
          >
            <TagDot color={colorOf(tag)} />
            {tag.name}
            {!disabled && (
              <button
                type="button"
                onClick={() => onChange(value.filter((v) => v.id !== tag.id))}
                aria-label={t("tags.remove", { name: tag.name })}
                className="text-muted hover:text-text"
              >
                <X size={12} />
              </button>
            )}
          </span>
        ))}
        {!disabled && (
          <input
            autoFocus={autoFocus}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={value.length ? "" : t("tags.placeholder")}
            className="min-w-24 flex-1 bg-transparent px-1 py-0.5 text-sm outline-none placeholder:text-muted"
            aria-label={t("tags.placeholder")}
            maxLength={64}
          />
        )}
      </div>
      {!disabled && (trimmed || options.length > 0) && (
        <div className="mt-1.5 space-y-1">
          {trimmed ? (
            group(options).map(({ category, tags }) => (
              <div key={category?.id ?? "other"} className="flex flex-wrap items-center gap-1.5">
                <span className="text-[10px] text-muted uppercase">
                  {category?.name ?? t("tags.other")}
                </span>
                {tags.map(suggestion)}
              </div>
            ))
          ) : (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] text-muted uppercase">{t("tags.recent")}</span>
              {options.map(suggestion)}
            </div>
          )}
          {trimmed && !exactMatch && (
            <button
              type="button"
              onClick={() => void create()}
              className="inline-flex items-center gap-1 rounded border border-dashed border-accent/50 px-2 py-0.5 text-xs text-accent hover:bg-accent/10"
            >
              <Plus size={12} /> {t("tags.create", { name: trimmed })}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
