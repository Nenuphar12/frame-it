// The Simple editor (docs/simple-editor.md §6.2): pick a configuration, move two sliders.
//
// Every control writes into the document's `composition` block and lets the solver re-derive the
// geometry — the same solver the server runs on save, so what is drawn here is what gets stored.
// The block is the source of truth while it is attached; a hand-built artwork shows the picker
// alone until one is chosen (§6.1).
import { ChevronDown, ChevronLeft, ChevronRight, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { photoThumbUrl, type FrameStyle, type Layout } from "@/api/client";
import * as actions from "@/editor/actions";
import { SLIDER_LIMITS, sliderMax, valueOf, type SliderKey } from "@/editor/core/bounds.ts";
import type { CaptionPlace, Recipe } from "@/editor/core/composition.ts";
import type { EditorDocument } from "@/editor/core/document.ts";
import {
  nativeZoom,
  photoZoom,
  slotSource,
  MAX_ZOOM,
  MIN_ZOOM,
  type PhotoSizes,
} from "@/editor/operations";
import { cn } from "@/shared/cn";
import { SLOT_MIME, startInternalDrag } from "@/shared/dnd";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { ColorField } from "./ColorField";
import { Field, IconButton, NumberField, PanelSection, Slider } from "./Controls";
import { SlotQualityBadge } from "./QualityBadge";
import { RecipePicker, RecipeSchema } from "./RecipePicker";
import { ShadowFields } from "./ShadowFields";

/** The ratio chips of §6.2, in the order they are shown. `fill` and `original` are not ratios. */
const RATIOS = ["1:1", "5:4", "4:3", "3:2", "16:9"] as const;

const isRatio = (format: string | null): format is string =>
  format !== null && format.includes(":");

/** `3:2` ⇄ `2:3`. A format carries its orientation now, so the chips need a way to flip it. */
function flipFormat(format: string): string {
  const [w, h] = format.split(":");
  return w && h ? `${h}:${w}` : format;
}

/** The landscape form of a ratio, which is what the chips are labelled with. */
function uprightFormat(format: string): string {
  const [w, h] = format.split(":");
  return w && h && Number(w) < Number(h) ? `${h}:${w}` : format;
}

const DEFAULT_BORDER_COLOR = "#FFFFFF";

interface SimplePanelProps {
  doc: EditorDocument;
  recipes: Recipe[];
  /** The frame styles of `GET /frame-styles`: the artwork's whole look in one dropdown (§6.2). */
  styles: FrameStyle[];
  /** Saved layouts (`GET /layouts`): a recipe and its parameters, applied in one go. */
  layouts: Layout[];
  sizes: PhotoSizes;
  selectedSlotId: string | null;
  onSelectSlot: (slotId: string) => void;
  /** Open the "save this artwork as a template" dialog (docs/templates.md §3). */
  onSaveAsTemplate: (kind: "frame_style" | "layout") => void;
}

export function SimplePanel({
  doc,
  recipes,
  styles,
  layouts,
  sizes,
  selectedSlotId,
  onSelectSlot,
  onSaveAsTemplate,
}: SimplePanelProps) {
  const { t } = useTranslation();
  const block = doc.composition;
  const count = doc.slots.length;
  const choices = recipes.filter((recipe) => recipe.count === count);
  const recipe =
    block && !block.detached ? (recipes.find((item) => item.id === block.recipe) ?? null) : null;

  // Detached: the slots are the truth and the block is memory. The controls would lie, so they
  // are replaced by the banner of §5 until the user re-applies the layout (or undoes the edit).
  if (block?.detached) {
    return <DetachedBanner recipe={recipes.find((item) => item.id === block.recipe) ?? null} />;
  }
  // A hand-built artwork shows the picker alone: choosing a layout attaches a block.
  if (!block || !recipe) {
    return (
      <PanelSection title={t("editor.simple.layout")}>
        <p className="text-xs text-muted">
          {choices.length > 0
            ? t("editor.simple.attachHint")
            : t("editor.simple.noRecipe", { count })}
        </p>
        {choices.length > 0 && (
          <RecipePicker recipes={choices} selected={null} onSelect={actions.setRecipe} />
        )}
      </PanelSection>
    );
  }
  return (
    <AttachedPanel
      doc={doc}
      block={block}
      recipe={recipe}
      choices={choices}
      styles={styles}
      layouts={layouts.filter((layout) => layout.slot_count === count)}
      sizes={sizes}
      selectedSlotId={selectedSlotId}
      onSelectSlot={onSelectSlot}
      onSaveAsTemplate={onSaveAsTemplate}
    />
  );
}

/** The panel proper: everything below depends on a block that is attached and has a recipe. */
function AttachedPanel({
  doc,
  block,
  recipe,
  choices,
  styles,
  layouts,
  sizes,
  selectedSlotId,
  onSelectSlot,
  onSaveAsTemplate,
}: {
  doc: EditorDocument;
  block: NonNullable<EditorDocument["composition"]>;
  recipe: Recipe;
  choices: Recipe[];
  styles: FrameStyle[];
  layouts: Layout[];
  sizes: PhotoSizes;
  selectedSlotId: string | null;
  onSelectSlot: (slotId: string) => void;
  onSaveAsTemplate: (kind: "frame_style" | "layout") => void;
}) {
  const { t } = useTranslation();
  const [more, setMore] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);
  const count = doc.slots.length;

  // One bisection per slider and per document, not per render: `sliderMax` solves ~9 times.
  const maxes = useMemo(() => {
    const photoSizes = doc.slots.map((slot) =>
      slot.photo_id ? (sizes[slot.photo_id] ?? null) : null,
    );
    const captionSize = doc.captions[0]?.size ?? 48;
    const of = (key: SliderKey) => sliderMax(key, recipe, block, photoSizes, captionSize);
    return {
      "outer.x": of("outer.x"),
      "outer.y": of("outer.y"),
      "gutter.x": of("gutter.x"),
      "gutter.y": of("gutter.y"),
      border: of("border"),
    } satisfies Record<SliderKey, number>;
  }, [doc.slots, doc.captions, sizes, recipe, block]);
  const maxOf = (key: SliderKey) => maxes[key];
  const balanced = recipe.balance != null && block.format === "fill";
  const balance = block.balance ?? recipe.balance?.default ?? 0.5;

  /** `outer` is a minimum: under a ratio the block is centred and the real inset is larger (§3.5). */
  const effective = { x: doc.margins.left, y: doc.margins.top };
  const caption = doc.captions[0] ?? null;
  // The document does not remember which style it was built from, and the colour is editable on
  // its own — so the dropdown shows the style the mat currently *is*, and "Custom" otherwise.
  const styleId =
    styles.find(
      (item) =>
        item.document.mat?.color === doc.mat.color &&
        (item.document.mat?.texture?.id ?? null) === (doc.mat.texture?.id ?? null),
    )?.id ?? null;

  const marginSlider = (key: SliderKey, label: string) => {
    const max = maxOf(key);
    const value = valueOf(block, key);
    const axis = key.endsWith(".y") ? "y" : "x";
    const slack = key.startsWith("outer") && effective[axis] > value ? effective[axis] : null;
    return (
      <Field label={label} key={key}>
        <Slider
          value={Math.min(value, max)}
          min={0}
          max={Math.max(max, 1)}
          step={4}
          disabled={max <= 0}
          onChange={(next) => set(key, next)}
        />
        <NumberField
          value={value}
          min={0}
          max={SLIDER_LIMITS[key]}
          onChange={(next) => set(key, next)}
        />
        {slack !== null && (
          <span
            className="shrink-0 text-[10px] text-muted tabular-nums"
            title={t("editor.simple.effectiveHint")}
          >
            → {slack}
          </span>
        )}
      </Field>
    );
  };

  function set(key: SliderKey, value: number): void {
    const clamped = Math.max(0, Math.min(SLIDER_LIMITS[key], Math.round(value)));
    if (key === "border") {
      actions.setComposition(
        {
          border:
            clamped <= 0
              ? null
              : { width: clamped, color: block.border?.color ?? DEFAULT_BORDER_COLOR },
        },
        "composition-border",
      );
      return;
    }
    const [field, axis] = key.split(".") as ["outer" | "gutter", "x" | "y"];
    actions.setComposition({ [field]: { ...block[field], [axis]: clamped } }, `composition-${key}`);
  }

  return (
    <>
      {/* One photo has exactly one recipe and no balance: the whole section is furniture (#10). */}
      {(choices.length > 1 || balanced || layouts.length > 0) && (
        <PanelSection
          title={t("editor.simple.layout")}
          action={
            <button
              type="button"
              className="text-[11px] text-muted hover:text-text"
              onClick={() => onSaveAsTemplate("layout")}
            >
              {t("templates.saveAsLayout")}
            </button>
          }
        >
          {choices.length > 1 && (
            <RecipePicker recipes={choices} selected={recipe.id} onSelect={actions.setRecipe} />
          )}
          {layouts.length > 0 && (
            <Field label={t("templates.savedLayouts")}>
              <select
                className="h-7 min-w-0 flex-1 rounded border border-border bg-panel-2 px-1 text-xs"
                value=""
                onChange={(event) => {
                  const picked = layouts.find((item) => item.id === event.target.value);
                  if (picked) actions.applyLayout(picked.document, picked.id);
                }}
              >
                <option value="">{t("common.select")}</option>
                {layouts.map((layout) => (
                  <option key={layout.id} value={layout.id}>
                    {layout.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {balanced && (
            <Field label={t("editor.simple.balance")}>
              <Slider
                value={balance}
                min={recipe.balance?.min ?? 0}
                max={recipe.balance?.max ?? 1}
                step={0.01}
                onChange={(value) =>
                  actions.setComposition({ balance: value }, "composition-balance")
                }
              />
              <span className="w-9 shrink-0 text-right text-[11px] text-muted tabular-nums">
                {Math.round(balance * 100)}%
              </span>
            </Field>
          )}
        </PanelSection>
      )}

      <PanelSection title={t("editor.simple.format")}>
        <FormatChoice
          label={t("editor.simple.format")}
          value={block.format}
          fill
          custom
          onChange={(format) => actions.setComposition({ format: format ?? "fill" })}
        />
        {recipe.balance != null && !balanced && (
          <p className="text-[11px] text-muted">{t("editor.simple.balanceInert")}</p>
        )}
      </PanelSection>

      <PanelSection
        title={t("editor.simple.margins")}
        action={
          <button
            type="button"
            onClick={() => setMore((value) => !value)}
            className="flex items-center gap-0.5 text-[11px] text-muted hover:text-text"
          >
            {more ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {t("editor.simple.more")}
          </button>
        }
      >
        {more ? (
          <>
            {marginSlider("outer.x", t("editor.simple.outerX"))}
            {marginSlider("outer.y", t("editor.simple.outerY"))}
            {count > 1 && marginSlider("gutter.x", t("editor.simple.gapX"))}
            {count > 1 && marginSlider("gutter.y", t("editor.simple.gapY"))}
          </>
        ) : (
          <>
            <LinkedSlider
              label={t("editor.simple.outer")}
              keys={["outer.x", "outer.y"]}
              block={block}
              max={Math.min(maxOf("outer.x"), maxOf("outer.y"))}
              limit={SLIDER_LIMITS["outer.y"]}
              effective={effective}
              onChange={(value) =>
                actions.setComposition({ outer: { x: value, y: value } }, "composition-outer")
              }
            />
            {count > 1 && (
              <LinkedSlider
                label={t("editor.simple.gap")}
                keys={["gutter.x", "gutter.y"]}
                block={block}
                max={Math.min(maxOf("gutter.x"), maxOf("gutter.y"))}
                limit={SLIDER_LIMITS["gutter.x"]}
                effective={null}
                onChange={(value) =>
                  actions.setComposition({ gutter: { x: value, y: value } }, "composition-gap")
                }
              />
            )}
          </>
        )}
      </PanelSection>

      <PhotosSection
        doc={doc}
        sizes={sizes}
        selectedSlotId={selectedSlotId}
        onSelectSlot={onSelectSlot}
        dragging={dragging}
        setDragging={setDragging}
        cellFormats={block.format === "fill" ? null : block.cell_formats}
        onCellFormat={(index, format) => {
          const next = [...block.cell_formats];
          while (next.length <= index) next.push(null);
          next[index] = format;
          actions.setComposition({ cell_formats: next.slice(0, doc.slots.length) });
        }}
      />

      <PanelSection
        title={t("editor.simple.background")}
        action={
          <button
            type="button"
            className="text-[11px] text-muted hover:text-text"
            onClick={() => onSaveAsTemplate("frame_style")}
          >
            {t("templates.saveAsStyle")}
          </button>
        }
      >
        {styles.length > 0 && (
          <Field label={t("editor.simple.style")}>
            <select
              className="h-7 min-w-0 flex-1 rounded border border-border bg-panel-2 px-1 text-xs"
              value={styleId ?? ""}
              onChange={(event) => {
                const picked = styles.find((item) => item.id === event.target.value);
                if (picked) actions.applyStyle(picked.document, picked.id);
              }}
            >
              {styleId === null && <option value="">{t("editor.simple.customStyle")}</option>}
              {styles.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label={t("editor.mat.color")}>
          <ColorField
            color={doc.mat.color}
            onChange={(color) => actions.setMatColor(color)}
            label={t("editor.mat.color")}
            photoId={doc.slots.find((slot) => slot.photo_id)?.photo_id ?? null}
          />
        </Field>
      </PanelSection>

      <PanelSection title={t("editor.simple.border")}>
        <Field label={t("editor.simple.width")}>
          <Slider
            value={Math.min(valueOf(block, "border"), Math.max(maxOf("border"), 1))}
            min={0}
            max={Math.max(maxOf("border"), 1)}
            step={2}
            disabled={maxOf("border") <= 0}
            onChange={(value) => set("border", value)}
          />
          <NumberField
            value={valueOf(block, "border")}
            min={0}
            max={SLIDER_LIMITS.border}
            onChange={(value) => set("border", value)}
          />
        </Field>
        {block.border && (
          <Field label={t("editor.simple.color")}>
            <ColorField
              color={block.border.color}
              onChange={(color) =>
                actions.setComposition(
                  { border: { width: block.border?.width ?? 1, color } },
                  "composition-border-color",
                )
              }
              label={t("editor.simple.color")}
              photoId={null}
            />
          </Field>
        )}
      </PanelSection>

      {/*
        A style carries a shadow and the mat dropdown applies it, so leaving the control in the
        Advanced panel alone made it look as though Simple had dropped the setting (remarks.md #2).
        It dresses every photo: in this panel the shadow is part of the look, not of one cell.
      */}
      <PanelSection title={t("editor.sections.shadow")}>
        <ShadowFields
          shadow={doc.slots[0]?.shadow ?? null}
          photoId={doc.slots.find((slot) => slot.photo_id)?.photo_id ?? null}
          onChange={(next, group) => actions.setShadowEverywhere(next, group)}
        />
      </PanelSection>

      <PanelSection title={t("editor.simple.caption")}>
        <input
          type="text"
          className="h-7 w-full rounded border border-border bg-panel-2 px-1.5 text-xs"
          value={block.caption.text}
          placeholder={t("editor.captions.placeholder")}
          onChange={(event) =>
            actions.setComposition(
              {
                caption: {
                  text: event.target.value,
                  place: block.caption.place === "none" ? "below" : block.caption.place,
                },
              },
              "composition-caption",
            )
          }
        />
        <div className="flex gap-1" role="radiogroup" aria-label={t("editor.simple.captionPlace")}>
          {(["none", "below", "above"] as CaptionPlace[]).map((place) => (
            <FormatChip
              key={place}
              label={t(`editor.simple.places.${place}`)}
              active={block.caption.place === place}
              onClick={() => actions.setComposition({ caption: { ...block.caption, place } }, null)}
            />
          ))}
        </div>
        {/* The size moves the band the solver reserves (§3.3), so the block re-solves around it. */}
        {caption && (
          <Field label={t("editor.captions.size")}>
            <Slider
              value={caption.size}
              min={16}
              max={320}
              step={2}
              onChange={(value) => actions.setCaptionSize(value)}
            />
            <NumberField
              value={caption.size}
              min={4}
              max={1000}
              suffix="px"
              onChange={(value) => actions.setCaptionSize(value)}
            />
          </Field>
        )}
      </PanelSection>
    </>
  );
}

/**
 * §5: a free-form edit has taken ownership of the slots. The remembered parameters are still in
 * the document, so "Re-apply layout" is one confirmed, undoable action away.
 */
function DetachedBanner({ recipe }: { recipe: Recipe | null }) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  return (
    <PanelSection title={t("editor.simple.layout")}>
      <p className="text-xs text-muted">{t("editor.simple.detached")}</p>
      {recipe && (
        <div className="flex items-center gap-2">
          <span className="h-10 w-16 shrink-0 text-muted">
            <RecipeSchema recipe={recipe} numbered={false} />
          </span>
          <span className="text-[11px] text-muted">
            {t(recipe.name_key, { defaultValue: recipe.id })}
          </span>
        </div>
      )}
      <Button size="sm" variant="secondary" onClick={() => setConfirming(true)}>
        <RotateCcw size={14} /> {t("editor.simple.reapply")}
      </Button>
      <Dialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("editor.simple.reapply")}
        description={t("editor.simple.reapplyConfirm")}
      >
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirming(false)}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              actions.reapplyLayout();
              setConfirming(false);
            }}
          >
            {t("editor.simple.reapply")}
          </Button>
        </div>
      </Dialog>
    </PanelSection>
  );
}

/** Both axes of `outer` / `gutter` on one slider (the first screen shows two, §6.2). */
function LinkedSlider({
  label,
  keys,
  block,
  max,
  limit,
  effective,
  onChange,
}: {
  label: string;
  keys: [SliderKey, SliderKey];
  block: NonNullable<EditorDocument["composition"]>;
  max: number;
  limit: number;
  effective: { x: number; y: number } | null;
  onChange: (value: number) => void;
}) {
  const { t } = useTranslation();
  const [x, y] = [valueOf(block, keys[0]), valueOf(block, keys[1])];
  const value = Math.max(x, y);
  const slack = effective && effective.y > y ? effective.y : null;
  return (
    <Field label={label}>
      <Slider
        value={Math.min(value, max)}
        min={0}
        max={Math.max(max, 1)}
        step={4}
        disabled={max <= 0}
        onChange={onChange}
      />
      <NumberField value={value} min={0} max={limit} onChange={onChange} />
      {slack !== null && (
        <span
          className="shrink-0 text-[10px] text-muted tabular-nums"
          title={t("editor.simple.effectiveHint")}
        >
          → {slack}
        </span>
      )}
    </Field>
  );
}

/** Numbered photo chips: click selects the cell, dragging one onto another swaps the two (§6.2). */
function PhotosSection({
  doc,
  sizes,
  selectedSlotId,
  onSelectSlot,
  dragging,
  setDragging,
  cellFormats,
  onCellFormat,
}: {
  doc: EditorDocument;
  sizes: PhotoSizes;
  selectedSlotId: string | null;
  onSelectSlot: (slotId: string) => void;
  dragging: string | null;
  setDragging: (slotId: string | null) => void;
  /** Per-cell format overrides, or `null` under `fill` where they mean nothing (§3.5). */
  cellFormats: (string | null)[] | null;
  onCellFormat: (index: number, format: string | null) => void;
}) {
  const { t } = useTranslation();
  const selected = doc.slots.find((slot) => slot.id === selectedSlotId) ?? null;
  const index = selected ? doc.slots.indexOf(selected) : -1;
  const zoom = selected ? photoZoom(selected, sizes) : null;
  const native = selected ? nativeZoom(selected, sizes) : null;
  // A single photo has nothing to be swapped with and no cell of its own to shape: the chips, the
  // hint, the arrows and the per-cell format are all about *which* cell (remarks.md #10).
  const several = doc.slots.length > 1;
  return (
    <PanelSection title={t("editor.simple.photos")}>
      {several && (
        <ul className="flex flex-wrap gap-1.5">
          {doc.slots.map((slot, index) => (
            <li key={slot.id}>
              <button
                type="button"
                draggable
                onDragStart={(event) => {
                  startInternalDrag(event.dataTransfer, SLOT_MIME, slot.id);
                  setDragging(slot.id);
                }}
                onDragEnd={() => setDragging(null)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => {
                  event.preventDefault();
                  if (dragging && dragging !== slot.id) actions.swapPhotos(dragging, slot.id);
                  setDragging(null);
                }}
                onClick={() => onSelectSlot(slot.id)}
                aria-pressed={slot.id === selectedSlotId}
                title={t("editor.simple.photoCell", { index: index + 1 })}
                className={cn(
                  "relative h-12 w-12 overflow-hidden rounded border",
                  slot.id === selectedSlotId ? "border-accent" : "border-border",
                  dragging === slot.id && "opacity-50",
                )}
              >
                {slot.photo_id ? (
                  <img
                    src={photoThumbUrl(slot.photo_id, 256)}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <span className="flex h-full w-full items-center justify-center text-[10px] text-muted">
                    {t("editor.simple.empty")}
                  </span>
                )}
                <span className="absolute bottom-0 left-0 bg-panel/80 px-1 text-[10px] tabular-nums">
                  {index + 1}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {several && <p className="text-[11px] text-muted">{t("editor.simple.swapHint")}</p>}
      {selected && several && (
        <>
          {/* Swapping by drag is not discoverable on its own: the arrows do the same thing. */}
          <Field label={t("editor.simple.position")}>
            <span className="flex items-center gap-1">
              <IconButton
                title={t("editor.simple.moveEarlier")}
                disabled={index <= 0}
                onClick={() => actions.swapPhotos(selected.id, doc.slots[index - 1]?.id ?? "")}
              >
                <ChevronLeft size={14} />
              </IconButton>
              <IconButton
                title={t("editor.simple.moveLater")}
                disabled={index < 0 || index >= doc.slots.length - 1}
                onClick={() => actions.swapPhotos(selected.id, doc.slots[index + 1]?.id ?? "")}
              >
                <ChevronRight size={14} />
              </IconButton>
              <span className="text-[11px] text-muted tabular-nums">
                {t("editor.simple.cellOf", { index: index + 1, total: doc.slots.length })}
              </span>
            </span>
          </Field>
          {cellFormats && (
            <>
              <p className="text-[11px] text-muted">{t("editor.simple.cellFormat")}</p>
              <FormatChoice
                label={t("editor.simple.cellFormat")}
                value={cellFormats[index] ?? null}
                inherit={t("editor.simple.sameAsLayout")}
                onChange={(format) => onCellFormat(index, format)}
              />
            </>
          )}
        </>
      )}
      {selected && zoom !== null && slotSource(selected, sizes) && (
        <>
          <Field label={t("editor.zoom")}>
            <Slider
              value={zoom}
              min={MIN_ZOOM}
              max={MAX_ZOOM}
              step={0.01}
              onChange={(value) => actions.setZoom(value)}
            />
            <span className="w-9 shrink-0 text-right text-[11px] text-muted tabular-nums">
              {zoom.toFixed(2)}×
            </span>
          </Field>
          {/* The tier belongs next to the zoom: it is the number the zoom actually moves (§7.2). */}
          <div className="flex items-center gap-2">
            <SlotQualityBadge slot={selected} />
            <button
              type="button"
              disabled={native === null}
              onClick={() => actions.setNativeFraming()}
              title={t("editor.simple.nativeHint")}
              className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted hover:text-text disabled:opacity-40"
            >
              {t("editor.simple.native")}
            </button>
          </div>
          <p className="text-[11px] text-muted">{t("editor.simple.reframeHint")}</p>
        </>
      )}
    </PanelSection>
  );
}

/**
 * The format control of §6.2 — one row of chips plus a Landscape/Portrait toggle.
 *
 * The same control serves the artwork and a single cell (`inherit` adds the "same as the layout"
 * chip): a dropdown for one and chips for the other made the two read as different kinds of
 * setting when they are the same one at two scales (remarks.md #4).
 */
function FormatChoice({
  label,
  value,
  inherit,
  fill,
  custom,
  onChange,
}: {
  label: string;
  /** The current format; `null` means "inherit", which only exists when `inherit` is given. */
  value: string | null;
  inherit?: string;
  /** Offer `fill` — a property of the whole block, never of one cell (§3.5). */
  fill?: boolean;
  custom?: boolean;
  onChange: (format: string | null) => void;
}) {
  const { t } = useTranslation();
  const ratio = isRatio(value);
  const [width, height] = ratio ? value.split(":") : [];
  const portrait = ratio && Number(width) < Number(height);
  // Picking a ratio keeps the orientation that is already showing: the toggle is the only thing
  // that flips a format, so moving 3:2 → 4:3 must not quietly turn the block back to landscape.
  const pick = (format: string) => onChange(portrait ? flipFormat(format) : format);
  return (
    <>
      <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={label}>
        {inherit !== undefined && (
          <FormatChip label={inherit} active={value === null} onClick={() => onChange(null)} />
        )}
        {fill && (
          <FormatChip
            label={t("editor.simple.formats.fill")}
            active={value === "fill"}
            onClick={() => onChange("fill")}
          />
        )}
        <FormatChip
          label={t("editor.simple.formats.original")}
          active={value === "original"}
          onClick={() => onChange("original")}
        />
        {RATIOS.map((item) => (
          <FormatChip
            key={item}
            label={item}
            active={ratio && uprightFormat(value) === item}
            onClick={() => pick(item)}
          />
        ))}
        {custom && (
          <CustomFormat
            value={
              ratio && !RATIOS.includes(uprightFormat(value) as (typeof RATIOS)[number])
                ? value
                : null
            }
            onChange={onChange}
          />
        )}
      </div>
      {ratio && (
        <div className="flex gap-1" role="radiogroup" aria-label={t("editor.simple.orientation")}>
          <FormatChip
            label={t("editor.simple.landscape")}
            active={!portrait}
            onClick={() => onChange(uprightFormat(value))}
          />
          <FormatChip
            label={t("editor.simple.portrait")}
            active={portrait}
            onClick={() => onChange(flipFormat(uprightFormat(value)))}
          />
        </div>
      )}
    </>
  );
}

function FormatChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={cn(
        "rounded border px-1.5 py-0.5 text-[11px]",
        active ? "border-accent text-accent" : "border-border text-muted hover:text-text",
      )}
    >
      {label}
    </button>
  );
}

/** The `…` chip of §6.2: any `w:h` the document model accepts (terms ≤ 1000). */
function CustomFormat({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (format: string) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  if (!open && value === null) {
    return <FormatChip label="…" active={false} onClick={() => setOpen(true)} />;
  }
  return (
    <span className="flex items-center gap-1">
      <input
        type="text"
        className="h-6 w-16 rounded border border-border bg-panel-2 px-1 text-[11px]"
        value={draft || (value ?? "")}
        placeholder="4:3"
        aria-label={t("editor.simple.customFormat")}
        onChange={(event) => {
          setDraft(event.target.value);
          if (/^[1-9][0-9]{0,3}:[1-9][0-9]{0,3}$/.test(event.target.value)) {
            onChange(event.target.value);
          }
        }}
        onBlur={() => setDraft("")}
      />
    </span>
  );
}
