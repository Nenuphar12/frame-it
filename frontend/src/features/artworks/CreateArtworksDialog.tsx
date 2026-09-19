import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  useArtworkDefaults,
  useCreateArtworks,
  useFrameStyles,
  useLayouts,
} from "@/api/queries";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Spinner } from "@/shared/ui/Misc";

interface CreateArtworksDialogProps {
  /** Selected photos, in grid order (slot order for multi-photo layouts). */
  photoIds: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Ids of the created artworks, in creation order (the review queue, §14 phase 5.7). */
  onCreated: (ids: string[]) => void;
}

/** Used only until `GET /artwork-defaults` answers (and if it ever fails). */
const DEFAULT_STYLE = "builtin-style-gallery-recessed";
const DEFAULT_LAYOUT = "builtin-layout-single";

/** Pick a frame style and a layout; multi-slot layouts consume the photos in selection order. */
export function CreateArtworksDialog({
  photoIds,
  open,
  onOpenChange,
  onCreated,
}: CreateArtworksDialogProps) {
  const { t } = useTranslation();
  const styles = useFrameStyles();
  const layouts = useLayouts();
  const create = useCreateArtworks();
  const defaults = useArtworkDefaults();
  // The user's pick wins; until they pick, the dialog follows the defaults from Settings (they
  // arrive asynchronously, so they are *derived* rather than copied into state on arrival).
  const [pickedStyle, setPickedStyle] = useState<string | null>(null);
  const [pickedLayout, setPickedLayout] = useState<string | null>(null);
  const styleId = pickedStyle ?? defaults.data?.style_id ?? DEFAULT_STYLE;
  const layoutId = pickedLayout ?? defaults.data?.layout_id ?? DEFAULT_LAYOUT;
  const [placement, setPlacement] = useState<"fit_in_mat" | "fill">("fit_in_mat");
  // `Enter` must create the artworks: without this Radix focuses the close cross instead (§11.5).
  const submitRef = useRef<HTMLButtonElement>(null);
  const layout = layouts.data?.find((l) => l.id === layoutId);
  const slotCount = layout?.slot_count ?? 1;

  const groups = useMemo(() => {
    const result: string[][] = [];
    for (let i = 0; i < photoIds.length; i += slotCount)
      result.push(photoIds.slice(i, i + slotCount));
    return result;
  }, [photoIds, slotCount]);

  const submit = () =>
    create.mutate(
      {
        groups,
        style_id: styleId,
        layout_id: layoutId,
        placement: slotCount === 1 ? placement : null,
      },
      {
        onSuccess: (created) => {
          onOpenChange(false);
          onCreated(created.map((artwork) => artwork.id));
        },
      },
    );

  const selectClass = "w-full rounded-md border border-border bg-bg px-2.5 py-1.5 text-sm";
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !create.isPending && onOpenChange(next)}
      title={t("artworks.create.title")}
      description={t("artworks.create.description", { count: photoIds.length })}
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        submitRef.current?.focus();
      }}
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          {t("artworks.create.style")}
          <select
            className={selectClass}
            value={styleId}
            onChange={(e) => setPickedStyle(e.target.value)}
          >
            {styles.data?.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          {t("artworks.create.layout")}
          <select
            className={selectClass}
            value={layoutId}
            onChange={(e) => setPickedLayout(e.target.value)}
          >
            {layouts.data?.map((l) => (
              <option key={l.id} value={l.id}>
                {t("artworks.create.layoutOption", { name: l.name, count: l.slot_count })}
              </option>
            ))}
          </select>
        </label>
        {slotCount === 1 && (
          <fieldset className="flex gap-4 text-sm">
            <legend className="mb-1">{t("artworks.create.placement")}</legend>
            {(["fit_in_mat", "fill"] as const).map((value) => (
              <label key={value} className="flex items-center gap-1.5">
                <input
                  type="radio"
                  name="placement"
                  checked={placement === value}
                  onChange={() => setPlacement(value)}
                />
                {t(`artworks.create.placements.${value}`)}
              </label>
            ))}
          </fieldset>
        )}
        <p className="text-xs text-muted">
          {t("artworks.create.summary", { count: groups.length })}
          {slotCount > 1 &&
            photoIds.length % slotCount !== 0 &&
            ` ${t("artworks.create.emptySlots")}`}
        </p>
        {create.error && (
          <p className="text-sm text-danger">
            {create.error instanceof ApiError
              ? t(`errors.${create.error.code}`, { defaultValue: create.error.message })
              : t("errors.unknown")}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={create.isPending}
          >
            {t("common.cancel")}
          </Button>
          <Button
            ref={submitRef}
            type="submit"
            variant="primary"
            disabled={create.isPending || photoIds.length === 0}
          >
            {create.isPending && <Spinner size={14} />}
            {t("artworks.create.submit", { count: groups.length })}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
