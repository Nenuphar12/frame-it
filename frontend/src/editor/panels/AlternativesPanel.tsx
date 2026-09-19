// Alternatives panel (§7.6): pops up as soon as the selected slot is enlarged, and offers only
// the ways out that are actually feasible for this photo, each with a preview of the result.
import { useTranslation } from "react-i18next";

import { photoProxyUrl } from "@/api/client";
import * as actions from "@/editor/actions";
import { alternatives, type Alternative } from "@/editor/core/alternatives.ts";
import type { DocSlot, EditorDocument } from "@/editor/core/document.ts";
import type { Rect, Size } from "@/editor/core/geometry.ts";
import { slotQuality } from "@/editor/core/quality.ts";
import { slotSource, type PhotoSizes } from "@/editor/operations";
import { Badge } from "@/shared/ui/Misc";

interface AlternativesPanelProps {
  doc: EditorDocument;
  slot: DocSlot;
  sizes: PhotoSizes;
}

export function AlternativesPanel({ doc, slot, sizes }: AlternativesPanelProps) {
  const { t } = useTranslation();
  const source = slotSource(slot, sizes);
  if (!source || !slot.photo_id) return null;
  const options = alternatives(
    { rect: slot.rect, crop: slot.source.crop },
    source,
    slot.quality_lock,
    doc.placement,
    doc.margins,
    doc.margins.linked,
    slot.source.crop_ratio,
    doc.margins.mirror_x,
    doc.margins.mirror_y,
  );
  if (options.length === 0) return null;

  return (
    <div className="border-b border-border bg-warning/5 px-3 py-3">
      <h3 className="mb-1 text-[11px] font-semibold tracking-wide text-warning uppercase">
        {t("editor.alternatives.title")}
      </h3>
      <p className="mb-2 text-[11px] text-muted">{t("editor.alternatives.description")}</p>
      <div className="flex flex-col gap-1.5">
        {options.map((option) => (
          <Option
            key={option.id}
            option={option}
            doc={doc}
            photoId={slot.photo_id!}
            source={source}
            onApply={() => actions.applyAlternative(option)}
          />
        ))}
      </div>
    </div>
  );
}

function Option({
  option,
  doc,
  photoId,
  source,
  onApply,
}: {
  option: Alternative;
  doc: EditorDocument;
  photoId: string;
  source: Size;
  onApply: () => void;
}) {
  const { t } = useTranslation();
  const quality = slotQuality({
    rect_w: option.rect.w,
    rect_h: option.rect.h,
    crop_w: option.crop.w,
    crop_h: option.crop.h,
    rotation: 0,
    has_photo: true,
  });
  return (
    <button
      type="button"
      onClick={onApply}
      className="flex items-center gap-2 rounded-md border border-border bg-panel p-1.5 text-left hover:border-accent"
    >
      <Preview
        doc={doc}
        photoId={photoId}
        source={source}
        rect={option.rect}
        crop={option.crop}
      />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs">{t(`editor.alternatives.${option.id}`)}</span>
        <span className="text-[11px] text-muted">
          {t(`editor.alternatives.${option.id}Hint`)}
        </span>
      </span>
      <Badge
        tone={
          quality.tier === "native" ? "accent" : quality.tier === "upscaled" ? "warning" : "neutral"
        }
      >
        {quality.percent}%
      </Badge>
    </button>
  );
}

/** Miniature of the result: the mat, with the photo's crop shown in the slot's rectangle. */
function Preview({
  doc,
  photoId,
  source,
  rect,
  crop,
}: {
  doc: EditorDocument;
  photoId: string;
  source: Size;
  rect: Rect;
  crop: Rect;
}) {
  const { width, height } = doc.canvas;
  const percent = (value: number, total: number) => `${(value / total) * 100}%`;
  return (
    <span
      className="relative block h-9 w-16 shrink-0 overflow-hidden rounded-sm border border-black/40"
      style={{ backgroundColor: doc.mat.color }}
    >
      <span
        className="absolute"
        style={{
          left: percent(rect.x, width),
          top: percent(rect.y, height),
          width: percent(rect.w, width),
          height: percent(rect.h, height),
          backgroundImage: `url(${photoProxyUrl(photoId)})`,
          backgroundSize: `${(source.w / crop.w) * 100}% ${(source.h / crop.h) * 100}%`,
          backgroundPosition: `${offset(crop.x, crop.w, source.w)}% ${offset(crop.y, crop.h, source.h)}%`,
        }}
      />
    </span>
  );
}

/** `background-position` percentage showing the crop inside the box (0 when it fills the axis). */
function offset(start: number, size: number, total: number): number {
  return total === size ? 0 : (start / (total - size)) * 100;
}
