import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  Cast,
  FileArchive,
  FolderMinus,
  FolderPlus,
  ImagePlus,
  Layers,
  Pencil,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ArtworkSort, ArtworkSummary, Collection } from "@/api/client";
import {
  useArtworks,
  useBulkTags,
  useCollectionItems,
  useCollections,
  useDeleteCollection,
  useMoveCollection,
} from "@/api/queries";
import { TagMenu } from "@/features/tags/TagMenu";
import { useRegisterCommands, type Command } from "@/app/commands";
import { ArtworkGrid } from "@/features/artworks/ArtworkGrid";
import { ArtworkViewer } from "@/features/artworks/ArtworkViewer";
import { useArtworkGridCommands } from "@/features/artworks/useArtworkGridCommands";

import { useSelection } from "@/features/photos/useSelection";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

import { ExportDialog } from "@/features/archive/ExportDialog";
import { ShowOnTvDialog } from "@/features/display/ShowOnTvDialog";

import { AddToCollectionMenu } from "./AddToCollectionMenu";
import { CollectionDialog } from "./CollectionDialog";
import { CollectionTree } from "./CollectionTree";
import { PickArtworksDialog } from "./PickArtworksDialog";

/** Manual order only means something inside one collection — never across a subtree (§2). */
const SORTS: ArtworkSort[] = ["manual", "created_desc", "created_asc", "updated_desc", "title_asc"];

/**
 * Collections: the tree on the left, the selected collection's artworks on the right.
 *
 * A manual collection keeps its own order (drag a card onto another to reorder); a smart one is a
 * saved filter and has no items of its own, so it offers neither reordering nor removal.
 */
export function CollectionsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const collections = useCollections();
  const rows = useMemo(() => collections.data ?? [], [collections.data]);
  // The open collection lives in the URL (`/collections?id=…`), so the sidebar can link straight
  // to one and a reload keeps it. A click writes the URL rather than local state.
  const search = useSearch({ from: "/shell/collections" });
  const selectedId = search.id ?? rows[0]?.id ?? null;
  const select = useCallback(
    (id: string | null) =>
      void navigate({ to: "/collections", search: id ? { id } : {}, replace: true }),
    [navigate],
  );
  const [includeNested, setIncludeNested] = useState(false);
  const [sort, setSort] = useState<ArtworkSort>("manual");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Collection | null>(null);
  const [creating, setCreating] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<Collection | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [showingOnTv, setShowingOnTv] = useState(false);

  const selected = rows.find((c) => c.id === selectedId) ?? null;
  const isManual = selected?.kind === "manual";
  const hasChildren = selected !== null && rows.some((c) => c.parent_id === selected.id);
  const move = useMoveCollection();
  const remove = useDeleteCollection();
  const items = useCollectionItems();

  // `manual` is only offered where it exists: a manual collection, showing its own items. The
  // server refuses the other combinations (`manual_sort`, `manual_sort_nested`) rather than
  // silently returning a different list, so the fallback happens here, visibly, in the picker.
  const manualOrder = isManual && !includeNested;
  const effectiveSort: ArtworkSort = sort === "manual" && !manualOrder ? "created_desc" : sort;
  // Nothing to list until a collection is picked, so no request at all: a placeholder id used to
  // ask the server for a collection that does not exist, and log a 404 on every visit.
  const artworks = useArtworks(
    selected
      ? { collection_id: selected.id, include_nested: includeNested, sort: effectiveSort }
      : {},
    { enabled: Boolean(selected) },
  );
  const found = useMemo<ArtworkSummary[]>(
    () => (selected ? (artworks.data?.pages.flatMap((p) => p.items) ?? []) : []),
    [artworks.data, selected],
  );
  const ids = useMemo(() => found.map((a) => a.id), [found]);
  const selection = useSelection(ids);
  const { selected: picked, clear, prune } = selection;
  useEffect(() => prune(new Set(ids)), [ids, prune]);

  const openEditor = useCallback(
    (id: string) => void navigate({ to: "/editor/$artworkId", params: { artworkId: id } }),
    [navigate],
  );

  const [collectionMenuOpen, setCollectionMenuOpen] = useState(false);
  const [tagMenuOpen, setTagMenuOpen] = useState(false);
  const bulkTags = useBulkTags();
  const removeFromCollection = useCallback(
    (artworkIds: string[]) => {
      if (selected && isManual) items.remove.mutate({ id: selected.id, artwork_ids: artworkIds });
    },
    [isManual, items.remove, selected],
  );
  const { selectedInOrder } = useArtworkGridCommands({
    items: found,
    selected: picked,
    selectAll: selection.selectAll,
    clear,
    openEditor,
    openCollectionMenu: () => setCollectionMenuOpen(true),
    openTagMenu: () => setTagMenuOpen(true),
    removeFromCollection: isManual ? removeFromCollection : undefined,
    suspended: openId !== null,
  });
  const commands = useMemo<Command[]>(
    () => [
      {
        id: "collections.new",
        label: "collections.new",
        group: "commands.groups.library",
        shortcut: openId === null ? "Shift+N" : undefined,
        run: () => setCreating(true),
      },
    ],
    [openId],
  );
  useRegisterCommands(commands);

  return (
    <div className="flex h-full">
      <aside className="flex w-64 shrink-0 flex-col border-r border-border">
        <div className="flex items-center gap-1 border-b border-border px-2.5 py-2">
          <span className="flex-1 text-sm font-semibold">{t("nav.collections")}</span>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setCreating(true)}
            title={t("collections.new")}
            aria-label={t("collections.new")}
          >
            <FolderPlus size={15} />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
          {rows.length === 0 ? (
            <p className="px-2 py-4 text-xs text-muted">{t("collections.emptyTree")}</p>
          ) : (
            <CollectionTree
              rows={rows}
              selectedId={selectedId}
              onSelect={select}
              onMove={(id, parentId, beforeId) =>
                move.mutate({ id, parent_id: parentId, before_id: beforeId })
              }
              onDropArtworks={(collectionId, artworkIds) =>
                items.add.mutate({ id: collectionId, artwork_ids: artworkIds })
              }
            />
          )}
          {move.isError && (
            <p className="px-2 py-1 text-xs text-danger">{t("errors.collection_cycle")}</p>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader
          title={selected?.name ?? t("nav.collections")}
          subtitle={
            selected
              ? selected.description ||
                t("collections.count", {
                  count: includeNested ? selected.nested_count : selected.item_count,
                })
              : undefined
          }
          actions={
            selected && (
              <>
                {hasChildren && (
                  <label
                    className="flex items-center gap-1.5 text-xs text-muted"
                    title={t("collections.includeNestedHint")}
                  >
                    <input
                      type="checkbox"
                      checked={includeNested}
                      onChange={(event) => setIncludeNested(event.target.checked)}
                    />
                    {t("collections.includeNested")}
                  </label>
                )}
                <select
                  value={effectiveSort}
                  onChange={(event) => setSort(event.target.value as ArtworkSort)}
                  aria-label={t("artworks.sort")}
                  className="h-7 rounded border border-border bg-bg px-1.5 text-xs outline-none"
                >
                  {SORTS.filter((option) => option !== "manual" || manualOrder).map((option) => (
                    <option key={option} value={option}>
                      {t(`artworks.sorts.${option}`)}
                    </option>
                  ))}
                </select>
                {isManual && (
                  <Button size="sm" variant="ghost" onClick={() => setAdding(true)}>
                    <ImagePlus size={14} /> {t("collections.addArtworks")}
                  </Button>
                )}
                {picked.size > 0 && (
                  <AddToCollectionMenu
                    artworkIds={selectedInOrder}
                    open={collectionMenuOpen}
                    onOpenChange={setCollectionMenuOpen}
                    onDone={clear}
                  />
                )}
                {picked.size > 0 && (
                  <TagMenu
                    itemTags={found.filter((a) => picked.has(a.id)).map((a) => a.tags ?? [])}
                    hint={t("tags.inheritedNotListed")}
                    open={tagMenuOpen}
                    onOpenChange={setTagMenuOpen}
                    onChange={(change) =>
                      bulkTags.artworks.mutate({ artwork_ids: selectedInOrder, ...change })
                    }
                  />
                )}
                {picked.size > 0 && isManual && (
                  <Button
                    size="sm"
                    variant="ghost"
                    title={t("collections.removeHint")}
                    onClick={() => {
                      removeFromCollection(selectedInOrder);
                      clear();
                    }}
                  >
                    <FolderMinus size={14} /> {t("collections.removeItems", { count: picked.size })}
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setShowingOnTv(true)}>
                  <Cast size={14} /> {t("display.showOnTv")}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setExporting(true)}>
                  <FileArchive size={14} /> {t("archive.exportTitle")}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(selected)}>
                  <Pencil size={14} /> {t("common.edit")}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(selected)}>
                  <Trash2 size={14} /> {t("common.delete")}
                </Button>
              </>
            )
          }
        />
        {selected?.kind === "smart" && (
          <p className="flex items-center gap-1.5 border-b border-border px-5 py-1.5 text-xs text-muted">
            <Sparkles size={12} className="text-accent" />
            {t("collections.smartReadOnly")}
          </p>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {!selected ? (
            <EmptyState
              icon={<Layers size={40} />}
              title={t("collections.emptyTitle")}
              description={t("collections.emptyDescription")}
              action={
                <Button variant="primary" onClick={() => setCreating(true)}>
                  {t("collections.new")}
                </Button>
              }
            />
          ) : artworks.isLoading ? (
            <div className="flex h-full items-center justify-center">
              <Spinner size={20} />
            </div>
          ) : found.length === 0 ? (
            <EmptyState
              icon={<Layers size={40} />}
              title={t("collections.noItemsTitle")}
              description={t(
                selected.kind === "smart" ? "collections.noMatches" : "collections.dropHint",
              )}
            />
          ) : (
            <ArtworkGrid
              items={found}
              selected={picked}
              onTileClick={(artwork, index, event) => selection.click(artwork.id, index, event)}
              onOpen={setOpenId}
              onEndReached={() => {
                if (artworks.hasNextPage && !artworks.isFetchingNextPage) {
                  void artworks.fetchNextPage();
                }
              }}
              onReorder={
                manualOrder && effectiveSort === "manual"
                  ? (artworkId, beforeId) =>
                      items.reorder.mutate({
                        id: selected.id,
                        artwork_id: artworkId,
                        before_id: beforeId,
                      })
                  : undefined
              }
            />
          )}
        </div>
      </div>

      {/* The TV plays what a collection holds, in its manual order when it has one (§4). */}
      <ShowOnTvDialog
        open={showingOnTv}
        onOpenChange={setShowingOnTv}
        label={selected?.name ?? ""}
        source={{
          collection_id: selected?.id ?? null,
          include_nested: includeNested,
          sort: effectiveSort,
        }}
      />
      {/* A collection is a natural export selection: its artworks, their photos and their tags. */}
      <ExportDialog
        open={exporting}
        onOpenChange={setExporting}
        collectionIds={selected ? [selected.id] : []}
      />
      {/* New collections land at the top level by default; the dialog's own picker nests them
          (a "+" next to the selected collection used to be the *only* way, remarks.md #4), and
          its first choice is the kind — one button for both (remarks.md #24). */}
      <CollectionDialog
        open={creating}
        onOpenChange={setCreating}
        kind="manual"
        parentId={null}
        onSaved={select}
      />
      <CollectionDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        collection={editing ?? undefined}
        kind={editing?.kind ?? "manual"}
      />
      <Dialog
        open={confirmDelete !== null}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
        title={t("collections.deleteTitle", { name: confirmDelete?.name ?? "" })}
        description={t("collections.deleteHint")}
      >
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmDelete(null)}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              if (confirmDelete) {
                remove.mutate(confirmDelete.id);
                if (selectedId === confirmDelete.id) select(null);
              }
              setConfirmDelete(null);
            }}
          >
            {t("common.delete")}
          </Button>
        </div>
      </Dialog>
      {selected && isManual && (
        <PickArtworksDialog
          collectionId={selected.id}
          collectionName={selected.name}
          alreadyIn={ids}
          open={adding}
          onOpenChange={setAdding}
        />
      )}
      {openId && (
        <ArtworkViewer
          artworkId={openId}
          ids={ids}
          onNavigate={setOpenId}
          onEdit={openEditor}
          onClose={() => setOpenId(null)}
        />
      )}
    </div>
  );
}
