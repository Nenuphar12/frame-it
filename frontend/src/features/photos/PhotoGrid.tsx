import { useVirtualizer } from "@tanstack/react-virtual";
import { AlertTriangle, Check } from "lucide-react";
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { useTranslation } from "react-i18next";

import { photoThumbUrl, type Photo } from "@/api/client";
import { cn } from "@/shared/cn";
import { Badge } from "@/shared/ui/Misc";

import { coversTv } from "./quality";

/** Tiles keep this size whatever the width (e.g. when the details drawer opens); only columns change. */
const TILE = 220;
const GAP = 8;

interface PhotoGridProps {
  photos: Photo[];
  selected?: Set<string>;
  focusedId?: string | null;
  onTileClick: (photo: Photo, index: number, event: MouseEvent) => void;
  onTileDoubleClick?: (photo: Photo) => void;
  onEndReached?: () => void;
}

function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry!.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/** Virtualized grid of fixed-size photo thumbnails (left-aligned, column count follows the width). */
export function PhotoGrid({
  photos,
  selected,
  focusedId,
  onTileClick,
  onTileDoubleClick,
  onEndReached,
}: PhotoGridProps) {
  const { t } = useTranslation();
  const [scrollRef, width] = useElementWidth<HTMLDivElement>();
  const columns = Math.max(1, Math.floor((width + GAP) / (TILE + GAP)));
  // Only shrinks when not even one tile fits (very narrow windows).
  const tile = width > 0 ? Math.min(TILE, width) : TILE;
  const rowCount = Math.ceil(photos.length / columns);
  const thumbSize = tile * window.devicePixelRatio > 256 ? 768 : 256;

  // eslint-disable-next-line react-hooks/incompatible-library -- component is not memoized
  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => tile + GAP,
    overscan: 4,
  });

  useEffect(() => virtualizer.measure(), [tile, virtualizer]);

  const virtualRows = virtualizer.getVirtualItems();
  const lastRow = virtualRows.at(-1)?.index ?? 0;
  useEffect(() => {
    if (rowCount > 0 && lastRow >= rowCount - 3) onEndReached?.();
  }, [lastRow, rowCount, onEndReached]);

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto px-5 py-4">
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualRows.map((row) => (
          <div
            key={row.key}
            className="absolute left-0 flex w-full"
            style={{ top: row.start, height: tile, gap: GAP }}
          >
            {photos.slice(row.index * columns, row.index * columns + columns).map((photo, i) => {
              const index = row.index * columns + i;
              const isSelected = selected?.has(photo.id) ?? false;
              return (
                <button
                  key={photo.id}
                  type="button"
                  data-photo-id={photo.id}
                  onClick={(event) => onTileClick(photo, index, event)}
                  onDoubleClick={() => onTileDoubleClick?.(photo)}
                  className={cn(
                    "group relative shrink-0 overflow-hidden rounded-md bg-panel-2 outline-offset-2",
                    isSelected && "ring-2 ring-accent",
                    focusedId === photo.id && !isSelected && "ring-2 ring-border",
                  )}
                  style={{ width: tile, height: tile }}
                  aria-pressed={selected ? isSelected : undefined}
                  aria-label={photo.original_filename}
                >
                  <img
                    src={photoThumbUrl(photo.id, thumbSize)}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    draggable={false}
                    className="h-full w-full object-contain"
                  />
                  {isSelected && (
                    <span className="absolute top-1.5 left-1.5 rounded-full bg-accent p-0.5 text-accent-contrast">
                      <Check size={12} strokeWidth={3} />
                    </span>
                  )}
                  <div className="absolute inset-x-0 bottom-0 flex items-center gap-1 bg-gradient-to-t from-black/70 to-transparent p-1.5 opacity-90">
                    {coversTv(photo) ? (
                      <Badge tone="accent" title={t("photos.coversTvHint")}>
                        4K+
                      </Badge>
                    ) : (
                      <Badge tone="neutral" title={t("photos.belowTvHint")}>
                        {photo.width}×{photo.height}
                      </Badge>
                    )}
                    {photo.quality_warnings.length > 0 && (
                      <Badge
                        tone="warning"
                        title={photo.quality_warnings
                          .map((w) => t(`photos.warnings.${w}`))
                          .join("\n")}
                      >
                        <AlertTriangle size={11} />
                      </Badge>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
