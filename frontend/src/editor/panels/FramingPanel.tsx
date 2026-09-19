// Framing controls: placement, margins (with the quality-point snapping of §7.5), quality lock,
// crop ratio, photo zoom, 90° turns / flip and free rotation.
import {
  FlipHorizontal,
  Link2,
  Link2Off,
  RotateCcw,
  RotateCw,
  UnfoldHorizontal,
  UnfoldVertical,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/shared/cn";

import * as actions from "@/editor/actions";
import type { DocSlot, EditorDocument } from "@/editor/core/document.ts";
import type { QualityLock } from "@/editor/core/placement.ts";
import { marginCandidates, snap, TOLERANCE_PX, type Side } from "@/editor/core/snapping.ts";
import {
  CROP_RATIOS,
  MAX_ZOOM,
  MIN_ZOOM,
  photoZoom,
  slotSource,
  type PhotoSizes,
} from "@/editor/operations";
import { Field, NumberField, PanelSection, Segmented, Slider } from "./Controls";
import { SlotQualityBadge } from "./QualityBadge";

const SIDES: Side[] = ["top", "right", "bottom", "left"];
const LOCKS: QualityLock[] = ["native", "no_upscale", "free"];

interface FramingPanelProps {
  doc: EditorDocument;
  slot: DocSlot | null;
  sizes: PhotoSizes;
  /** Stage scale, so margin snapping uses the §7.5 tolerance of 8 *screen* pixels. */
  stageScale: number;
  onSnap: (side: Side, value: number | null) => void;
}

export function FramingPanel({ doc, slot, sizes, stageScale, onSnap }: FramingPanelProps) {
  const { t } = useTranslation();
  const source = slot ? slotSource(slot, sizes) : null;
  const single = doc.slots.length === 1;

  /**
   * A dragged margin snaps to the stops of §7.5; a *typed* one never does — the tolerance is 8
   * screen pixels, which at a fitted stage is tens of document pixels, so snapping a typed value
   * would silently swallow it (entering `1` next to a `0` margin gave `0` back).
   */
  const changeMargin = (side: Side, raw: number, snapping: boolean) => {
    let value = Math.max(0, Math.round(raw));
    if (slot && snapping) {
      const crop = slot.source.crop;
      const candidates = marginCandidates(side, doc.margins, { w: crop.w, h: crop.h });
      const result = snap(value, candidates, TOLERANCE_PX / Math.max(stageScale, 0.001));
      value = result.value;
      onSnap(side, result.hit ? result.value : null);
    }
    actions.setMargins({ [side]: value });
  };

  const zoom = slot ? photoZoom(slot, sizes) : null;

  return (
    <>
      <PanelSection
        title={t("editor.sections.framing")}
        action={slot ? <SlotQualityBadge slot={slot} /> : undefined}
      >
        <Segmented
          label={t("editor.placement.label")}
          value={doc.placement}
          onChange={actions.setPlacement}
          options={[
            { value: "fit_in_mat", label: t("editor.placement.fit_in_mat"), disabled: !single },
            { value: "fill", label: t("editor.placement.fill"), disabled: !single },
            { value: "manual", label: t("editor.placement.manual"), disabled: !single },
          ]}
        />
        {slot && (
          <Segmented
            label={t("editor.lock.label")}
            value={slot.quality_lock}
            onChange={actions.setLock}
            options={LOCKS.map((lock) => ({
              value: lock,
              label: t(`editor.lock.${lock}`),
              title: t(`editor.lock.${lock}Hint`),
            }))}
          />
        )}
      </PanelSection>

      {doc.placement === "fit_in_mat" && (
        <PanelSection
          title={t("editor.sections.margins")}
          action={
            <div className="flex items-center gap-1">
              <Toggle
                pressed={doc.margins.linked}
                title={t("editor.margins.link")}
                onClick={() => actions.setMargins({ linked: !doc.margins.linked }, null)}
              >
                {doc.margins.linked ? <Link2 size={14} /> : <Link2Off size={14} />}
              </Toggle>
              <Toggle
                pressed={doc.margins.linked || doc.margins.mirror_x}
                disabled={doc.margins.linked}
                title={t("editor.margins.mirrorX")}
                onClick={() =>
                  actions.setMargins(
                    { mirror_x: !doc.margins.mirror_x, left: doc.margins.left },
                    null,
                  )
                }
              >
                <UnfoldHorizontal size={14} />
              </Toggle>
              <Toggle
                pressed={doc.margins.linked || doc.margins.mirror_y}
                disabled={doc.margins.linked}
                title={t("editor.margins.mirrorY")}
                onClick={() =>
                  actions.setMargins({ mirror_y: !doc.margins.mirror_y, top: doc.margins.top }, null)
                }
              >
                <UnfoldVertical size={14} />
              </Toggle>
            </div>
          }
        >
          {SIDES.map((side) => (
            <Field key={side} label={t(`editor.sides.${side}`)}>
              <Slider
                value={doc.margins[side]}
                min={0}
                max={side === "left" || side === "right" ? 1800 : 1000}
                onChange={(value) => changeMargin(side, value, true)}
                onCommit={() => onSnap(side, null)}
              />
              <NumberField
                value={doc.margins[side]}
                min={0}
                max={side === "left" || side === "right" ? doc.canvas.width - 1 : doc.canvas.height - 1}
                onChange={(value) => changeMargin(side, value, false)}
                suffix="px"
              />
            </Field>
          ))}
        </PanelSection>
      )}

      {slot && (
        <PanelSection title={t("editor.sections.photo")}>
          <Field label={t("editor.cropRatio")}>
            <select
              className="h-7 min-w-0 flex-1 rounded border border-border bg-panel-2 px-1 text-xs"
              value={slot.source.crop_ratio}
              onChange={(event) => actions.setCropRatio(event.target.value)}
            >
              {CROP_RATIOS.map((ratio) => (
                <option key={ratio} value={ratio}>
                  {ratio === "original" || ratio === "free" ? t(`editor.ratios.${ratio}`) : ratio}
                </option>
              ))}
            </select>
          </Field>
          {zoom !== null && (
            <Field label={t("editor.zoom")}>
              <Slider
                value={zoom}
                min={MIN_ZOOM}
                max={MAX_ZOOM}
                step={0.01}
                onChange={actions.setZoom}
              />
              <NumberField
                value={zoom}
                min={MIN_ZOOM}
                max={MAX_ZOOM}
                step={0.1}
                onChange={actions.setZoom}
                suffix="×"
              />
            </Field>
          )}
          <div className="flex items-center gap-1.5">
            <IconButton title={t("editor.orient.rotateLeft")} onClick={() => actions.rotateSource(-1)}>
              <RotateCcw size={14} />
            </IconButton>
            <IconButton title={t("editor.orient.rotateRight")} onClick={() => actions.rotateSource(1)}>
              <RotateCw size={14} />
            </IconButton>
            <IconButton title={t("editor.orient.flip")} onClick={actions.flipSource}>
              <FlipHorizontal size={14} />
            </IconButton>
            {source && (
              <span className="ml-auto text-[11px] text-muted tabular-nums">
                {source.w} × {source.h}
              </span>
            )}
          </div>
          <Field label={t("editor.rotation")}>
            <Slider
              value={slot.rotation}
              min={-45}
              max={45}
              step={0.1}
              onChange={actions.setRotation}
            />
            <NumberField
              value={slot.rotation}
              min={-180}
              max={180}
              step={0.1}
              onChange={actions.setRotation}
              suffix="°"
            />
          </Field>
        </PanelSection>
      )}
    </>
  );
}

/** Small pressed/unpressed toggle (margin link and mirrors). */
function Toggle({
  pressed,
  title,
  onClick,
  disabled,
  children,
}: {
  pressed: boolean;
  title: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      aria-label={title}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "rounded p-0.5 text-muted hover:text-text disabled:opacity-50 disabled:hover:text-muted",
        pressed && "bg-panel-2 text-text",
      )}
    >
      {children}
    </button>
  );
}

function IconButton({
  title,
  onClick,
  children,
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className="inline-flex h-7 w-7 items-center justify-center rounded border border-border text-muted hover:text-text"
    >
      {children}
    </button>
  );
}
