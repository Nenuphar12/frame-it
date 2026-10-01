import * as Popover from "@radix-ui/react-popover";
import { Check, Minus, Plus, Tag as TagIcon } from "lucide-react";
import { forwardRef, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Tag, TagWithCount } from "@/api/client";
import { useAllTags, useCreateTag, useTags } from "@/api/queries";
import { cn } from "@/shared/cn";
import { Button } from "@/shared/ui/Button";

import { TagDot } from "./TagDot";
import { useTagCategoryIndex } from "./useTagCategories";

export interface TagChange {
  add?: string[];
  remove?: string[];
}

interface TagMenuProps {
  /** The tags each selected item carries — what decides a row's state (all / some / none). */
  itemTags: readonly (readonly Tag[])[];
  onChange: (change: TagChange) => void;
  /** A line under the list (e.g. that an artwork's inherited tags are not listed here). */
  hint?: string;
  trigger?: ReactNode;
  disabled?: boolean;
  /** Opened by a shortcut rather than the trigger (the trigger stays the anchor). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

type State = "all" | "some" | "none";

const RECENT = 6;

/**
 * Tag many photos or artworks at once (docs/organization.md §1). Each row says whether **all**,
 * **some** or **none** of the selection carry the tag; a click adds it to all of them, or — when
 * they all have it — removes it from all of them. Additive by construction: nothing else moves.
 */
export const TagMenu = forwardRef<HTMLButtonElement, TagMenuProps>(function TagMenu(
  { itemTags, onChange, hint, trigger, disabled, open, onOpenChange },
  ref,
) {
  const { t } = useTranslation();
  const all = useAllTags();
  const recent = useTags("", { sort: "recent", limit: RECENT });
  const createTag = useCreateTag();
  const { group, colorOf } = useTagCategoryIndex();
  const [query, setQuery] = useState("");
  const trimmed = query.trim();

  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const tags of itemTags) {
      for (const tag of new Set(tags.map((x) => x.id))) map.set(tag, (map.get(tag) ?? 0) + 1);
    }
    return map;
  }, [itemTags]);
  const total = itemTags.length;
  const stateOf = (id: string): State => {
    const count = counts.get(id) ?? 0;
    return count === 0 ? "none" : count >= total ? "all" : "some";
  };

  const tags = useMemo(() => all.data ?? [], [all.data]);
  const matches = useMemo(
    () =>
      trimmed ? tags.filter((tag) => tag.name.toLowerCase().includes(trimmed.toLowerCase())) : [],
    [tags, trimmed],
  );
  const exact = tags.some((tag) => tag.name.toLowerCase() === trimmed.toLowerCase());
  const recentTags = (recent.data ?? []).filter((tag) => tag.last_used_at);

  const toggle = (tag: Tag) => {
    if (stateOf(tag.id) === "all") onChange({ remove: [tag.id] });
    else onChange({ add: [tag.id] });
  };
  const create = async () => {
    if (!trimmed) return;
    const tag = await createTag.mutateAsync(trimmed);
    setQuery("");
    onChange({ add: [tag.id] });
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const first = matches[0];
    if (first && (exact || matches.length === 1)) toggle(first);
    else if (trimmed && !exact) void create();
  };

  const row = (tag: TagWithCount, keyPrefix: string) => {
    const state = stateOf(tag.id);
    return (
      <button
        key={`${keyPrefix}-${tag.id}`}
        type="button"
        role="menuitemcheckbox"
        aria-checked={state === "all" ? true : state === "some" ? "mixed" : false}
        onClick={() => toggle(tag)}
        className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm hover:bg-panel-2"
      >
        <span
          className={cn(
            "flex size-3.5 shrink-0 items-center justify-center rounded-sm border",
            state === "none"
              ? "border-border-strong"
              : "border-accent bg-accent text-accent-contrast",
          )}
        >
          {state === "all" && <Check size={10} strokeWidth={3} />}
          {state === "some" && <Minus size={10} strokeWidth={3} />}
        </span>
        <TagDot color={colorOf(tag)} />
        <span className="min-w-0 flex-1 truncate">{tag.name}</span>
        {state === "some" && (
          <span className="text-[11px] text-muted tabular-nums">
            {counts.get(tag.id)}/{total}
          </span>
        )}
      </button>
    );
  };

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) setQuery("");
        onOpenChange?.(next);
      }}
    >
      <Popover.Trigger asChild ref={ref}>
        {trigger ?? (
          <Button size="sm" variant="ghost" disabled={disabled || total === 0}>
            <TagIcon size={14} /> {t("tags.tagSelection")}
          </Button>
        )}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          // `Escape` closes the menu, not the page's selection behind it.
          onEscapeKeyDown={(event) => event.stopPropagation()}
          sideOffset={6}
          align="end"
          className="z-50 w-72 rounded-md border border-border bg-panel p-1 shadow-xl"
        >
          <input
            autoFocus
            value={query}
            maxLength={64}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={t("tags.menuPlaceholder")}
            aria-label={t("tags.menuPlaceholder")}
            className="mb-1 w-full rounded border border-border bg-bg px-2 py-1 text-sm outline-none placeholder:text-muted focus:border-accent"
          />
          <div className="max-h-72 overflow-y-auto" role="menu">
            {trimmed ? (
              <>
                {group(matches).map(({ category, tags: inGroup }) => (
                  <div key={category?.id ?? "other"}>
                    <p className="px-2 pt-1.5 pb-0.5 text-[10px] text-muted uppercase">
                      {category?.name ?? t("tags.other")}
                    </p>
                    {inGroup.map((tag) => row(tag, "match"))}
                  </div>
                ))}
                {!exact && (
                  <button
                    type="button"
                    onClick={() => void create()}
                    className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm text-accent hover:bg-accent/10"
                  >
                    <Plus size={13} /> {t("tags.createAndAdd", { name: trimmed })}
                  </button>
                )}
              </>
            ) : (
              <>
                {recentTags.length > 0 && (
                  <div>
                    <p className="px-2 pt-1.5 pb-0.5 text-[10px] text-muted uppercase">
                      {t("tags.recent")}
                    </p>
                    {recentTags.map((tag) => row(tag, "recent"))}
                  </div>
                )}
                {group(tags).map(({ category, tags: inGroup }) => (
                  <div key={category?.id ?? "other"}>
                    <p className="px-2 pt-1.5 pb-0.5 text-[10px] text-muted uppercase">
                      {category?.name ?? t("tags.other")}
                    </p>
                    {inGroup.map((tag) => row(tag, "all"))}
                  </div>
                ))}
                {tags.length === 0 && <p className="p-2 text-xs text-muted">{t("tags.none")}</p>}
              </>
            )}
          </div>
          {hint && (
            <p className="border-t border-border px-2 pt-1.5 pb-1 text-[11px] text-muted">{hint}</p>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
});
