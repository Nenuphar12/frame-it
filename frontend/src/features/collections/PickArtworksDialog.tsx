import { Check, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { artworkThumbUrl } from "@/api/client";
import { useArtworks, useCollectionItems } from "@/api/queries";
import { cn } from "@/shared/cn";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Spinner } from "@/shared/ui/Misc";

interface PickArtworksDialogProps {
  collectionId: string;
  collectionName: string;
  /** Already in the collection: shown ticked and not offered again. */
  alreadyIn: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * "Add artworks" from inside a collection (user feedback): search the library, tick what belongs
 * here, confirm. The mirror of dragging cards onto the tree, for when you are already *in* the
 * collection and the artworks are somewhere else.
 */
export function PickArtworksDialog({
  collectionId,
  collectionName,
  alreadyIn,
  open,
  onOpenChange,
}: PickArtworksDialogProps) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const items = useCollectionItems();
  const artworks = useArtworks(search.trim() ? { q: search.trim() } : {});
  const all = useMemo(() => artworks.data?.pages.flatMap((p) => p.items) ?? [], [artworks.data]);
  const present = useMemo(() => new Set(alreadyIn), [alreadyIn]);

  const toggle = (id: string) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const confirm = () => {
    if (picked.size > 0) {
      items.add.mutate({ id: collectionId, artwork_ids: [...picked] });
    }
    setPicked(new Set());
    onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("collections.addArtworksTitle", { name: collectionName })}
      description={t("collections.addArtworksHint")}
      className="w-[min(94vw,52rem)]"
    >
      <div className="flex min-h-0 flex-col gap-3">
        <label className="flex items-center gap-2 rounded-md border border-border bg-bg px-2.5 py-1.5">
          <Search size={14} className="text-muted" />
          <input
            autoFocus
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("artworks.searchPlaceholder")}
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
          />
        </label>
        <div className="max-h-[50vh] min-h-40 overflow-y-auto">
          {artworks.isLoading ? (
            <div className="flex h-40 items-center justify-center">
              <Spinner size={18} />
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2">
              {all.map((artwork) => {
                const inside = present.has(artwork.id);
                const on = picked.has(artwork.id);
                return (
                  <button
                    key={artwork.id}
                    type="button"
                    disabled={inside}
                    onClick={() => toggle(artwork.id)}
                    className={cn(
                      "relative overflow-hidden rounded-md border text-left",
                      on ? "border-accent ring-1 ring-accent" : "border-border",
                      inside && "opacity-40",
                    )}
                  >
                    <img
                      src={artworkThumbUrl(artwork, 256)}
                      alt=""
                      loading="lazy"
                      className="aspect-video w-full object-cover"
                    />
                    <span className="block truncate px-2 py-1 text-xs">
                      {artwork.title || t("artworks.untitled")}
                    </span>
                    {(on || inside) && (
                      <span className="absolute top-1 right-1 rounded-full bg-accent p-0.5 text-accent-contrast">
                        <Check size={12} />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2">
          <span className="mr-auto text-xs text-muted">
            {t("collections.picked", { count: picked.size })}
          </span>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" disabled={picked.size === 0} onClick={confirm}>
            {t("collections.addTo")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
