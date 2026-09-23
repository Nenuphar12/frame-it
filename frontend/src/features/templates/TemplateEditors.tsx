// Editing a template: a style is a look, a layout is a recipe and its parameters.
//
// Both dialogs edit a *copy* and save once — editing a template never touches an artwork
// (docs/templates.md §5), so there is nothing to preview against and no autosave to arbitrate.
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, type LayoutDocumentApi, type StyleDocumentApi } from "@/api/client";
import { useRecipes } from "@/api/queries";
import { RecipePicker } from "@/editor/panels/RecipePicker";
import { Field, NumberField, Segmented, Slider } from "@/editor/panels/Controls";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Spinner } from "@/shared/ui/Misc";

import { LayoutPreview, StylePreview } from "./TemplatePreview";

const FORMATS = ["fill", "original", "1:1", "5:4", "4:3", "3:2", "16:9"] as const;

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-24 shrink-0 text-muted">{label}</span>
      {children}
    </div>
  );
}

function ColorInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <span className="flex items-center gap-1.5">
      <input
        type="color"
        value={value}
        onChange={(event) => onChange(event.target.value.toUpperCase())}
        className="h-7 w-10 rounded border border-border bg-panel-2"
      />
      <span className="font-mono text-[11px] text-muted">{value}</span>
    </span>
  );
}

function Error({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="text-sm text-danger">
      {error instanceof ApiError
        ? t(`errors.${error.code}`, { defaultValue: error.message })
        : t("errors.unknown")}
    </p>
  );
}

export function StyleEditorDialog({
  open,
  onOpenChange,
  initialName,
  initialDocument,
  onSubmit,
  pending,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialName: string;
  initialDocument: StyleDocumentApi;
  onSubmit: (name: string, document: StyleDocumentApi) => void;
  pending: boolean;
  error: unknown;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(initialName);
  const [document, setDocument] = useState(initialDocument);
  const mat = document.mat ?? { color: "#F2EFE8", texture: null };
  const defaults = document.slot_defaults ?? {
    bands: [],
    shadow: null,
    quality_lock: "no_upscale" as const,
  };
  const band = defaults.bands?.[0] ?? null;
  const shadow = defaults.shadow ?? null;
  const caption = document.caption_defaults;
  const patch = (next: Partial<StyleDocumentApi>) => setDocument({ ...document, ...next });

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("templates.editStyle")}
      className="w-[min(94vw,46rem)]"
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(name.trim(), document);
        }}
      >
        <div className="grid gap-4 sm:grid-cols-[1fr_16rem]">
          <div className="flex flex-col gap-2">
            <Row label={t("templates.name")}>
              <input
                className="h-7 w-full rounded border border-border bg-panel-2 px-2 text-xs"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </Row>
            <Row label={t("templates.matColor")}>
              <ColorInput
                value={mat.color}
                onChange={(color) => patch({ mat: { ...mat, color } })}
              />
            </Row>
            <Row label={t("templates.border")}>
              <Segmented
                value={band ? "on" : "off"}
                label={t("templates.border")}
                options={[
                  { value: "off", label: t("common.off") },
                  { value: "on", label: t("common.on") },
                ]}
                onChange={(value) =>
                  patch({
                    slot_defaults: {
                      ...defaults,
                      bands: value === "on" ? [band ?? { width: 12, color: "#FFFFFF" }] : [],
                    },
                  })
                }
              />
            </Row>
            {band && (
              <>
                <Row label={t("templates.borderWidth")}>
                  <Slider
                    value={band.width}
                    min={1}
                    max={120}
                    onChange={(width) =>
                      patch({
                        slot_defaults: { ...defaults, bands: [{ ...band, width }] },
                      })
                    }
                  />
                  <NumberField
                    value={band.width}
                    min={1}
                    max={120}
                    onChange={(width) =>
                      patch({ slot_defaults: { ...defaults, bands: [{ ...band, width }] } })
                    }
                    suffix="px"
                  />
                </Row>
                <Row label={t("templates.borderColor")}>
                  <ColorInput
                    value={band.color}
                    onChange={(color) =>
                      patch({ slot_defaults: { ...defaults, bands: [{ ...band, color }] } })
                    }
                  />
                </Row>
              </>
            )}
            <Row label={t("templates.shadow")}>
              <Segmented
                value={shadow ? shadow.type : "none"}
                label={t("templates.shadow")}
                options={[
                  { value: "none", label: t("common.off") },
                  { value: "inner", label: t("templates.shadowInner") },
                  { value: "drop", label: t("templates.shadowDrop") },
                ]}
                onChange={(value) =>
                  patch({
                    slot_defaults: {
                      ...defaults,
                      shadow:
                        value === "none"
                          ? null
                          : {
                              type: value,
                              offset_x: shadow?.offset_x ?? 0,
                              offset_y: shadow?.offset_y ?? 6,
                              blur: shadow?.blur ?? 28,
                              color: shadow?.color ?? "#000000",
                              opacity: shadow?.opacity ?? 0.4,
                            },
                    },
                  })
                }
              />
            </Row>
            {shadow && (
              <Row label={t("templates.shadowOpacity")}>
                <Slider
                  value={Math.round(shadow.opacity * 100)}
                  min={0}
                  max={100}
                  onChange={(value) =>
                    patch({
                      slot_defaults: { ...defaults, shadow: { ...shadow, opacity: value / 100 } },
                    })
                  }
                />
                <span className="w-10 text-right tabular-nums">
                  {Math.round(shadow.opacity * 100)}%
                </span>
              </Row>
            )}
            {caption && (
              <>
                <Row label={t("templates.captionSize")}>
                  <Slider
                    value={caption.size}
                    min={16}
                    max={200}
                    onChange={(size) => patch({ caption_defaults: { ...caption, size } })}
                  />
                  <NumberField
                    value={caption.size}
                    min={4}
                    max={1000}
                    onChange={(size) => patch({ caption_defaults: { ...caption, size } })}
                    suffix="px"
                  />
                </Row>
                <Row label={t("templates.captionColor")}>
                  <ColorInput
                    value={caption.color}
                    onChange={(color) => patch({ caption_defaults: { ...caption, color } })}
                  />
                </Row>
              </>
            )}
          </div>
          <div className="aspect-video overflow-hidden rounded border border-border">
            <StylePreview style={document} />
          </div>
        </div>
        <Error error={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" variant="primary" disabled={pending || !name.trim()}>
            {pending && <Spinner size={14} />}
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function LayoutEditorDialog({
  open,
  onOpenChange,
  initialName,
  initialDocument,
  onSubmit,
  pending,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialName: string;
  initialDocument: LayoutDocumentApi;
  onSubmit: (name: string, document: LayoutDocumentApi) => void;
  pending: boolean;
  error: unknown;
}) {
  const { t } = useTranslation();
  const recipes = useRecipes();
  const [name, setName] = useState(initialName);
  const [document, setDocument] = useState(initialDocument);
  const recipe = (recipes.data ?? []).find((entry) => entry.id === document.recipe);
  const outer = document.outer ?? { x: 120, y: 120 };
  const gutter = document.gutter ?? { x: 80, y: 80 };
  const border = document.border ?? null;
  const patch = (next: Partial<LayoutDocumentApi>) => setDocument({ ...document, ...next });

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("templates.editLayout")}
      className="w-[min(94vw,46rem)]"
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(name.trim(), document);
        }}
      >
        <Row label={t("templates.name")}>
          <input
            className="h-7 w-full rounded border border-border bg-panel-2 px-2 text-xs"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </Row>
        <div className="grid gap-4 sm:grid-cols-[1fr_16rem]">
          <div className="flex flex-col gap-2">
            <span className="text-[11px] font-semibold tracking-wide text-muted uppercase">
              {t("editor.simple.layout")}
            </span>
            <RecipePicker
              recipes={recipes.data ?? []}
              selected={document.recipe}
              onSelect={(id) => patch({ recipe: id, balance: null })}
            />
            <Field label={t("editor.simple.format")}>
              <select
                className="h-7 w-full rounded border border-border bg-panel-2 px-1.5 text-xs"
                value={document.format ?? "fill"}
                onChange={(event) => patch({ format: event.target.value })}
              >
                {FORMATS.map((value) => (
                  <option key={value} value={value}>
                    {t(`editor.simple.formats.${value}`, { defaultValue: value })}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("editor.simple.outer")}>
              <Slider
                value={outer.x}
                min={0}
                max={800}
                onChange={(x) => patch({ outer: { ...outer, x } })}
              />
              <NumberField
                value={outer.x}
                min={0}
                max={800}
                onChange={(x) => patch({ outer: { ...outer, x } })}
              />
            </Field>
            <Field label={`${t("editor.simple.outer")} ↕`}>
              <Slider
                value={outer.y}
                min={0}
                max={450}
                onChange={(y) => patch({ outer: { ...outer, y } })}
              />
              <NumberField
                value={outer.y}
                min={0}
                max={450}
                onChange={(y) => patch({ outer: { ...outer, y } })}
              />
            </Field>
            <Field label={t("editor.simple.gap")}>
              <Slider
                value={gutter.x}
                min={0}
                max={400}
                onChange={(x) => patch({ gutter: { x, y: x } })}
              />
              <NumberField
                value={gutter.x}
                min={0}
                max={400}
                onChange={(x) => patch({ gutter: { x, y: x } })}
              />
            </Field>
            <Field label={t("templates.border")}>
              <Segmented
                value={border ? "on" : "off"}
                label={t("templates.border")}
                options={[
                  { value: "off", label: t("common.off") },
                  { value: "on", label: t("common.on") },
                ]}
                onChange={(value) =>
                  patch({
                    border: value === "on" ? (border ?? { width: 18, color: "#FFFFFF" }) : null,
                  })
                }
              />
            </Field>
            {border && (
              <Field label={t("templates.borderWidth")}>
                <Slider
                  value={border.width}
                  min={1}
                  max={200}
                  onChange={(width) => patch({ border: { ...border, width } })}
                />
                <ColorInput
                  value={border.color}
                  onChange={(color) => patch({ border: { ...border, color } })}
                />
              </Field>
            )}
            <Field label={t("editor.simple.caption")}>
              <Segmented
                value={document.caption_place ?? "none"}
                label={t("editor.simple.caption")}
                options={[
                  { value: "none", label: t("editor.simple.places.none") },
                  { value: "above", label: t("editor.simple.places.above") },
                  { value: "below", label: t("editor.simple.places.below") },
                ]}
                onChange={(value) => patch({ caption_place: value })}
              />
            </Field>
          </div>
          <div className="aspect-video overflow-hidden rounded border border-border">
            <LayoutPreview layout={document} recipe={recipe} />
          </div>
        </div>
        <Error error={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" variant="primary" disabled={pending || !name.trim()}>
            {pending && <Spinner size={14} />}
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
