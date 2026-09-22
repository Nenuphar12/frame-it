// The Simple editor (docs/simple-editor.md §6.2): pick a configuration, move two sliders.
//
// Every control writes into the document's `composition` block and lets the solver re-derive the
// geometry — the same solver the server runs on save, so what is drawn here is what gets stored.
// The block is the source of truth while it is attached; a hand-built artwork shows the picker
// alone until one is chosen (§6.1).
import { ChevronDown, ChevronRight, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { photoThumbUrl } from "@/api/client";
import * as actions from "@/editor/actions";
import { SLIDER_LIMITS, sliderMax, valueOf, type SliderKey } from "@/editor/core/bounds.ts";
import type { CaptionPlace, Recipe } from "@/editor/core/composition.ts";
import type { EditorDocument } from "@/editor/core/document.ts";
import { photoZoom, slotSource, MAX_ZOOM, MIN_ZOOM, type PhotoSizes } from "@/editor/operations";
import { cn } from "@/shared/cn";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { ColorField } from "./ColorField";
import { Field, NumberField, PanelSection, Slider } from "./Controls";
import { RecipePicker, RecipeSchema } from "./RecipePicker";

/** The ratio chips of §6.2, in the order they are shown. `original` is added for a single cell. */
const FORMATS = ["fill", "1:1", "5:4", "4:3", "3:2", "16:9"] as const;

const DEFAULT_BORDER_COLOR = "#FFFFFF";

interface SimplePanelProps {
  doc: EditorDocument;
  recipes: Recipe[];
  sizes: PhotoSizes;
  selectedSlotId: string | null;
  onSelectSlot: (slotId: string) => void;
}

export function SimplePanel({
  doc,
  recipes,
  sizes,
  selectedSlotId,
  onSelectSlot,
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
      sizes={sizes}
      selectedSlotId={selectedSlotId}
      onSelectSlot={onSelectSlot}
    />
  );
}

/** The panel proper: everything below depends on a block that is attached and has a recipe. */
function AttachedPanel({
  doc,
  block,
  recipe,
  choices,
  sizes,
  selectedSlotId,
  onSelectSlot,
}: {
  doc: EditorDocument;
  block: NonNullable<EditorDocument["composition"]>;
  recipe: Recipe;
  choices: Recipe[];
  sizes: PhotoSizes;
  selectedSlotId: string | null;
  onSelectSlot: (slotId: string) => void;
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
  const ratioFormat = block.format !== "fill" && block.format !== "original";
  const balanced = recipe.balance != null && block.format === "fill";
  const balance = block.balance ?? recipe.balance?.default ?? 0.5;

  /** `outer` is a minimum: under a ratio the block is centred and the real inset is larger (§3.5). */
  const effective = { x: doc.margins.left, y: doc.margins.top };

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
      <PanelSection title={t("editor.simple.layout")}>
        <RecipePicker recipes={choices} selected={recipe.id} onSelect={actions.setRecipe} />
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

      <PanelSection title={t("editor.simple.format")}>
        <div
          className="flex flex-wrap gap-1"
          role="radiogroup"
          aria-label={t("editor.simple.format")}
        >
          {count === 1 && (
            <FormatChip
              label={t("editor.simple.formats.original")}
              active={block.format === "original"}
              onClick={() => actions.setComposition({ format: "original" })}
            />
          )}
          {FORMATS.map((format) => (
            <FormatChip
              key={format}
              label={format === "fill" ? t("editor.simple.formats.fill") : format}
              active={block.format === format}
              onClick={() => actions.setComposition({ format })}
            />
          ))}
          <CustomFormat
            value={
              ratioFormat && !FORMATS.includes(block.format as (typeof FORMATS)[number])
                ? block.format
                : null
            }
            onChange={(format) => actions.setComposition({ format })}
          />
        </div>
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
            {marginSlider("gutter.x", t("editor.simple.gapX"))}
            {marginSlider("gutter.y", t("editor.simple.gapY"))}
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
      />

      <PanelSection title={t("editor.simple.background")}>
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
}: {
  doc: EditorDocument;
  sizes: PhotoSizes;
  selectedSlotId: string | null;
  onSelectSlot: (slotId: string) => void;
  dragging: string | null;
  setDragging: (slotId: string | null) => void;
}) {
  const { t } = useTranslation();
  const selected = doc.slots.find((slot) => slot.id === selectedSlotId) ?? null;
  const zoom = selected ? photoZoom(selected, sizes) : null;
  return (
    <PanelSection title={t("editor.simple.photos")}>
      <ul className="flex flex-wrap gap-1.5">
        {doc.slots.map((slot, index) => (
          <li key={slot.id}>
            <button
              type="button"
              draggable
              onDragStart={() => setDragging(slot.id)}
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
          <p className="text-[11px] text-muted">{t("editor.simple.reframeHint")}</p>
        </>
      )}
    </PanelSection>
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
