import { Plus, X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Tag } from "@/api/client";
import { useCreateTag, useTags } from "@/api/queries";

interface TagPickerProps {
  value: Tag[];
  onChange: (tags: Tag[]) => void;
  disabled?: boolean;
}

/** Chips + autocomplete input; Enter picks the first suggestion or creates the tag. */
export function TagPicker({ value, onChange, disabled }: TagPickerProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const suggestions = useTags(query.trim());
  const createTag = useCreateTag();
  const chosen = new Set(value.map((tag) => tag.id));
  const options = (suggestions.data ?? []).filter((tag) => !chosen.has(tag.id)).slice(0, 6);
  const trimmed = query.trim();
  const exactMatch = options.some((tag) => tag.name.toLowerCase() === trimmed.toLowerCase());

  const add = (tag: Tag) => {
    onChange([...value, { id: tag.id, name: tag.name, color: tag.color }]);
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
    }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-border bg-bg p-1.5">
        {value.map((tag) => (
          <span
            key={tag.id}
            className="inline-flex items-center gap-1 rounded bg-panel-2 px-2 py-0.5 text-xs"
          >
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
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {options.map((tag) => (
            <button
              key={tag.id}
              type="button"
              onClick={() => add(tag)}
              className="rounded border border-border px-2 py-0.5 text-xs text-muted hover:bg-panel-2 hover:text-text"
            >
              {tag.name}
            </button>
          ))}
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
