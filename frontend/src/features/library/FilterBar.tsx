import * as Popover from "@radix-ui/react-popover";
import { Filter, Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAllTags, useCollections } from "@/api/queries";
import { TagOptions } from "@/features/tags/TagOptions";
import { cn } from "@/shared/cn";
import { Button } from "@/shared/ui/Button";

import {
  CHIP_FIELDS,
  FIELD_OPS,
  TIERS,
  defaultClause,
  type ChipFilter,
  type FilterClause,
  type FilterField,
} from "./filters";

interface FilterBarProps {
  chips: ChipFilter;
  onChange: (chips: ChipFilter) => void;
  /** Extra controls on the right of the bar (sort, view switches…). */
  children?: React.ReactNode;
}

const input =
  "h-7 rounded border border-border bg-bg px-1.5 text-xs outline-none focus:border-accent";

/**
 * The library filter bar: one chip per clause, joined by `and` (docs/data-model.md §5.2).
 *
 * The chips *are* the AST the server compiles, which is what makes "save as a smart collection"
 * a one-liner: the same object goes into `collections.filter`.
 */
export function FilterBar({ chips, onChange, children }: FilterBarProps) {
  const { t } = useTranslation();
  // Every tag, not the autocomplete's first twenty: a filter must reach any of them.
  const tags = useAllTags();
  const collections = useCollections();

  const patch = (index: number, next: Partial<FilterClause>) =>
    onChange(chips.map((chip, n) => (n === index ? { ...chip, ...next } : chip)));
  const remove = (index: number) => onChange(chips.filter((_, n) => n !== index));

  const values = (chip: FilterClause): string[] =>
    Array.isArray(chip.value) ? chip.value.map(String) : [];

  const renderValue = (chip: FilterClause, index: number) => {
    switch (chip.field) {
      case "favorite":
      case "is_incomplete":
        return (
          <select
            className={input}
            value={String(chip.value)}
            onChange={(event) => patch(index, { value: event.target.value === "true" })}
          >
            <option value="true">{t("common.yes")}</option>
            <option value="false">{t("common.no")}</option>
          </select>
        );
      case "status":
        return (
          <select
            className={input}
            value={String(chip.value)}
            onChange={(event) => patch(index, { value: event.target.value })}
          >
            <option value="draft">{t("artworks.statuses.draft")}</option>
            <option value="ready">{t("artworks.statuses.ready")}</option>
          </select>
        );
      case "worst_tier":
        return (
          <select
            className={input}
            value={values(chip)[0] ?? "upscaled"}
            onChange={(event) => patch(index, { value: [event.target.value] })}
          >
            {TIERS.map((tier) => (
              <option key={tier} value={tier}>
                {t(`artworks.tiers.${tier}`)}
              </option>
            ))}
          </select>
        );
      case "tag":
        return (
          <select
            className={input}
            value={values(chip)[0] ?? ""}
            onChange={(event) => patch(index, { value: [event.target.value] })}
          >
            <option value="">{t("filters.pick")}</option>
            {/* An artwork carries its own tags and its photos': the count is that union. */}
            <TagOptions tags={tags.data ?? []} count={(tag) => tag.artwork_count} />
          </select>
        );
      case "collection":
        return (
          <>
            <select
              className={input}
              value={values(chip)[0] ?? ""}
              onChange={(event) => patch(index, { value: [event.target.value] })}
            >
              <option value="">{t("filters.pick")}</option>
              {(collections.data ?? []).map((collection) => (
                <option key={collection.id} value={collection.id}>
                  {collection.name}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-[11px] text-muted">
              <input
                type="checkbox"
                checked={chip.include_nested ?? false}
                onChange={(event) => patch(index, { include_nested: event.target.checked })}
              />
              {t("collections.includeNested")}
            </label>
          </>
        );
      case "taken_at":
      case "created_at": {
        const [from = "", to = ""] = values(chip);
        if (chip.op === "between") {
          return (
            <>
              <input
                type="date"
                className={input}
                value={from}
                onChange={(event) => patch(index, { value: [event.target.value, to] })}
              />
              <span className="text-[11px] text-muted">→</span>
              <input
                type="date"
                className={input}
                value={to}
                onChange={(event) => patch(index, { value: [from, event.target.value] })}
              />
            </>
          );
        }
        return (
          <input
            type="date"
            className={input}
            value={typeof chip.value === "string" ? chip.value : ""}
            onChange={(event) => patch(index, { value: event.target.value })}
          />
        );
      }
      case "photo_count":
        return (
          <input
            type="number"
            min={0}
            max={32}
            className={cn(input, "w-16")}
            value={Number(chip.value)}
            onChange={(event) => patch(index, { value: Number(event.target.value) })}
          />
        );
      default:
        return (
          <input
            className={cn(input, "w-32")}
            value={String(chip.value)}
            placeholder={t("filters.value")}
            onChange={(event) => patch(index, { value: event.target.value })}
          />
        );
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-2">
      <Filter size={14} className="text-muted" />
      {chips.map((chip, index) => (
        <span
          key={`${chip.field}-${index}`}
          className="flex items-center gap-1.5 rounded-md border border-border bg-panel px-2 py-1"
        >
          <span className="text-xs font-medium">{t(`filters.fields.${chip.field}`)}</span>
          {FIELD_OPS[chip.field].length > 1 && (
            <select
              className={input}
              value={chip.op}
              onChange={(event) => {
                const op = event.target.value as FilterClause["op"];
                const reset = op === "between" ? { value: ["", ""] } : {};
                patch(index, { op, ...reset });
              }}
            >
              {FIELD_OPS[chip.field].map((op) => (
                <option key={op} value={op}>
                  {t(`filters.ops.${op}`)}
                </option>
              ))}
            </select>
          )}
          {renderValue(chip, index)}
          <button
            type="button"
            onClick={() => remove(index)}
            aria-label={t("filters.remove")}
            className="text-muted hover:text-text"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      <Popover.Root>
        <Popover.Trigger asChild>
          <Button variant="ghost" size="sm">
            <Plus size={14} /> {t("filters.add")}
          </Button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            onEscapeKeyDown={(event) => event.stopPropagation()}
            sideOffset={6}
            className="z-50 w-48 rounded-md border border-border bg-panel p-1 shadow-xl"
          >
            {CHIP_FIELDS.map((field: FilterField) => (
              <Popover.Close key={field} asChild>
                <button
                  type="button"
                  onClick={() => onChange([...chips, defaultClause(field)])}
                  className="block w-full rounded px-2 py-1.5 text-left text-sm hover:bg-panel-2"
                >
                  {t(`filters.fields.${field}`)}
                </button>
              </Popover.Close>
            ))}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      {chips.length > 0 && (
        <Button variant="ghost" size="sm" onClick={() => onChange([])}>
          {t("filters.clear")}
        </Button>
      )}
      <div className="ml-auto flex items-center gap-2">{children}</div>
    </div>
  );
}
