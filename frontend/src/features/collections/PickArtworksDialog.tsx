import { Check, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { artworkThumbUrl } from "@/api/client";
import { useArtworks, useCollectionItems } from "@/api/queries";
import { useRegisterCommands, type Command } from "@/app/commands";
import { useSelection } from "@/features/photos/useSelection";
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
 *
 * Mounted only while open: its `Ctrl/Cmd+A` must not outlive it, and every opening starts empty.
 */
export function PickArtworksDialog(props: PickArtworksDialogProps) {
  if (!props.open) return null;
  return <Picker {...props} />;
}

function Picker({
  collectionId,
  collectionName,
  alreadyIn,
  open,
  onOpenChange,
}: PickArtworksDialogProps) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const items = useCollectionItems();
  const artworks = useArtworks(search.trim() ? { q: search.trim() } : {});
  const all = useMemo(() => artworks.data?.pages.flatMap((p) => p.items) ?? [], [artworks.data]);
  const ids = useMemo(() => all.map((a) => a.id), [all]);
  const present = useMemo(() => new Set(alreadyIn), [alreadyIn]);
  // A picker: a click ticks or unticks, Shift-click ticks a range, Ctrl/Cmd+A ticks every
  // artwork listed — never the ones already in the collection (user feedback).
  const selection = useSelection(ids, { toggle: true, disabled: present });
  const { selected: picked, selectAll, clear } = selection;
  const selectable = ids.length - ids.filter((id) => present.has(id)).length;

  const commands = useMemo<Command[]>(
    () => [
      {
        id: "collections.pickAll",
        label: "collections.pickAll",
        group: "commands.groups.library",
        shortcut: "$mod+a",
        // Even from the (empty) search box, which has the focus: see its `onKeyDown`.
        allowInInputs: true,
        run: selectAll,
      },
    ],
    [selectAll],
  );
  useRegisterCommands(commands);

  const confirm = () => {
    if (picked.size > 0) {
      // In the order they are listed, not the order they were ticked.
      items.add.mutate({ id: collectionId, artwork_ids: ids.filter((id) => picked.has(id)) });
    }
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
            onChange={(event) => {
              setSearch(event.target.value);
              clear();
            }}
            onKeyDown={(event) => {
              // With text in the box, Ctrl/Cmd+A selects that text, as anywhere else: the
              // window-level shortcut never hears it.
              const selectAllKey = (event.ctrlKey || event.metaKey) && event.key === "a";
              if (selectAllKey && search !== "") event.stopPropagation();
            }}
            placeholder={t("artworks.searchPlaceholder")}
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
          />
        </label>
        <div
          className="max-h-[50vh] min-h-40 overflow-y-auto"
          onScroll={(event) => {
            const box = event.currentTarget;
            const nearEnd = box.scrollTop + box.clientHeight > box.scrollHeight - 200;
            if (nearEnd && artworks.hasNextPage && !artworks.isFetchingNextPage) {
              void artworks.fetchNextPage();
            }
          }}
        >
          {artworks.isLoading ? (
            <div className="flex h-40 items-center justify-center">
              <Spinner size={18} />
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-2 select-none">
              {all.map((artwork, index) => {
                const inside = present.has(artwork.id);
                const on = picked.has(artwork.id);
                return (
                  <button
                    key={artwork.id}
                    type="button"
                    disabled={inside}
                    aria-pressed={on}
                    onClick={(event) => selection.click(artwork.id, index, event)}
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
                      draggable={false}
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
          <span className="mr-auto flex items-center gap-2 text-xs text-muted">
            {t("collections.picked", { count: picked.size })}
            {selectable > 0 && picked.size < selectable && (
              <button
                type="button"
                onClick={selectAll}
                className="underline-offset-2 hover:text-text hover:underline"
              >
                {t("collections.pickAllCount", { count: selectable })}
              </button>
            )}
            {picked.size > 0 && (
              <button
                type="button"
                onClick={clear}
                className="underline-offset-2 hover:text-text hover:underline"
              >
                {t("collections.pickNone")}
              </button>
            )}
          </span>
          <span className="hidden text-[11px] text-muted/80 sm:inline">
            {t("collections.pickHint")}
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
