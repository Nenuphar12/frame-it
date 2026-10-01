// Captions: the list, and every property of the selected one (§14 phase 6, item 4). The
// typography fields are `CaptionTypography`, shared with the Simple panel.
import { Plus, Trash2, Type } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useFonts } from "@/api/queries";
import * as actions from "@/editor/actions";
import type { CaptionAnchor, DocCaption, EditorDocument } from "@/editor/core/document.ts";
import { CAPTION_DEFAULTS, MAX_CAPTIONS } from "@/editor/operations";
import { cn } from "@/shared/cn";
import { CaptionTypography } from "./CaptionTypography";
import { Field, IconButton, NumberField, PanelSection, Segmented, Slider } from "./Controls";

const ANCHORS: CaptionAnchor[] = ["start", "middle", "end"];

interface CaptionsPanelProps {
  doc: EditorDocument;
  caption: DocCaption | null;
  onSelect: (captionId: string | null) => void;
}

export function CaptionsPanel({ doc, caption, onSelect }: CaptionsPanelProps) {
  const { t } = useTranslation();
  const fonts = useFonts();

  const add = () => {
    const first = fonts.data?.[0];
    actions.addCaption(t("editor.captions.placeholder"), {
      font: first?.id ?? CAPTION_DEFAULTS.font,
      weight: first?.weights.includes(CAPTION_DEFAULTS.weight)
        ? CAPTION_DEFAULTS.weight
        : (first?.weights[0] ?? CAPTION_DEFAULTS.weight),
    });
  };

  return (
    <PanelSection
      title={t("editor.sections.captions")}
      action={
        <div className="flex items-center gap-1">
          <IconButton
            title={t("editor.captions.add")}
            disabled={doc.captions.length >= MAX_CAPTIONS}
            onClick={add}
          >
            <Plus size={14} />
          </IconButton>
          <IconButton
            title={t("editor.captions.remove")}
            disabled={!caption}
            onClick={actions.removeCaption}
          >
            <Trash2 size={14} />
          </IconButton>
        </div>
      }
    >
      {doc.captions.length === 0 && (
        <p className="text-[11px] text-muted">{t("editor.captions.none")}</p>
      )}
      {doc.captions.length > 0 && (
        <ul className="flex flex-col gap-1">
          {doc.captions.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onSelect(item.id)}
                className={cn(
                  "flex w-full items-center gap-2 truncate rounded border border-border px-1.5 py-1 text-left text-xs",
                  item.id === caption?.id && "border-accent bg-panel-2",
                )}
              >
                <Type size={12} className="shrink-0 text-muted" />
                <span className="truncate">{item.text}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {caption && (
        <>
          <Field label={t("editor.captions.text")}>
            <input
              type="text"
              value={caption.text}
              onChange={(event) => actions.updateCaption({ text: event.target.value }, "caption-text")}
              className="h-7 min-w-0 flex-1 rounded border border-border bg-panel-2 px-1.5 text-xs"
            />
          </Field>
          <CaptionTypography
            caption={caption}
            photoId={doc.slots[0]?.photo_id ?? null}
            onChange={(patch, group) => actions.updateCaption(patch, group)}
          />
          <Segmented
            label={t("editor.captions.anchor")}
            value={caption.anchor}
            onChange={(anchor: CaptionAnchor) => actions.updateCaption({ anchor })}
            options={ANCHORS.map((anchor) => ({
              value: anchor,
              label: t(`editor.captions.anchors.${anchor}`),
            }))}
          />
          <Field label={t("editor.captions.position")}>
            <NumberField
              value={caption.x}
              min={-20000}
              max={20000}
              onChange={(x) => actions.updateCaption({ x }, "caption-move")}
              suffix="x"
            />
            <NumberField
              value={caption.y}
              min={-20000}
              max={20000}
              onChange={(y) => actions.updateCaption({ y }, "caption-move")}
              suffix="y"
            />
          </Field>
          <Field label={t("editor.rotation")}>
            <Slider
              value={caption.rotation}
              min={-45}
              max={45}
              step={0.1}
              onChange={(rotation) => actions.updateCaption({ rotation }, "caption-rotation")}
            />
            <NumberField
              value={caption.rotation}
              min={-180}
              max={180}
              step={0.1}
              onChange={(rotation) => actions.updateCaption({ rotation }, "caption-rotation")}
              suffix="°"
            />
          </Field>
        </>
      )}
    </PanelSection>
  );
}
