// Decoration controls: mat colour and texture, bands around the photo, inner/drop shadow.
import { Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useTextures } from "@/api/queries";
import * as actions from "@/editor/actions";
import type { DocSlot, EditorDocument, Shadow } from "@/editor/core/document.ts";
import { ColorField } from "./ColorField";
import { Field, NumberField, PanelSection, Segmented, Slider } from "./Controls";

const MAX_BANDS = 3;

const DEFAULT_SHADOW: Shadow = {
  type: "inner",
  offset_x: 0,
  offset_y: 6,
  blur: 28,
  color: "#000000",
  opacity: 0.45,
};

export function StylePanel({ doc, slot }: { doc: EditorDocument; slot: DocSlot | null }) {
  const { t } = useTranslation();
  const textures = useTextures();
  const photoId = slot?.photo_id ?? null;
  const texture = doc.mat.texture;
  const shadow = slot?.shadow ?? null;

  return (
    <>
      <PanelSection title={t("editor.sections.mat")}>
        <Field label={t("editor.mat.color")}>
          <ColorField
            color={doc.mat.color}
            onChange={(color) => actions.setMatColor(color)}
            label={t("editor.mat.color")}
            photoId={photoId}
          />
        </Field>
        <Field label={t("editor.mat.texture")}>
          <select
            className="h-7 min-w-0 flex-1 rounded border border-border bg-panel-2 px-1 text-xs"
            value={texture?.id ?? ""}
            onChange={(event) =>
              actions.setTexture(event.target.value || null, texture?.strength ?? 0.35)
            }
          >
            <option value="">{t("editor.mat.noTexture")}</option>
            {(textures.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </Field>
        {texture && (
          <Field label={t("editor.mat.strength")}>
            <Slider
              value={texture.strength}
              min={0}
              max={1}
              step={0.01}
              onChange={(value) => actions.setTexture(texture.id, value, "texture-strength")}
            />
            <span className="w-8 text-right text-[11px] text-muted tabular-nums">
              {Math.round(texture.strength * 100)}
            </span>
          </Field>
        )}
      </PanelSection>

      {slot && (
        <PanelSection
          title={t("editor.sections.bands")}
          action={
            slot.bands.length < MAX_BANDS ? (
              <button
                type="button"
                className="inline-flex items-center gap-1 text-[11px] text-muted hover:text-text"
                onClick={() =>
                  actions.setBands([...slot.bands, { width: 12, color: "#FFFFFF" }])
                }
              >
                <Plus size={12} /> {t("editor.bands.add")}
              </button>
            ) : undefined
          }
        >
          {slot.bands.length === 0 && (
            <p className="text-[11px] text-muted">{t("editor.bands.none")}</p>
          )}
          {slot.bands.map((band, index) => (
            <div key={index} className="flex items-center gap-1.5">
              <NumberField
                value={band.width}
                min={1}
                max={400}
                onChange={(width) =>
                  actions.setBands(slot.bands.map((b, i) => (i === index ? { ...b, width } : b)))
                }
                suffix="px"
              />
              <ColorField
                color={band.color}
                label={t("editor.bands.color")}
                photoId={photoId}
                onChange={(color) =>
                  actions.setBands(slot.bands.map((b, i) => (i === index ? { ...b, color } : b)))
                }
              />
              <button
                type="button"
                aria-label={t("common.remove")}
                className="text-muted hover:text-danger"
                onClick={() => actions.setBands(slot.bands.filter((_, i) => i !== index))}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </PanelSection>
      )}

      {slot && (
        <PanelSection title={t("editor.sections.shadow")}>
          <Segmented
            label={t("editor.shadow.label")}
            value={shadow?.type ?? "none"}
            onChange={(value) =>
              actions.setShadow(
                value === "none"
                  ? null
                  : { ...(shadow ?? DEFAULT_SHADOW), type: value as Shadow["type"] },
                null,
              )
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
                  onChange={(blur) => actions.setShadow({ ...shadow, blur })}
                />
                <NumberField
                  value={shadow.blur}
                  min={0}
                  max={200}
                  onChange={(blur) => actions.setShadow({ ...shadow, blur })}
                />
              </Field>
              <Field label={t("editor.shadow.opacity")}>
                <Slider
                  value={shadow.opacity}
                  min={0}
                  max={1}
                  step={0.01}
                  onChange={(opacity) => actions.setShadow({ ...shadow, opacity })}
                />
                <span className="w-8 text-right text-[11px] text-muted tabular-nums">
                  {Math.round(shadow.opacity * 100)}
                </span>
              </Field>
              <Field label={t("editor.shadow.offset")}>
                <NumberField
                  value={shadow.offset_x}
                  min={-500}
                  max={500}
                  onChange={(offset_x) => actions.setShadow({ ...shadow, offset_x })}
                  suffix="x"
                />
                <NumberField
                  value={shadow.offset_y}
                  min={-500}
                  max={500}
                  onChange={(offset_y) => actions.setShadow({ ...shadow, offset_y })}
                  suffix="y"
                />
              </Field>
              <Field label={t("editor.shadow.color")}>
                <ColorField
                  color={shadow.color}
                  label={t("editor.shadow.color")}
                  photoId={photoId}
                  onChange={(color) => actions.setShadow({ ...shadow, color })}
                />
              </Field>
            </>
          )}
        </PanelSection>
      )}
    </>
  );
}
