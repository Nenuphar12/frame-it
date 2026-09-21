// Captions: the list, and every property of the selected one (§14 phase 6, item 4).
//
// The font catalogue comes from `GET /fonts`, which is also what the renderer uses, so a weight
// offered here always exists in the bundled files (the server rejects the others).
import { Plus, Trash2, Type } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useFonts } from "@/api/queries";
import * as actions from "@/editor/actions";
import type { CaptionAnchor, DocCaption, EditorDocument } from "@/editor/core/document.ts";
import { CAPTION_DEFAULTS, MAX_CAPTIONS } from "@/editor/operations";
import { cn } from "@/shared/cn";
import { ColorField } from "./ColorField";
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
  const font = (fonts.data ?? []).find((item) => item.id === caption?.font);
  const weights = font?.weights ?? [CAPTION_DEFAULTS.weight];

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
          <Field label={t("editor.captions.font")}>
            <select
              className="h-7 min-w-0 flex-1 rounded border border-border bg-panel-2 px-1 text-xs"
              value={caption.font}
              onChange={(event) => {
                const next = (fonts.data ?? []).find((item) => item.id === event.target.value);
                actions.updateCaption({
                  font: event.target.value,
                  // The weight must exist in the new family, or the server rejects the document.
                  weight: next?.weights.includes(caption.weight)
                    ? caption.weight
                    : (next?.weights[0] ?? caption.weight),
                });
              }}
            >
              {(fonts.data ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("editor.captions.weight")}>
            <select
              className="h-7 min-w-0 flex-1 rounded border border-border bg-panel-2 px-1 text-xs"
              value={caption.weight}
              onChange={(event) => actions.updateCaption({ weight: Number(event.target.value) })}
            >
              {weights.map((weight) => (
                <option key={weight} value={weight}>
                  {weight}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("editor.captions.size")}>
            <Slider
              value={caption.size}
              min={16}
              max={320}
              onChange={(size) => actions.updateCaption({ size }, "caption-size")}
            />
            <NumberField
              value={caption.size}
              min={4}
              max={1000}
              onChange={(size) => actions.updateCaption({ size }, "caption-size")}
              suffix="px"
            />
          </Field>
          <Field label={t("editor.captions.color")}>
            <ColorField
              color={caption.color}
              onChange={(color) => actions.updateCaption({ color }, "caption-color")}
              label={t("editor.captions.color")}
              photoId={doc.slots[0]?.photo_id ?? null}
            />
          </Field>
          <Field label={t("editor.captions.letterSpacing")}>
            <Slider
              value={caption.letter_spacing}
              min={-0.1}
              max={0.5}
              step={0.005}
              onChange={(value) => actions.updateCaption({ letter_spacing: value }, "caption-spacing")}
            />
            <NumberField
              value={caption.letter_spacing}
              min={-0.5}
              max={2}
              step={0.01}
              onChange={(value) => actions.updateCaption({ letter_spacing: value }, "caption-spacing")}
              suffix="em"
            />
          </Field>
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
