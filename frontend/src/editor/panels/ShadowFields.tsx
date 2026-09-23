// The shadow control, shared by the three places that dress a photo: the Simple panel, the
// Advanced Style panel and the frame-style template editor (docs/templates.md §7).
//
// One component on purpose — a shadow edited in a template and a shadow edited on an artwork are
// the same six numbers, and the style editor used to offer a subset (type and opacity), which read
// as "a template cannot say that" rather than "we did not wire it up" (remarks.md #2).
import { useTranslation } from "react-i18next";

import type { Shadow } from "@/editor/core/document.ts";
import { ColorField } from "./ColorField";
import { Field, NumberField, Segmented, Slider } from "./Controls";

/** What `None → Recessed/Raised` starts from: the look of the built-in styles. */
const DEFAULT_SHADOW: Shadow = {
  type: "inner",
  offset_x: 0,
  offset_y: 6,
  blur: 28,
  color: "#000000",
  opacity: 0.45,
};

export function ShadowFields({
  shadow,
  onChange,
  photoId = null,
}: {
  shadow: Shadow | null;
  /** `group` is the undo group: `null` commits a step of its own (a click), a name coalesces. */
  onChange: (shadow: Shadow | null, group: string | null) => void;
  /** Photo whose palette the colour picker offers; `null` outside the editor. */
  photoId?: string | null;
}) {
  const { t } = useTranslation();
  const set = (patch: Partial<Shadow>, group: string | null) =>
    onChange({ ...(shadow ?? DEFAULT_SHADOW), ...patch }, group);
  return (
    <>
      <Segmented
        label={t("editor.shadow.label")}
        value={shadow?.type ?? "none"}
        onChange={(value) =>
          value === "none" ? onChange(null, null) : set({ type: value as Shadow["type"] }, null)
        }
        options={[
          { value: "none", label: t("editor.shadow.none") },
          { value: "inner", label: t("editor.shadow.inner") },
          { value: "drop", label: t("editor.shadow.drop") },
        ]}
      />
      {shadow && (
        <>
          <Field label={t("editor.shadow.blur")}>
            <Slider
              value={shadow.blur}
              min={0}
              max={200}
              onChange={(blur) => set({ blur }, "shadow-blur")}
            />
            <NumberField
              value={shadow.blur}
              min={0}
              max={200}
              onChange={(blur) => set({ blur }, "shadow-blur")}
            />
          </Field>
          <Field label={t("editor.shadow.opacity")}>
            <Slider
              value={shadow.opacity}
              min={0}
              max={1}
              step={0.01}
              onChange={(opacity) => set({ opacity }, "shadow-opacity")}
            />
            <span className="w-8 shrink-0 text-right text-[11px] text-muted tabular-nums">
              {Math.round(shadow.opacity * 100)}
            </span>
          </Field>
          <Field label={t("editor.shadow.offset")}>
            <NumberField
              value={shadow.offset_x}
              min={-500}
              max={500}
              onChange={(offset_x) => set({ offset_x }, "shadow-offset")}
              suffix="x"
            />
            <NumberField
              value={shadow.offset_y}
              min={-500}
              max={500}
              onChange={(offset_y) => set({ offset_y }, "shadow-offset")}
              suffix="y"
            />
          </Field>
          <Field label={t("editor.shadow.color")}>
            <ColorField
              color={shadow.color}
              label={t("editor.shadow.color")}
              photoId={photoId}
              onChange={(color) => set({ color }, "shadow-color")}
            />
          </Field>
        </>
      )}
    </>
  );
}
