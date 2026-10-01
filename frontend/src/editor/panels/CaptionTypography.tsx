// A caption's typography — font, weight, size, colour, spacing — shared by the two editors.
//
// In Advanced these are the selected caption's fields; in Simple they are the derived caption's
// (docs/simple-editor.md §3.7: the block owns the text and the side, the document the typography).
// One component, so a font offered in one mode is offered in the other.
//
// The font catalogue comes from `GET /fonts`, which is also what the renderer uses, so a weight
// offered here always exists in the bundled files (the server rejects the others).
import { useTranslation } from "react-i18next";

import { useFonts } from "@/api/queries";
import type { DocCaption } from "@/editor/core/document.ts";
import { ColorField } from "./ColorField";
import { Field, NumberField, Slider } from "./Controls";

export type TypographyPatch = Partial<
  Pick<DocCaption, "font" | "weight" | "size" | "color" | "letter_spacing">
>;

export function CaptionTypography({
  caption,
  photoId,
  onChange,
}: {
  caption: DocCaption;
  /** Photo whose palette the colour picker offers. */
  photoId: string | null;
  /** `group` is the undo group: `null` commits a step of its own, a name coalesces a drag. */
  onChange: (patch: TypographyPatch, group: string | null) => void;
}) {
  const { t } = useTranslation();
  const fonts = useFonts();
  const families = fonts.data ?? [];
  const weights = families.find((item) => item.id === caption.font)?.weights ?? [caption.weight];
  return (
    <>
      <Field label={t("editor.captions.font")}>
        <select
          className="h-7 min-w-0 flex-1 rounded border border-border bg-panel-2 px-1 text-xs"
          value={caption.font}
          onChange={(event) => {
            const next = families.find((item) => item.id === event.target.value);
            onChange(
              {
                font: event.target.value,
                // The weight must exist in the new family, or the server rejects the document.
                weight: next?.weights.includes(caption.weight)
                  ? caption.weight
                  : (next?.weights[0] ?? caption.weight),
              },
              null,
            );
          }}
        >
          {families.map((item) => (
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
          onChange={(event) => onChange({ weight: Number(event.target.value) }, null)}
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
          step={2}
          onChange={(size) => onChange({ size }, "caption-size")}
        />
        <NumberField
          value={caption.size}
          min={4}
          max={1000}
          suffix="px"
          onChange={(size) => onChange({ size }, "caption-size")}
        />
      </Field>
      <Field label={t("editor.captions.color")}>
        <ColorField
          color={caption.color}
          onChange={(color) => onChange({ color }, "caption-color")}
          label={t("editor.captions.color")}
          photoId={photoId}
        />
      </Field>
      <Field label={t("editor.captions.letterSpacing")}>
        <Slider
          value={caption.letter_spacing}
          min={-0.1}
          max={0.5}
          step={0.005}
          onChange={(value) => onChange({ letter_spacing: value }, "caption-spacing")}
        />
        <NumberField
          value={caption.letter_spacing}
          min={-0.5}
          max={2}
          step={0.01}
          suffix="em"
          onChange={(value) => onChange({ letter_spacing: value }, "caption-spacing")}
        />
      </Field>
    </>
  );
}
