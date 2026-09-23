// Decoration controls: mat colour and texture, bands around the photo, inner/drop shadow.
import { Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useTextures } from "@/api/queries";
import * as actions from "@/editor/actions";
import type { DocSlot, EditorDocument } from "@/editor/core/document.ts";
import { ColorField } from "./ColorField";
import { Field, NumberField, PanelSection, Slider } from "./Controls";
import { ShadowFields } from "./ShadowFields";

const MAX_BANDS = 3;

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
                onClick={() => actions.setBands([...slot.bands, { width: 12, color: "#FFFFFF" }])}
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
          <ShadowFields
            shadow={shadow}
            photoId={photoId}
            onChange={(next, group) => actions.setShadow(next, group)}
          />
        </PanelSection>
      )}
    </>
  );
}
