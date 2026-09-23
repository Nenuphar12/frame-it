import { Link } from "@tanstack/react-router";
import { ChevronLeft, Frame, Heart, Layers, Upload, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { artworkRenderUrl, artworkThumbUrl } from "@/api/client";
import { useArtworks, useCollections } from "@/api/queries";
import { cn } from "@/shared/cn";
import { EmptyState, Spinner } from "@/shared/ui/Misc";

type View = { kind: "all" } | { kind: "favorites" } | { kind: "collection"; id: string };

/**
 * Read-only browsing from a phone (docs/PLAN.md §14, Phase 9 item 6). An uploader device may
 * *look* at the library — artworks, collections, favourites — and nothing more: every mutating
 * route already requires an admin, so this page simply never offers one.
 */
export function MobileBrowsePage() {
  const { t } = useTranslation();
  const [view, setView] = useState<View>({ kind: "all" });
  const [openId, setOpenId] = useState<string | null>(null);
  const collections = useCollections();

  const artworks = useArtworks(
    view.kind === "collection"
      ? { collection_id: view.id, include_nested: true }
      : view.kind === "favorites"
        ? { favorite: true }
        : {},
  );
  const items = useMemo(() => artworks.data?.pages.flatMap((p) => p.items) ?? [], [artworks.data]);
  const open = items.find((a) => a.id === openId) ?? null;
  const title =
    view.kind === "collection"
      ? ((collections.data ?? []).find((c) => c.id === view.id)?.name ?? t("nav.collections"))
      : t(view.kind === "favorites" ? "nav.favorites" : "nav.artworks");

  const tab = (active: boolean) =>
    cn(
      "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs whitespace-nowrap",
      active ? "border-accent bg-accent/15 text-accent" : "border-border text-muted",
    );

  return (
    <div className="mx-auto flex min-h-full max-w-lg flex-col gap-4 px-4 pt-[max(1rem,env(safe-area-inset-top))] pb-8">
      <header className="flex items-center justify-between gap-2">
        <h1 className="truncate text-lg font-semibold">{title}</h1>
        <Link
          to="/m"
          className="rounded-md p-2 text-muted hover:text-text"
          aria-label={t("mobile.title")}
        >
          <Upload size={18} />
        </Link>
      </header>

      <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
        <button type="button" className={tab(view.kind === "all")} onClick={() => setView({ kind: "all" })}>
          <Frame size={13} /> {t("nav.artworks")}
        </button>
        <button
          type="button"
          className={tab(view.kind === "favorites")}
          onClick={() => setView({ kind: "favorites" })}
        >
          <Heart size={13} /> {t("nav.favorites")}
        </button>
        {(collections.data ?? []).map((collection) => (
          <button
            key={collection.id}
            type="button"
            className={tab(view.kind === "collection" && view.id === collection.id)}
            onClick={() => setView({ kind: "collection", id: collection.id })}
          >
            <Layers size={13} /> {collection.name}
          </button>
        ))}
      </div>

      {artworks.isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner size={20} />
        </div>
      ) : items.length === 0 ? (
        <EmptyState compact icon={<Frame size={32} />} title={t("artworks.emptyTitle")} />
      ) : (
        <div className="grid grid-cols-2 gap-2">
          {items.map((artwork) => (
            <button
              key={artwork.id}
              type="button"
              onClick={() => setOpenId(artwork.id)}
              className="overflow-hidden rounded-lg border border-border bg-panel text-left"
            >
              <img
                src={artworkThumbUrl(artwork, 768)}
                alt=""
                loading="lazy"
                decoding="async"
                className="aspect-video w-full object-cover"
              />
              <span className="block truncate px-2 py-1.5 text-xs">
                {artwork.title || t("artworks.untitled")}
              </span>
            </button>
          ))}
        </div>
      )}
      {artworks.hasNextPage && (
        <button
          type="button"
          onClick={() => void artworks.fetchNextPage()}
          className="rounded-md border border-border py-2 text-sm text-muted"
        >
          {t("common.loadMore")}
        </button>
      )}

      {open && (
        <div className="fixed inset-0 z-50 flex flex-col bg-black/95">
          <div className="flex items-center justify-between p-3 text-white">
            <button type="button" onClick={() => setOpenId(null)} aria-label={t("common.close")}>
              <ChevronLeft size={22} />
            </button>
            <span className="truncate text-sm">{open.title || t("artworks.untitled")}</span>
            <button type="button" onClick={() => setOpenId(null)} aria-label={t("common.close")}>
              <X size={20} />
            </button>
          </div>
          <img
            src={artworkRenderUrl(open, "jpg")}
            alt=""
            className="min-h-0 flex-1 object-contain"
          />
        </div>
      )}
    </div>
  );
}
