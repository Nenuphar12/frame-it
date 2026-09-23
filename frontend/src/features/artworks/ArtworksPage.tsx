import { useNavigate } from "@tanstack/react-router";
import { Frame, Heart, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ArtworkSort } from "@/api/client";
import { useArtworks, useTrashActions, type ArtworkFilter } from "@/api/queries";
import { AddToCollectionMenu } from "@/features/collections/AddToCollectionMenu";
import { FilterBar } from "@/features/library/FilterBar";
import type { ChipFilter } from "@/features/library/filters";
import { useSelection } from "@/features/photos/useSelection";
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

export function ArtworksPage({ favoritesOnly = false }: ArtworksPageProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [chips, setChips] = useState<ChipFilter>([]);
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

  const { artworks: trashArtworks } = useTrashActions();
  const searchRef = useRef<HTMLInputElement>(null);
  const [collectionMenuOpen, setCollectionMenuOpen] = useState(false);
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
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    trashArtworks.mutate(selectedInOrder);
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
    </div>
  );
}
