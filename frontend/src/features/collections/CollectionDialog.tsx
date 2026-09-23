import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Collection } from "@/api/client";
import {
  useCollections,
  useCreateCollection,
  useMoveCollection,
  useUpdateCollection,
  useValidateFilter,
} from "@/api/queries";
import { FilterBar } from "@/features/library/FilterBar";
import { toChips, toGroup, type ChipFilter, type FilterGroup } from "@/features/library/filters";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";

import { subtreeIds } from "./tree";

/**
 * The dialog owns the mounting: the form's state is initialized from the collection once, so
 * opening it on another collection has to remount it (`key`) rather than reset it in an effect.
 */
export function CollectionDialog(props: CollectionDialogProps) {
  if (!props.open) return null;
  return <CollectionForm key={props.collection?.id ?? "new"} {...props} />;
}

interface CollectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Editing an existing collection, or creating one under this parent. */
  collection?: Collection;
  /** Pre-selected parent for a new collection; `null` (the default) means the top level. */
  parentId?: string | null;
  kind: "manual" | "smart";
  onSaved?: (id: string) => void;
}

const field = "w-full rounded-md border border-border bg-bg px-2.5 py-1.5 text-sm outline-none";

/**
 * Create or edit a collection. A smart one carries a filter, edited with the same chip bar as the
 * library — the AST it produces *is* what gets saved (docs/data-model.md §5.2), and the live
 * match count comes from `POST /filters/validate`, i.e. from the server that will run it.
 */
function CollectionForm({
  open,
  onOpenChange,
  collection,
  parentId = null,
  kind,
  onSaved,
}: CollectionDialogProps) {
  const { t } = useTranslation();
  const create = useCreateCollection();
  const update = useUpdateCollection();
  const move = useMoveCollection();
  const collections = useCollections();
  const [name, setName] = useState(collection?.name ?? "");
  const [description, setDescription] = useState(collection?.description ?? "");
  const [dateStart, setDateStart] = useState(collection?.date_start ?? "");
  const [dateEnd, setDateEnd] = useState(collection?.date_end ?? "");
  const [chips, setChips] = useState<ChipFilter>(() =>
    toChips(collection?.filter as FilterGroup | null | undefined),
  );
  const [parent, setParent] = useState<string>(collection?.parent_id ?? parentId ?? "");
  const effectiveKind = collection?.kind ?? kind;
  // A smart collection holds no children, and nothing may become its own descendant.
  const descendants = useMemo(
    () => (collection ? new Set(subtreeIds(collections.data ?? [], collection.id)) : new Set()),
    [collection, collections.data],
  );
  const parents = (collections.data ?? []).filter(
    (c) => c.kind === "manual" && !descendants.has(c.id),
  );
  const group = toGroup(chips);
  const validation = useValidateFilter(effectiveKind === "smart" ? (group ?? emptyGroup) : undefined);

  const busy = create.isPending || update.isPending || move.isPending;
  const canSave = name.trim().length > 0 && !busy;

  const submit = async () => {
    if (!canSave) return;
    const filter = effectiveKind === "smart" ? (group ?? emptyGroup) : undefined;
    if (collection) {
      await update.mutateAsync({
        id: collection.id,
        name,
        description,
        date_start: dateStart,
        date_end: dateEnd,
        filter,
      });
      // Re-parenting is its own endpoint (it has to check cycles and pick a position).
      if ((collection.parent_id ?? "") !== parent) {
        await move.mutateAsync({ id: collection.id, parent_id: parent || null });
      }
      onSaved?.(collection.id);
    } else {
      const created = await create.mutateAsync({
        name,
        parent_id: parent || null,
        kind: effectiveKind,
        description,
        filter,
      });
      onSaved?.(created.id);
    }
    onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t(
        collection
          ? "collections.edit"
          : effectiveKind === "smart"
            ? "collections.newSmart"
            : "collections.new",
      )}
      description={effectiveKind === "smart" ? t("collections.smartHint") : undefined}
      className={effectiveKind === "smart" ? "w-[min(94vw,52rem)]" : undefined}
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="block space-y-1">
          <span className="text-xs text-muted">{t("collections.name")}</span>
          <input
            autoFocus
            value={name}
            maxLength={256}
            onChange={(event) => setName(event.target.value)}
            className={field}
          />
        </label>
        <label className="block space-y-1">
          <span className="text-xs text-muted">{t("collections.parent")}</span>
          <select
            value={parent}
            onChange={(event) => setParent(event.target.value)}
            className={field}
          >
            <option value="">{t("collections.topLevel")}</option>
            {parents.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block space-y-1">
          <span className="text-xs text-muted">{t("collections.description")}</span>
          <textarea
            value={description}
            rows={2}
            onChange={(event) => setDescription(event.target.value)}
            className={field}
          />
        </label>
        <div className="flex gap-3">
          <label className="flex-1 space-y-1">
            <span className="text-xs text-muted">{t("collections.dateStart")}</span>
            <input
              type="date"
              value={dateStart}
              onChange={(event) => setDateStart(event.target.value)}
              className={field}
            />
          </label>
          <label className="flex-1 space-y-1">
            <span className="text-xs text-muted">{t("collections.dateEnd")}</span>
            <input
              type="date"
              value={dateEnd}
              onChange={(event) => setDateEnd(event.target.value)}
              className={field}
            />
          </label>
        </div>
        {effectiveKind === "smart" && (
          <div className="space-y-1">
            <span className="text-xs text-muted">{t("collections.filter")}</span>
            <div className="rounded-md border border-border">
              <FilterBar chips={chips} onChange={setChips} />
            </div>
            <p className="text-xs text-muted">
              {validation.data?.valid === false
                ? validation.data.error
                : t("collections.matches", { count: validation.data?.match_count ?? 0 })}
            </p>
          </div>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" variant="primary" disabled={!canSave}>
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

const emptyGroup: FilterGroup = { op: "and", clauses: [] };
