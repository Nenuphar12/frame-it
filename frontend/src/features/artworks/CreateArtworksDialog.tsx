import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useArtworkDefaults,
  useCreateArtworks,
  useFrameStyles,
  useLayouts,
  useRecipes,
} from "@/api/queries";
import { RecipePicker } from "@/editor/panels/RecipePicker";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Spinner } from "@/shared/ui/Misc";
import { problemMessage } from "@/shared/problem";

interface CreateArtworksDialogProps {
  /** Selected photos, in grid order (slot order for a multi-photo composition). */
  photoIds: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Ids of the created artworks, in creation order (the review queue, §14 phase 5.7). */
  onCreated: (ids: string[]) => void;
}

/** Used only until `GET /artwork-defaults` answers (and if it ever fails). */
const DEFAULT_STYLE = "builtin-style-gallery-recessed";

type Grouping = "together" | "separate";

/**
 * Create artworks from the selected photos.
 *
 * Selecting several photos means "make me *one* artwork out of these" far more often than "make
 * me one artwork each" (remarks.md, phase 7 feedback #6), so the default is a single parametric
 * artwork holding them all, laid out by the recipe for that count. "One artwork per photo" is one
 * radio away.
 */
export function CreateArtworksDialog({
  photoIds,
  open,
  onOpenChange,
  onCreated,
}: CreateArtworksDialogProps) {
  const { t } = useTranslation();
  const styles = useFrameStyles();
  const recipes = useRecipes();
  const layouts = useLayouts();
  const create = useCreateArtworks();
  const defaults = useArtworkDefaults();
  // The user's pick wins; until they pick, the dialog follows the defaults from Settings (they
  // arrive asynchronously, so they are *derived* rather than copied into state on arrival).
  const [pickedStyle, setPickedStyle] = useState<string | null>(null);
  const [pickedGrouping, setPickedGrouping] = useState<Grouping | null>(null);
  const [pickedRecipe, setPickedRecipe] = useState<string | null>(null);
  const [pickedLayout, setPickedLayout] = useState<string | null>(null);
  const [placement, setPlacement] = useState<"fit_in_mat" | "fill">("fit_in_mat");
  const styleId = pickedStyle ?? defaults.data?.style_id ?? DEFAULT_STYLE;
  // `Enter` must create the artworks: without this Radix focuses the close cross instead (§11.5).
  const submitRef = useRef<HTMLButtonElement>(null);

  const choices = useMemo(
    () => (recipes.data ?? []).filter((recipe) => recipe.count === photoIds.length),
    [recipes.data, photoIds.length],
  );
  const canGroup = photoIds.length > 1 && choices.length > 0;
  const grouping: Grouping = pickedGrouping ?? (canGroup ? "together" : "separate");
  const together = grouping === "together" && canGroup;
  const recipeId = together ? (pickedRecipe ?? choices[0]?.id) : undefined;
  const groups = useMemo(
    () => (together ? [photoIds] : photoIds.map((id) => [id])),
    [together, photoIds],
  );
  // A saved layout only fits a selection holding exactly its cells (docs/templates.md §4).
  const savedLayouts = useMemo(
    () => (layouts.data ?? []).filter((layout) => layout.slot_count === groups[0]?.length),
    [layouts.data, groups],
  );
  const layoutId = savedLayouts.some((layout) => layout.id === pickedLayout) ? pickedLayout : null;

  const submit = () =>
    create.mutate(
      layoutId
        ? { groups, style_id: styleId, layout_id: layoutId }
        : {
            groups,
            style_id: styleId,
            composition: {
              ...(recipeId ? { recipe: recipeId } : {}),
              // A one-photo artwork keeps the old choice: the whole photo in the mat, or edge to edge.
              ...(together ? {} : { format: placement === "fill" ? "fill" : "original" }),
            },
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
        {photoIds.length > 1 && (
          <fieldset className="flex flex-col gap-1.5 text-sm">
            <legend className="mb-1">{t("artworks.create.grouping")}</legend>
            {(["together", "separate"] as Grouping[]).map((value) => (
              <label key={value} className="flex items-center gap-1.5">
                <input
                  type="radio"
                  name="grouping"
                  checked={grouping === value}
                  disabled={value === "together" && !canGroup}
                  onChange={() => setPickedGrouping(value)}
                />
                {t(`artworks.create.groupings.${value}`, { count: photoIds.length })}
              </label>
            ))}
            {photoIds.length > 1 && !canGroup && (
              <p className="text-xs text-muted">
                {t("artworks.create.noRecipe", { count: photoIds.length })}
              </p>
            )}
          </fieldset>
        )}
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
        {savedLayouts.length > 0 && (
          <label className="flex flex-col gap-1 text-sm">
            {t("templates.savedLayouts")}
            <select
              className={selectClass}
              value={layoutId ?? ""}
              onChange={(event) => setPickedLayout(event.target.value || null)}
            >
              <option value="">{t("artworks.create.noLayout")}</option>
              {savedLayouts.map((layout) => (
                <option key={layout.id} value={layout.id}>
                  {layout.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {together && !layoutId && (
          <div className="flex flex-col gap-1 text-sm">
            {t("artworks.create.layout")}
            <RecipePicker
              recipes={choices}
              selected={recipeId ?? null}
              onSelect={setPickedRecipe}
            />
          </div>
        )}
        {!together && !layoutId && (
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
        </p>
        {create.error && (
          <p className="text-sm text-danger">
            {problemMessage(t, create.error)}
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
