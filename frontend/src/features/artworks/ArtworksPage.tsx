import { useNavigate, useSearch } from "@tanstack/react-router";
import { Cast, FileArchive, Frame, Heart, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ArtworkSort } from "@/api/client";
import { useArtworks, useBulkTags, type ArtworkFilter } from "@/api/queries";
import { ExportDialog } from "@/features/archive/ExportDialog";
import { AddToCollectionMenu } from "@/features/collections/AddToCollectionMenu";
import { ShowOnTvDialog } from "@/features/display/ShowOnTvDialog";
import { FilterBar } from "@/features/library/FilterBar";
import type { ChipFilter } from "@/features/library/filters";
import { useSelection } from "@/features/photos/useSelection";
import { TagMenu } from "@/features/tags/TagMenu";
import { useTrashWithUndo } from "@/features/trash/useTrashWithUndo";
import { Button } from "@/shared/ui/Button";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

import { ArtworkGrid } from "./ArtworkGrid";
import { ArtworkViewer } from "./ArtworkViewer";
import { useArtworkGridCommands } from "./useArtworkGridCommands";

const SORTS: ArtworkSort[] = ["created_desc", "created_asc", "updated_desc", "title_asc"];

interface ArtworksPageProps {
  /** The Favorites view is this page with one clause pinned on (docs/PLAN.md §14, Phase 9). */
  favoritesOnly?: boolean;
}

/** A filter to open the grid with — from the Places view (`place`) or the Tags page (`tag`). */
export interface ArtworksSearch {
  place?: string;
  tag?: string;
}

function chipsFrom(linked: ArtworksSearch): ChipFilter {
  return [
    ...(linked.place ? [{ field: "place" as const, op: "contains" as const, value: linked.place }] : []),
    ...(linked.tag ? [{ field: "tag" as const, op: "has_any" as const, value: [linked.tag] }] : []),
  ];
}

export function ArtworksPage({ favoritesOnly = false }: ArtworksPageProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  // `/artworks?place=Kyoto` (or `?tag=<id>`) opens the grid with that chip already in the bar;
  // following another such link while the page is open replaces the chips with the new one.
  const linked: ArtworksSearch = useSearch({ strict: false });
  const linkKey = `${linked.place ?? ""}\u001f${linked.tag ?? ""}`;
  const [chips, setChips] = useState<ChipFilter>(() => chipsFrom(linked));
  const [chipsFor, setChipsFor] = useState(linkKey);
  if (chipsFor !== linkKey) {
    setChipsFor(linkKey);
    setChips(chipsFrom(linked));
  }
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<ArtworkSort>("created_desc");
  const [openId, setOpenId] = useState<string | null>(null);

  const filter = useMemo<ArtworkFilter>(
    () => ({
      chips,
      sort,
      ...(search.trim() ? { q: search.trim() } : {}),
      ...(favoritesOnly ? { favorite: true } : {}),
    }),
    [chips, favoritesOnly, search, sort],
  );
  const artworks = useArtworks(filter);
  const items = useMemo(() => artworks.data?.pages.flatMap((p) => p.items) ?? [], [artworks.data]);
  const ids = useMemo(() => items.map((a) => a.id), [items]);
  const selection = useSelection(ids);
  const { selected, clear, selectAll, prune } = selection;
  useEffect(() => prune(new Set(ids)), [ids, prune]);

  const { trashArtworks } = useTrashWithUndo();
  const bulkTags = useBulkTags();
  const searchRef = useRef<HTMLInputElement>(null);
  const [collectionMenuOpen, setCollectionMenuOpen] = useState(false);
  const [tagMenuOpen, setTagMenuOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [showingOnTv, setShowingOnTv] = useState(false);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = artworks;
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const openEditor = useCallback(
    (id: string) => void navigate({ to: "/editor/$artworkId", params: { artworkId: id } }),
    [navigate],
  );

  const { selectedInOrder } = useArtworkGridCommands({
    items,
    selected,
    selectAll,
    clear,
    openEditor,
    openCollectionMenu: () => setCollectionMenuOpen(true),
    openTagMenu: () => setTagMenuOpen(true),
    focusSearch: () => searchRef.current?.focus(),
    suspended: openId !== null,
  });

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t(favoritesOnly ? "nav.favorites" : "nav.artworks")}
        subtitle={
          selected.size > 0
            ? t("artworks.selected", { count: selected.size })
            : artworks.data
              ? t("artworks.count", { count: items.length })
              : undefined
        }
        actions={
          <>
            <label className="flex items-center gap-2 rounded-md border border-border bg-bg px-2.5 py-1.5">
              <Search size={14} className="text-muted" />
              <input
                ref={searchRef}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t("artworks.searchPlaceholder")}
                className="w-52 bg-transparent text-sm outline-none placeholder:text-muted"
              />
            </label>
            {selected.size > 0 && (
              <>
                <AddToCollectionMenu
                  artworkIds={selectedInOrder}
                  open={collectionMenuOpen}
                  onOpenChange={setCollectionMenuOpen}
                  onDone={clear}
                />
                {/* Own tags only: an inherited tag belongs to a photo, and is removed there. */}
                <TagMenu
                  itemTags={items.filter((a) => selected.has(a.id)).map((a) => a.tags ?? [])}
                  hint={t("tags.inheritedNotListed")}
                  open={tagMenuOpen}
                  onOpenChange={setTagMenuOpen}
                  onChange={(change) =>
                    bulkTags.artworks.mutate({ artwork_ids: selectedInOrder, ...change })
                  }
                />
                <Button size="sm" variant="ghost" onClick={() => setShowingOnTv(true)}>
                  <Cast size={14} /> {t("display.showOnTv")}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setExporting(true)}>
                  <FileArchive size={14} /> {t("archive.exportSelection")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    void trashArtworks(selectedInOrder);
                    clear();
                  }}
                >
                  <Trash2 size={14} /> {t("trash.moveToTrash")}
                </Button>
              </>
            )}
          </>
        }
      />
      <FilterBar chips={chips} onChange={setChips}>
        <select
          value={sort}
          onChange={(event) => setSort(event.target.value as ArtworkSort)}
          aria-label={t("artworks.sort")}
          className="h-7 rounded border border-border bg-bg px-1.5 text-xs outline-none"
        >
          {SORTS.map((option) => (
            <option key={option} value={option}>
              {t(`artworks.sorts.${option}`)}
            </option>
          ))}
        </select>
      </FilterBar>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {artworks.isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner size={20} />
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={favoritesOnly ? <Heart size={40} /> : <Frame size={40} />}
            title={t(favoritesOnly ? "artworks.noFavoritesTitle" : "artworks.emptyTitle")}
            description={t(
              favoritesOnly ? "artworks.noFavoritesDescription" : "artworks.emptyDescription",
            )}
          />
        ) : (
          <ArtworkGrid
            items={items}
            selected={selected}
            onTileClick={(artwork, index, event) => selection.click(artwork.id, index, event)}
            onOpen={setOpenId}
            onEndReached={loadMore}
          />
        )}
      </div>
      {openId && (
        <ArtworkViewer
          artworkId={openId}
          ids={ids}
          onNavigate={setOpenId}
          onEdit={openEditor}
          onClose={() => setOpenId(null)}
        />
      )}
      {/* The picked artworks, in the order they were picked — the TV plays exactly them. */}
      <ShowOnTvDialog
        open={showingOnTv}
        onOpenChange={setShowingOnTv}
        label={t("display.selectionLabel", { count: selectedInOrder.length })}
        source={{ artwork_ids: selectedInOrder }}
      />
      {/* A partial archive of the selection (docs/archive-format.md §12.1) — the same dialog the
          Backup page opens for the whole library. */}
      <ExportDialog
        open={exporting}
        onOpenChange={setExporting}
        artworkIds={selectedInOrder}
      />
    </div>
  );
}
