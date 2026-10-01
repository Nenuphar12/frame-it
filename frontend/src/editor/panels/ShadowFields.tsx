// The shadow control, shared by the three places that dress a photo: the Simple panel, the
// Advanced Style panel and the frame-style template editor (docs/templates.md §7).
//
// One component on purpose — a shadow edited in a template and a shadow edited on an artwork are
// the same six numbers, and the style editor used to offer a subset (type and opacity), which read
// as "a template cannot say that" rather than "we did not wire it up" (remarks.md #2).
import { useTranslation } from "react-i18next";

import type { EdgeShadow, Shadow } from "@/editor/core/document.ts";
import { ColorField } from "./ColorField";
import { Field, NumberField, PercentField, Segmented, Slider } from "./Controls";

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
        <ShadowNumbers
          shadow={shadow}
          photoId={photoId}
          prefix="shadow"
          onChange={(patch, group) => set(patch, group)}
        />
      )}
    </>
  );
}

/** What the frame's shadow starts from: soft, from above, light enough to sit under a real bezel. */
const DEFAULT_EDGE_SHADOW: EdgeShadow = {
  offset_x: 0,
  offset_y: 10,
  blur: 60,
  color: "#000000",
  opacity: 0.22,
};

/**
 * The frame's shadow on the artwork (`edge_shadow`, rendering-spec.md §8.1): the same five numbers
 * as a photo's shadow, without a kind — it is always cast inwards, from the edge of the screen.
 */
export function EdgeShadowFields({
  shadow,
  onChange,
  photoId = null,
}: {
  shadow: EdgeShadow | null;
  onChange: (shadow: EdgeShadow | null, group: string | null) => void;
  photoId?: string | null;
}) {
  const { t } = useTranslation();
  return (
    <>
      <Field label={t("editor.edgeShadow.label")}>
        <Segmented
          label={t("editor.edgeShadow.label")}
          value={shadow ? "on" : "off"}
          onChange={(value) => onChange(value === "on" ? DEFAULT_EDGE_SHADOW : null, null)}
          options={[
            { value: "off", label: t("common.off") },
            { value: "on", label: t("common.on"), title: t("editor.edgeShadow.hint") },
          ]}
        />
      </Field>
      {shadow && (
        <ShadowNumbers
          shadow={shadow}
          photoId={photoId}
          prefix="edge-shadow"
          onChange={(patch, group) => onChange({ ...shadow, ...patch }, group)}
        />
      )}
    </>
  );
}

/** Blur, opacity, offset and colour — what a photo's shadow and the frame's have in common. */
function ShadowNumbers({
  shadow,
  photoId,
  prefix,
  onChange,
}: {
  shadow: EdgeShadow;
  photoId: string | null;
  /** Undo-group prefix, so dragging one shadow's slider never merges into the other's. */
  prefix: string;
  onChange: (patch: Partial<EdgeShadow>, group: string | null) => void;
}) {
  const { t } = useTranslation();
  const set = (patch: Partial<EdgeShadow>, field: string) => onChange(patch, `${prefix}-${field}`);
  return (
    <>
      <Field label={t("editor.shadow.blur")}>
        <Slider value={shadow.blur} min={0} max={200} onChange={(blur) => set({ blur }, "blur")} />
        <NumberField
          value={shadow.blur}
          min={0}
          max={200}
          onChange={(blur) => set({ blur }, "blur")}
        />
      </Field>
      <Field label={t("editor.shadow.opacity")}>
        <Slider
          value={shadow.opacity}
          min={0}
          max={1}
          step={0.01}
          onChange={(opacity) => set({ opacity }, "opacity")}
        />
        <PercentField value={shadow.opacity} onChange={(opacity) => set({ opacity }, "opacity")} />
      </Field>
      <Field label={t("editor.shadow.offset")}>
        <NumberField
          value={shadow.offset_x}
          min={-500}
          max={500}
          onChange={(offset_x) => set({ offset_x }, "offset")}
          suffix="x"
        />
        <NumberField
          value={shadow.offset_y}
          min={-500}
          max={500}
          onChange={(offset_y) => set({ offset_y }, "offset")}
          suffix="y"
        />
      </Field>
      <Field label={t("editor.shadow.color")}>
        <ColorField
          color={shadow.color}
          label={t("editor.shadow.color")}
          photoId={photoId}
          onChange={(color) => set({ color }, "color")}
        />
      </Field>
    </>
  );
}
