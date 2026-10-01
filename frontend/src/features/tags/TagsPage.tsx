import { Link } from "@tanstack/react-router";
import { FolderInput, MapPin, Merge, Plus, Tags as TagsIcon, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagCategory, TagWithCount } from "@/api/client";
import {
  useAllTags,
  useCategorizeTags,
  useCreateTag,
  useDeleteTag,
  useDeleteUnusedTags,
  useMergeTags,
  useTagCategoryActions,
  useUnusedTags,
  useUpdateTag,
} from "@/api/queries";
import { cn } from "@/shared/cn";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

import { PlacesView } from "./PlacesView";
import { TagDot } from "./TagDot";
import { useTagCategoryIndex } from "./useTagCategories";

/** Six colours is enough to sort tags at a glance without becoming a palette editor. */
const COLORS = ["#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7", "#64748b"];
/** The `<select>` value meaning "no category". */
const OTHER = "";

type Tab = "tags" | "places";

/**
 * The tag manager (docs/organization.md §1), grouped by **category** — People, Events, Themes and
 * whatever the user adds; a tag with none is "Other". Rename, recolour, re-categorise (one or
 * many), merge and delete, with the counts that say what a deletion would take away, plus the
 * clean-up of tags nothing uses. The **Places** tab is the derived view of where photos were
 * taken: places are metadata, never tags.
 */
export function TagsPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("tags");
  const [query, setQuery] = useState("");
  const tags = useAllTags();
  const { categories, colorOf } = useTagCategoryIndex();
  const unused = useUnusedTags();
  const create = useCreateTag();
  const update = useUpdateTag();
  const merge = useMergeTags();
  const remove = useDeleteTag();
  const categorize = useCategorizeTags();
  const deleteUnused = useDeleteUnusedTags();
  const categoryActions = useTagCategoryActions();
  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState(OTHER);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [merging, setMerging] = useState<TagWithCount | null>(null);
  const [mergeTarget, setMergeTarget] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<TagWithCount | null>(null);
  const [confirmCategory, setConfirmCategory] = useState<TagCategory | null>(null);
  const [confirmUnused, setConfirmUnused] = useState(false);

  const all = useMemo(() => tags.data ?? [], [tags.data]);
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? all.filter((tag) => tag.name.toLowerCase().includes(needle)) : all;
  }, [all, query]);
  /** Every category — even an empty one, so it can be renamed or filled — then "Other". */
  const sections = useMemo(() => {
    const known = new Set(categories.map((c) => c.id));
    const of = (id: string | null) =>
      rows.filter((tag) =>
        id === null ? !tag.category_id || !known.has(tag.category_id) : tag.category_id === id,
      );
    return [
      ...categories.map((category) => ({ category, tags: of(category.id) })),
      { category: null, tags: of(null) },
    ];
  }, [categories, rows]);
  const selected = rows.filter((tag) => selectedIds.has(tag.id));
  const unusedCount = unused.data?.length ?? 0;

  const toggle = (id: string) =>
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const moveSelection = (value: string) => {
    if (selected.length === 0) return;
    categorize.mutate(
      { tag_ids: selected.map((tag) => tag.id), category_id: value === OTHER ? null : value },
      { onSuccess: () => setSelectedIds(new Set()) },
    );
  };

  const addTag = () => {
    const name = newName.trim();
    if (!name) return;
    create.mutate({ name, category_id: newCategory === OTHER ? null : newCategory });
    setNewName("");
  };

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("nav.tags")}
        subtitle={tab === "tags" ? t("tags.count", { count: all.length }) : t("places.subtitle")}
        actions={
          <div
            className="flex items-center gap-1 rounded-md border border-border p-0.5"
            role="tablist"
          >
            {(["tags", "places"] as Tab[]).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={tab === value}
                onClick={() => setTab(value)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-sm",
                  tab === value ? "bg-accent/15 text-accent" : "text-muted hover:text-text",
                )}
              >
                {value === "tags" ? <TagsIcon size={14} /> : <MapPin size={14} />}
                {t(value === "tags" ? "tags.tabTags" : "places.title")}
              </button>
            ))}
          </div>
        }
      />
      {tab === "places" ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <PlacesView />
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-2">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("tags.search")}
              aria-label={t("tags.search")}
              className="h-8 w-44 rounded-md border border-border bg-bg px-2.5 text-sm outline-none"
            />
            <form
              className="flex items-center gap-1.5"
              onSubmit={(event) => {
                event.preventDefault();
                addTag();
              }}
            >
              <input
                value={newName}
                maxLength={64}
                onChange={(event) => setNewName(event.target.value)}
                placeholder={t("tags.newPlaceholder")}
                aria-label={t("tags.newPlaceholder")}
                className="h-8 w-36 rounded-md border border-border bg-bg px-2.5 text-sm outline-none"
              />
              <select
                value={newCategory}
                onChange={(event) => setNewCategory(event.target.value)}
                aria-label={t("tags.category")}
                className="h-8 rounded-md border border-border bg-bg px-1.5 text-sm"
              >
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
                <option value={OTHER}>{t("tags.other")}</option>
              </select>
              <Button type="submit" size="sm" variant="primary" disabled={!newName.trim()}>
                {t("tags.add")}
              </Button>
            </form>
            <span className="flex-1" />
            {selected.length > 0 && (
              <label className="flex items-center gap-1.5 text-xs">
                <FolderInput size={14} className="text-muted" />
                {t("tags.moveSelected", { count: selected.length })}
                <select
                  value="__pick"
                  onChange={(event) => moveSelection(event.target.value)}
                  className="h-7 rounded border border-border bg-bg px-1.5 text-xs"
                >
                  <option value="__pick" disabled>
                    {t("filters.pick")}
                  </option>
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                  <option value={OTHER}>{t("tags.other")}</option>
                </select>
                <button
                  type="button"
                  onClick={() => setSelectedIds(new Set())}
                  aria-label={t("tags.clearSelection")}
                  className="rounded p-0.5 text-muted hover:text-text"
                >
                  <X size={13} />
                </button>
              </label>
            )}
            <Button
              size="sm"
              variant="ghost"
              disabled={unusedCount === 0}
              onClick={() => setConfirmUnused(true)}
              title={t("tags.unusedHint")}
            >
              <Trash2 size={14} /> {t("tags.deleteUnused", { count: unusedCount })}
            </Button>
          </div>

          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
            {tags.isLoading ? (
              <div className="flex h-full items-center justify-center">
                <Spinner size={20} />
              </div>
            ) : all.length === 0 && categories.length === 0 ? (
              <EmptyState
                icon={<TagsIcon size={40} />}
                title={t("tags.emptyTitle")}
                description={t("tags.emptyDescription")}
              />
            ) : (
              sections.map(({ category, tags: inSection }) => (
                <CategorySection
                  key={category?.id ?? "other"}
                  category={category}
                  tags={inSection}
                  hideWhenEmpty={query.trim().length > 0}
                  categories={categories}
                  selectedIds={selectedIds}
                  colorOf={colorOf}
                  onToggle={toggle}
                  onToggleAll={(ids, on) =>
                    setSelectedIds((current) => {
                      const next = new Set(current);
                      ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
                      return next;
                    })
                  }
                  onRenameCategory={(id, name) => categoryActions.update.mutate({ id, name })}
                  onRecolorCategory={(id, color) => categoryActions.update.mutate({ id, color })}
                  onDeleteCategory={setConfirmCategory}
                  onRename={(id, name) => update.mutateAsync({ id, name }).catch(() => undefined)}
                  onRecolor={(id, color) => update.mutate({ id, color })}
                  onMove={(id, value) =>
                    update.mutate({ id, category_id: value === OTHER ? null : value })
                  }
                  onMerge={(tag) => {
                    setMerging(tag);
                    setMergeTarget("");
                  }}
                  onDelete={setConfirmDelete}
                />
              ))
            )}
            <form
              className="flex items-center gap-1.5"
              onSubmit={(event) => {
                event.preventDefault();
                const name = newCategoryName.trim();
                if (!name) return;
                categoryActions.create.mutate({ name });
                setNewCategoryName("");
              }}
            >
              <input
                value={newCategoryName}
                maxLength={64}
                onChange={(event) => setNewCategoryName(event.target.value)}
                placeholder={t("tags.newCategoryPlaceholder")}
                aria-label={t("tags.newCategoryPlaceholder")}
                className="h-8 w-48 rounded-md border border-border bg-bg px-2.5 text-sm outline-none"
              />
              <Button type="submit" size="sm" variant="ghost" disabled={!newCategoryName.trim()}>
                <Plus size={14} /> {t("tags.newCategory")}
              </Button>
            </form>
          </div>
        </>
      )}

      <Dialog
        open={merging !== null}
        onOpenChange={(open) => !open && setMerging(null)}
        title={t("tags.mergeTitle", { name: merging?.name ?? "" })}
        description={t("tags.mergeHint", { name: merging?.name ?? "" })}
      >
        <div className="space-y-3">
          <select
            value={mergeTarget}
            onChange={(event) => setMergeTarget(event.target.value)}
            className="w-full rounded-md border border-border bg-bg px-2.5 py-1.5 text-sm"
          >
            <option value="">{t("tags.mergePick")}</option>
            {all
              .filter((tag) => tag.id !== merging?.id)
              .map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.name}
                </option>
              ))}
          </select>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setMerging(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="primary"
              disabled={!mergeTarget}
              onClick={() => {
                if (merging && mergeTarget) {
                  merge.mutate({ id: mergeTarget, source_ids: [merging.id] });
                }
                setMerging(null);
              }}
            >
              {t("tags.merge")}
            </Button>
          </div>
        </div>
      </Dialog>

      <Dialog
        open={confirmDelete !== null}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
        title={t("tags.deleteTitle", { name: confirmDelete?.name ?? "" })}
        description={t("tags.deleteHint", {
          photos: confirmDelete?.photo_count ?? 0,
          artworks: confirmDelete?.own_artwork_count ?? 0,
        })}
      >
        <div className="space-y-3">
          {/* An artwork carrying the tag only through its photos loses it too: say how many. */}
          {confirmDelete &&
            (confirmDelete.artwork_count ?? 0) > (confirmDelete.own_artwork_count ?? 0) && (
              <p className="text-sm text-muted">
                {t("tags.deleteInheritedHint", {
                  count:
                    (confirmDelete.artwork_count ?? 0) - (confirmDelete.own_artwork_count ?? 0),
                })}
              </p>
            )}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmDelete(null)}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (confirmDelete) remove.mutate(confirmDelete.id);
                setConfirmDelete(null);
              }}
            >
              {t("common.delete")}
            </Button>
          </div>
        </div>
      </Dialog>

      <Dialog
        open={confirmCategory !== null}
        onOpenChange={(open) => !open && setConfirmCategory(null)}
        title={t("tags.deleteCategoryTitle", { name: confirmCategory?.name ?? "" })}
        description={t("tags.deleteCategoryHint", { count: confirmCategory?.tag_count ?? 0 })}
      >
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmCategory(null)}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              if (confirmCategory) categoryActions.remove.mutate(confirmCategory.id);
              setConfirmCategory(null);
            }}
          >
            {t("common.delete")}
          </Button>
        </div>
      </Dialog>

      <Dialog
        open={confirmUnused}
        onOpenChange={setConfirmUnused}
        title={t("tags.deleteUnused", { count: unusedCount })}
        description={t("tags.unusedHint")}
      >
        <div className="space-y-3">
          <ul className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto text-xs">
            {(unused.data ?? []).map((tag) => (
              <li key={tag.id} className="rounded bg-panel-2 px-2 py-0.5">
                {tag.name}
              </li>
            ))}
          </ul>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmUnused(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                deleteUnused.mutate(undefined);
                setConfirmUnused(false);
              }}
            >
              {t("common.delete")}
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

interface CategorySectionProps {
  /** `null` is "Other": the tags with no category, which cannot be renamed or deleted. */
  category: TagCategory | null;
  tags: TagWithCount[];
  /** While searching, a category with no match is noise: hide it. */
  hideWhenEmpty: boolean;
  categories: TagCategory[];
  selectedIds: Set<string>;
  colorOf: (tag: TagWithCount) => string | null;
  onToggle: (id: string) => void;
  onToggleAll: (ids: string[], on: boolean) => void;
  onRenameCategory: (id: string, name: string) => void;
  onRecolorCategory: (id: string, color: string) => void;
  onDeleteCategory: (category: TagCategory) => void;
  onRename: (id: string, name: string) => Promise<unknown>;
  onRecolor: (id: string, color: string) => void;
  onMove: (id: string, value: string) => void;
  onMerge: (tag: TagWithCount) => void;
  onDelete: (tag: TagWithCount) => void;
}

function CategorySection({
  category,
  tags,
  hideWhenEmpty,
  categories,
  selectedIds,
  colorOf,
  onToggle,
  onToggleAll,
  onRenameCategory,
  onRecolorCategory,
  onDeleteCategory,
  onRename,
  onRecolor,
  onMove,
  onMerge,
  onDelete,
}: CategorySectionProps) {
  const { t } = useTranslation();
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  if (hideWhenEmpty && tags.length === 0) return null;
  const ids = tags.map((tag) => tag.id);
  const allOn = ids.length > 0 && ids.every((id) => selectedIds.has(id));
  const title = category?.name ?? t("tags.other");

  const commitCategory = () => {
    setRenaming(false);
    const name = draft.trim();
    if (category && name && name !== category.name) onRenameCategory(category.id, name);
  };
  const commitTag = async (tag: TagWithCount) => {
    const name = draftName.trim();
    setEditingId(null);
    if (name && name !== tag.name) await onRename(tag.id, name);
  };

  return (
    <section aria-label={title}>
      <header className="mb-1 flex flex-wrap items-center gap-2 border-b border-border pb-1">
        <input
          type="checkbox"
          checked={allOn}
          disabled={ids.length === 0}
          onChange={(event) => onToggleAll(ids, event.target.checked)}
          aria-label={t("tags.selectCategory", { name: title })}
        />
        <TagDot color={category?.color ?? null} className="size-2.5" />
        {category && renaming ? (
          <input
            autoFocus
            value={draft}
            maxLength={64}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={commitCategory}
            onKeyDown={(event) => {
              if (event.key === "Enter") commitCategory();
              if (event.key === "Escape") setRenaming(false);
            }}
            aria-label={t("tags.renameCategory")}
            className="h-7 w-40 rounded border border-border bg-bg px-1.5 text-sm font-semibold outline-none"
          />
        ) : category ? (
          <button
            type="button"
            onClick={() => {
              setDraft(category.name);
              setRenaming(true);
            }}
            title={t("tags.renameCategory")}
            className="rounded px-1 text-sm font-semibold hover:bg-panel-2"
          >
            {category.name}
          </button>
        ) : (
          <h2 className="px-1 text-sm font-semibold" title={t("tags.otherHint")}>
            {title}
          </h2>
        )}
        <span className="text-xs text-muted">{t("tags.count", { count: tags.length })}</span>
        <span className="flex-1" />
        {category && (
          <>
            <div className="flex items-center gap-1" aria-label={t("tags.categoryColor")}>
              {COLORS.map((color) => (
                <button
                  key={color}
                  type="button"
                  aria-label={color}
                  onClick={() =>
                    onRecolorCategory(category.id, category.color === color ? "" : color)
                  }
                  style={{ backgroundColor: color }}
                  className={cn(
                    "size-3.5 rounded-full border",
                    category.color === color ? "border-text" : "border-transparent",
                  )}
                />
              ))}
            </div>
            <Button
              size="sm"
              variant="ghost"
              title={t("tags.deleteCategory")}
              aria-label={t("tags.deleteCategory")}
              onClick={() => onDeleteCategory(category)}
            >
              <Trash2 size={13} />
            </Button>
          </>
        )}
      </header>
      {tags.length === 0 ? (
        <p className="px-1 py-1.5 text-xs text-muted">{t("tags.emptyCategory")}</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="sr-only">
            <tr>
              <th>{t("tags.select")}</th>
              <th>{t("tags.name")}</th>
              <th>{t("tags.color")}</th>
              <th>{t("tags.category")}</th>
              <th>{t("nav.photos")}</th>
              <th>{t("nav.artworks")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tags.map((tag) => {
              const inherited = (tag.artwork_count ?? 0) - (tag.own_artwork_count ?? 0);
              return (
                <tr key={tag.id} className="border-t border-border/60">
                  <td className="w-6 py-1">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(tag.id)}
                      onChange={() => onToggle(tag.id)}
                      aria-label={t("tags.selectTag", { name: tag.name })}
                    />
                  </td>
                  <td className="py-1 pr-3">
                    {editingId === tag.id ? (
                      <input
                        autoFocus
                        value={draftName}
                        maxLength={64}
                        onChange={(event) => setDraftName(event.target.value)}
                        onBlur={() => void commitTag(tag)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") void commitTag(tag);
                          if (event.key === "Escape") setEditingId(null);
                        }}
                        className="h-7 w-48 rounded border border-border bg-bg px-1.5 outline-none"
                      />
                    ) : (
                      <button
                        type="button"
                        onClick={() => {
                          setEditingId(tag.id);
                          setDraftName(tag.name);
                        }}
                        className="inline-flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-panel-2"
                      >
                        <TagDot color={colorOf(tag)} />
                        {tag.name}
                      </button>
                    )}
                  </td>
                  <td className="py-1 pr-3">
                    <div className="flex items-center gap-1">
                      {COLORS.map((color) => (
                        <button
                          key={color}
                          type="button"
                          aria-label={color}
                          title={t("tags.ownColor")}
                          onClick={() => onRecolor(tag.id, tag.color === color ? "" : color)}
                          style={{ backgroundColor: color }}
                          className={cn(
                            "size-3.5 rounded-full border",
                            tag.color === color ? "border-text" : "border-transparent",
                          )}
                        />
                      ))}
                    </div>
                  </td>
                  <td className="py-1 pr-3">
                    <select
                      value={tag.category_id ?? OTHER}
                      onChange={(event) => onMove(tag.id, event.target.value)}
                      aria-label={t("tags.categoryOf", { name: tag.name })}
                      className="h-7 rounded border border-border bg-bg px-1 text-xs"
                    >
                      {categories.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.name}
                        </option>
                      ))}
                      <option value={OTHER}>{t("tags.other")}</option>
                    </select>
                  </td>
                  <td className="py-1 text-right tabular-nums" title={t("nav.photos")}>
                    {tag.photo_count}
                  </td>
                  <td
                    className="py-1 text-right tabular-nums"
                    title={t("tags.artworkCountHint", {
                      own: tag.own_artwork_count ?? 0,
                      inherited,
                    })}
                  >
                    {(tag.artwork_count ?? 0) > 0 ? (
                      <Link
                        to="/artworks"
                        search={{ tag: tag.id }}
                        className="text-accent hover:underline"
                      >
                        {tag.artwork_count}
                      </Link>
                    ) : (
                      0
                    )}
                  </td>
                  <td className="py-1 text-right whitespace-nowrap">
                    <Button
                      size="sm"
                      variant="ghost"
                      title={t("tags.merge")}
                      aria-label={t("tags.merge")}
                      onClick={() => onMerge(tag)}
                    >
                      <Merge size={14} />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      title={t("common.delete")}
                      aria-label={t("common.delete")}
                      onClick={() => onDelete(tag)}
                    >
                      <Trash2 size={14} />
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
