import { Frame } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { artworkThumbUrl } from "@/api/client";
import { useArtworks, type ArtworkFilter } from "@/api/queries";
import { cn } from "@/shared/cn";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

import { ArtworkBadges } from "./ArtworkBadges";
import { ArtworkViewer } from "./ArtworkViewer";

const FILTERS: { key: string; filter: ArtworkFilter }[] = [
  { key: "all", filter: {} },
  { key: "draft", filter: { status: "draft" } },
  { key: "ready", filter: { status: "ready" } },
];

export function ArtworksPage() {
  const { t } = useTranslation();
  const [filterKey, setFilterKey] = useState("all");
  const filter = FILTERS.find((f) => f.key === filterKey)!.filter;
  const artworks = useArtworks(filter);
  const items = useMemo(() => artworks.data?.pages.flatMap((p) => p.items) ?? [], [artworks.data]);
  const [openId, setOpenId] = useState<string | null>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = artworks;

  useEffect(() => {
    const element = sentinel.current;
    if (!element) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting && hasNextPage && !isFetchingNextPage) void fetchNextPage();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("nav.artworks")}
        subtitle={artworks.data ? t("artworks.count", { count: items.length }) : undefined}
        actions={
          <div className="flex rounded-md border border-border p-0.5" role="tablist">
            {FILTERS.map(({ key }) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={filterKey === key}
                onClick={() => setFilterKey(key)}
                className={cn(
                  "rounded px-2.5 py-1 text-xs text-muted",
                  filterKey === key && "bg-panel-2 text-text",
                )}
              >
                {t(`artworks.filters.${key}`)}
              </button>
            ))}
          </div>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {artworks.isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner size={20} />
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Frame size={40} />}
            title={t("artworks.emptyTitle")}
            description={t("artworks.emptyDescription")}
          />
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(18rem,1fr))] gap-3">
            {items.map((artwork) => (
              <button
                key={artwork.id}
                type="button"
                onClick={() => setOpenId(artwork.id)}
                className="group overflow-hidden rounded-md border border-border bg-panel text-left outline-offset-2 hover:border-muted"
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
            ))}
          </div>
        )}
        <div ref={sentinel} className="h-4" />
      </div>
      {openId && (
        <ArtworkViewer
          artworkId={openId}
          ids={items.map((a) => a.id)}
          onNavigate={setOpenId}
          onClose={() => setOpenId(null)}
        />
      )}
    </div>
  );
}
