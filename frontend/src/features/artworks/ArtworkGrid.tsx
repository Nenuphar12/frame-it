import { GripVertical, Heart } from "lucide-react";
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { useTranslation } from "react-i18next";

import { artworkThumbUrl, type ArtworkSummary } from "@/api/client";
import { useArtworkActions } from "@/api/queries";
import { cn } from "@/shared/cn";
import { ARTWORK_MIME, startInternalDrag } from "@/shared/dnd";

import { ArtworkBadges } from "./ArtworkBadges";

interface ArtworkGridProps {
  items: ArtworkSummary[];
  selected: Set<string>;
  onTileClick: (artwork: ArtworkSummary, index: number, event: MouseEvent) => void;
  onOpen: (id: string) => void;
  onEndReached?: () => void;
  /**
   * Manual order inside a collection. `beforeId` is the artwork to land in front of, `null` = last
   * — the grid works out which from the drag's direction, so dragging right actually moves right.
   */
  onReorder?: (artworkId: string, beforeId: string | null) => void;
}

/**
 * The artwork grid, shared by Artworks, Favorites and a collection's page.
 *
 * Cards carry the selection (the bulk bar acts on it), the favourite heart, and an HTML drag
 * stamped `ARTWORK_MIME` so the collections tree can accept a drop — `shared/dnd.ts` explains why
 * every internal drag has to stamp itself.
 */
export function ArtworkGrid({
  items,
  selected,
  onTileClick,
  onOpen,
  onEndReached,
  onReorder,
}: ArtworkGridProps) {
  const { t } = useTranslation();
  const { update } = useArtworkActions();
  const sentinel = useRef<HTMLDivElement>(null);
  const dragged = useRef<string[] | null>(null);
  /** The card the pointer is over while dragging, so the drop has a visible target. */
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  useEffect(() => {
    const element = sentinel.current;
    if (!element || !onEndReached) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting) onEndReached();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [onEndReached]);

  const dragPayload = (artwork: ArtworkSummary) => {
    const ids = selected.has(artwork.id) ? [...selected] : [artwork.id];
    dragged.current = ids;
    return ids.join(",");
  };

  return (
    <>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-3">
        {items.map((artwork, index) => (
          <div
            key={artwork.id}
            draggable
            onDragStart={(event) =>
              startInternalDrag(event.dataTransfer, ARTWORK_MIME, dragPayload(artwork))
            }
            onDragOver={(event) => {
              if (onReorder && event.dataTransfer.types.includes(ARTWORK_MIME)) {
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                setDropTarget(artwork.id);
              }
            }}
            onDragLeave={() => setDropTarget(null)}
            onDragEnd={() => setDropTarget(null)}
            onDrop={(event) => {
              if (!onReorder) return;
              const payload = event.dataTransfer.getData(ARTWORK_MIME);
              const moved = payload.split(",").filter(Boolean);
              if (moved.length === 0 || moved.includes(artwork.id)) return;
              event.preventDefault();
              // Dropping always meant "insert before the target", so dragging a card *forward*
              // asked for the place it already had and nothing moved (remarks.md #6). Dragging
              // down/right now lands the card after the target instead.
              const from = items.findIndex((a) => a.id === moved[0]);
              const forward = from !== -1 && from < index;
              const anchor = forward ? (items[index + 1]?.id ?? null) : artwork.id;
              for (const id of moved) onReorder(id, anchor);
              setDropTarget(null);
            }}
            className={cn(
              "group relative overflow-hidden rounded-md border bg-panel text-left",
              selected.has(artwork.id) ? "border-accent ring-1 ring-accent" : "border-border",
              dropTarget === artwork.id && "ring-2 ring-accent",
            )}
          >
            <button
              type="button"
              onClick={(event) => onTileClick(artwork, index, event)}
              onDoubleClick={() => onOpen(artwork.id)}
              title={t("artworks.openHint")}
              className="block w-full text-left outline-offset-2"
            >
              <div className="relative aspect-video bg-panel-2">
                <img
                  src={artworkThumbUrl(artwork, window.devicePixelRatio > 1 ? 768 : 256)}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  className="h-full w-full object-cover"
                />
              </div>
              <div className="flex items-center gap-1.5 px-2.5 py-2">
                <span className="min-w-0 flex-1 truncate text-sm">
                  {artwork.title || t("artworks.untitled")}
                </span>
                <ArtworkBadges artwork={artwork} />
              </div>
            </button>
            <button
              type="button"
              aria-label={t("artworks.toggleFavorite")}
              aria-pressed={artwork.favorite}
              onClick={() => update.mutate({ id: artwork.id, favorite: !artwork.favorite })}
              className={cn(
                "absolute top-1.5 right-1.5 rounded-full bg-black/45 p-1.5 text-white/80 backdrop-blur",
                "opacity-0 transition group-hover:opacity-100 focus-visible:opacity-100",
                artwork.favorite && "text-danger opacity-100",
              )}
            >
              <Heart size={14} fill={artwork.favorite ? "currentColor" : "none"} />
            </button>
            {onReorder && (
              <span
                className="absolute top-1.5 left-1.5 rounded bg-black/45 p-1 text-white/70 opacity-0 transition group-hover:opacity-100"
                title={t("collections.dragToReorder")}
              >
                <GripVertical size={14} />
              </span>
            )}
          </div>
        ))}
      </div>
      <div ref={sentinel} className="h-4" />
    </>
  );
}
