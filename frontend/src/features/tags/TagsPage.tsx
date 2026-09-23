import { Merge, Tags as TagsIcon, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagWithCount } from "@/api/client";
import { ApiError } from "@/api/client";
import { useCreateTag, useDeleteTag, useMergeTags, useTags, useUpdateTag } from "@/api/queries";
import { cn } from "@/shared/cn";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

/** Six colours is enough to sort tags at a glance without becoming a palette editor. */
const COLORS = ["#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7", "#64748b"];

/**
 * The tag manager (docs/organization.md §1): rename, recolour, merge and delete, with the counts
 * that say what a deletion would actually take away.
 */
export function TagsPage() {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const tags = useTags(query.trim());
  const create = useCreateTag();
  const update = useUpdateTag();
  const merge = useMergeTags();
  const remove = useDeleteTag();
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [merging, setMerging] = useState<TagWithCount | null>(null);
  const [mergeTarget, setMergeTarget] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<TagWithCount | null>(null);
  const rows = useMemo(() => tags.data ?? [], [tags.data]);
  const error = update.error instanceof ApiError ? update.error.code : null;

  const rename = async (tag: TagWithCount) => {
    const name = draftName.trim();
    setEditingId(null);
    if (name && name !== tag.name) await update.mutateAsync({ id: tag.id, name }).catch(() => {});
  };

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("nav.tags")}
        subtitle={t("tags.count", { count: rows.length })}
        actions={
          <>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("tags.search")}
              className="h-9 w-48 rounded-md border border-border bg-bg px-2.5 text-sm outline-none"
            />
            <form
              className="flex gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (newName.trim()) {
                  create.mutate(newName.trim());
                  setNewName("");
                }
              }}
            >
              <input
                value={newName}
                maxLength={64}
                onChange={(event) => setNewName(event.target.value)}
                placeholder={t("tags.newPlaceholder")}
                className="h-9 w-40 rounded-md border border-border bg-bg px-2.5 text-sm outline-none"
              />
              <Button type="submit" variant="primary" disabled={!newName.trim()}>
                {t("tags.add")}
              </Button>
            </form>
          </>
        }
      />
      {error && <p className="px-5 pt-2 text-xs text-danger">{t(`errors.${error}`)}</p>}
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {tags.isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner size={20} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<TagsIcon size={40} />}
            title={t("tags.emptyTitle")}
            description={t("tags.emptyDescription")}
          />
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="py-1.5 font-medium">{t("tags.name")}</th>
                <th className="py-1.5 font-medium">{t("tags.color")}</th>
                <th className="py-1.5 text-right font-medium">{t("nav.photos")}</th>
                <th className="py-1.5 text-right font-medium">{t("nav.artworks")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((tag) => (
                <tr key={tag.id} className="border-t border-border">
                  <td className="py-1.5 pr-3">
                    {editingId === tag.id ? (
                      <input
                        autoFocus
                        value={draftName}
                        maxLength={64}
                        onChange={(event) => setDraftName(event.target.value)}
                        onBlur={() => void rename(tag)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") void rename(tag);
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
                        className="rounded px-1 py-0.5 hover:bg-panel-2"
                      >
                        {tag.name}
                      </button>
                    )}
                  </td>
                  <td className="py-1.5 pr-3">
                    <div className="flex items-center gap-1">
                      {COLORS.map((color) => (
                        <button
                          key={color}
                          type="button"
                          aria-label={color}
                          onClick={() =>
                            update.mutate({ id: tag.id, color: tag.color === color ? "" : color })
                          }
                          style={{ backgroundColor: color }}
                          className={cn(
                            "size-4 rounded-full border",
                            tag.color === color ? "border-text" : "border-transparent",
                          )}
                        />
                      ))}
                    </div>
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{tag.photo_count}</td>
                  <td className="py-1.5 text-right tabular-nums">{tag.artwork_count}</td>
                  <td className="py-1.5 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      title={t("tags.merge")}
                      aria-label={t("tags.merge")}
                      onClick={() => {
                        setMerging(tag);
                        setMergeTarget("");
                      }}
                    >
                      <Merge size={14} />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      title={t("common.delete")}
                      aria-label={t("common.delete")}
                      onClick={() => setConfirmDelete(tag)}
                    >
                      <Trash2 size={14} />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

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
            {rows
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
          artworks: confirmDelete?.artwork_count ?? 0,
        })}
      >
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
      </Dialog>
    </div>
  );
}
