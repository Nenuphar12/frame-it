// Photo picker of the composition editor: search the library, pick a photo for a slot.
//
// The tiles are also HTML-draggable (`PHOTO_MIME`), so a photo can be dropped straight onto the
// canvas — on a slot to replace its photo, on the mat to add a slot there.
//
// Replacing a photo opens on the ones taken *around* it (`around`): the same few days or the same
// spot is where the better frame of the same scene lives. The whole library is one chip away.
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { photoThumbUrl } from "@/api/client";
import { usePhoto, usePhotos } from "@/api/queries";
import { cn } from "@/shared/cn";
import { PHOTO_MIME, startInternalDrag } from "@/shared/dnd";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Spinner } from "@/shared/ui/Misc";

interface PhotoPickerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Photo ids already used in the artwork (marked, still selectable). */
  used?: string[];
  onPick: (photoId: string) => void;
  /** Offered when the picker fills a *new* slot: a slot can stay empty (incomplete artwork). */
  onPickEmpty?: () => void;
  /** The photo being replaced: the picker opens on what was taken around it. */
  around?: string | null;
}

export function PhotoPicker({
  open,
  onOpenChange,
  used = [],
  onPick,
  onPickEmpty,
  around = null,
}: PhotoPickerProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [everything, setEverything] = useState(false);
  const reference = usePhoto(open ? around : null).data;
  // A photo that says neither when nor where it was taken has no neighbours to offer.
  const located = Boolean(reference && (reference.taken_at || reference.gps_lat !== null));
  const nearby = located && !everything;
  const photos = usePhotos({
    q: query || undefined,
    around: nearby && around ? around : undefined,
  });
  const items = (photos.data?.pages ?? []).flatMap((page) => page.items);
  const scope = (active: boolean, label: string, onClick: () => void) => (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={cn(
        "rounded border px-2 py-0.5 text-xs",
        active ? "border-accent text-accent" : "border-border text-muted hover:text-text",
      )}
    >
      {label}
    </button>
  );

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("editor.slots.pickPhoto")}
      className="w-[min(94vw,56rem)]"
    >
      <input
        type="search"
        autoFocus
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("photos.searchPlaceholder")}
        className="mb-3 h-8 w-full rounded border border-border bg-panel-2 px-2 text-sm"
      />
      {located && (
        <div
          className="mb-3 flex items-center gap-1.5"
          role="radiogroup"
          aria-label={t("editor.picker.scope")}
        >
          {scope(nearby, t("editor.picker.around"), () => setEverything(false))}
          {scope(!nearby, t("editor.picker.all"), () => setEverything(true))}
        </div>
      )}
      {nearby && !photos.isLoading && items.every((photo) => photo.id === around) && (
        <p className="mb-3 text-xs text-muted">{t("editor.picker.aroundEmpty")}</p>
      )}
      <div className="grid max-h-[55vh] grid-cols-[repeat(auto-fill,minmax(7rem,1fr))] gap-2 overflow-y-auto">
        {photos.isLoading && <Spinner size={18} />}
        {items.map((photo) => (
          <button
            key={photo.id}
            type="button"
            draggable
            onDragStart={(event) =>
              startInternalDrag(event.dataTransfer, PHOTO_MIME, photo.id, "copy")
            }
            onClick={() => {
              onPick(photo.id);
              onOpenChange(false);
            }}
            title={photo.original_filename}
            className={cn(
              "relative aspect-square overflow-hidden rounded border border-border hover:border-accent",
              used.includes(photo.id) && "ring-1 ring-accent",
            )}
          >
            <img
              src={photoThumbUrl(photo.id, 256)}
              alt=""
              loading="lazy"
              className="h-full w-full object-cover"
            />
          </button>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-center gap-2">
        {photos.hasNextPage && (
          <Button variant="secondary" size="sm" onClick={() => void photos.fetchNextPage()}>
            {t("photos.loadMore")}
          </Button>
        )}
        {onPickEmpty && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              onPickEmpty();
              onOpenChange(false);
            }}
          >
            {t("editor.slots.addEmpty")}
          </Button>
        )}
      </div>
    </Dialog>
  );
}
