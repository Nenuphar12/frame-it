// Editing a template: a style is a look, a layout is a recipe and its parameters.
//
// Both dialogs edit a *copy* and save once — editing a template never touches an artwork
// (docs/templates.md §5), so there is nothing to preview against and no autosave to arbitrate.
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type LayoutDocumentApi, type StyleDocumentApi } from "@/api/client";
import { useRecipes } from "@/api/queries";
import { ColorField } from "@/editor/panels/ColorField";
import { RecipePicker } from "@/editor/panels/RecipePicker";
import { ShadowFields } from "@/editor/panels/ShadowFields";
import { Field, NumberField, Segmented, Slider } from "@/editor/panels/Controls";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Spinner } from "@/shared/ui/Misc";
import { problemMessage } from "@/shared/problem";

import { LayoutPreview, StylePreview } from "./TemplatePreview";

const FORMATS = ["fill", "original", "1:1", "5:4", "4:3", "3:2", "16:9"] as const;

function Error({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="text-sm text-danger">
      {problemMessage(t, error)}
    </p>
  );
}

/**
 * The window both editors live in: controls in a column, the preview taking everything else.
 *
 * Full size on purpose (`Dialog size="full"`) — the preview *is* the editor here, and at dialog
 * size you cannot tell a 12 px border from an 18 px one or see where a caption band lands.
 */
function EditorShell({
  title,
  open,
  onOpenChange,
  onSubmit,
  controls,
  preview,
  error,
  pending,
  canSave,
}: {
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: () => void;
  controls: React.ReactNode;
  preview: React.ReactNode;
  error: unknown;
  pending: boolean;
  canSave: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={title} size="full">
      <form
        className="flex min-h-0 flex-1 flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        {/*
          Preview left, settings right — the artwork editor's arrangement, so the two editors
          read the same way (remarks.md #1). `row-reverse` rather than a swap in the markup: the
          controls stay first in the DOM, which is the tab order a form wants, and they stay on
          top when the dialog is too narrow to hold two columns.
        */}
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto lg:flex-row-reverse lg:overflow-visible">
          <div className="flex w-full flex-col gap-2 lg:w-[22rem] lg:shrink-0 lg:overflow-y-auto lg:border-l lg:border-border lg:pl-4">
            {controls}
          </div>
          {/* The SVG letterboxes itself inside this box, so the shadow hugs the artwork. */}
          <div className="flex min-h-64 flex-1 items-center justify-center rounded-lg bg-panel-2 p-4 [&_svg]:drop-shadow-xl">
            {preview}
          </div>
        </div>
        <Error error={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" variant="primary" disabled={pending || !canSave}>
            {pending && <Spinner size={14} />}
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
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
    <EditorShell
      title={t("templates.editStyle")}
      open={open}
      onOpenChange={onOpenChange}
      onSubmit={() => onSubmit(name.trim(), document)}
      error={error}
      pending={pending}
      canSave={Boolean(name.trim())}
      preview={<StylePreview style={document} />}
      controls={
        <>
          <Field label={t("templates.name")}>
            <input
              className="h-7 w-full rounded border border-border bg-panel-2 px-2 text-xs"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </Field>
          <Field label={t("templates.matColor")}>
            <ColorField
              color={mat.color}
              label={t("templates.matColor")}
              onChange={(color) => patch({ mat: { ...mat, color } })}
            />
          </Field>
          <Field label={t("templates.border")}>
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
          </Field>
          {band && (
            <>
              <Field label={t("templates.borderWidth")}>
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
              </Field>
              <Field label={t("templates.borderColor")}>
                <ColorField
                  color={band.color}
                  label={t("templates.borderColor")}
                  onChange={(color) =>
                    patch({ slot_defaults: { ...defaults, bands: [{ ...band, color }] } })
                  }
                />
              </Field>
            </>
          )}
          {/*
            The same control as the artwork editor's: a template that could only say "inner at
            40 %" read as a limitation of templates rather than of this dialog (remarks.md #2).
          */}
          <ShadowFields
            shadow={shadow}
            onChange={(next) => patch({ slot_defaults: { ...defaults, shadow: next } })}
          />
          {caption && (
            <>
              <Field label={t("templates.captionSize")}>
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
              </Field>
              <Field label={t("templates.captionColor")}>
                <ColorField
                  color={caption.color}
                  label={t("templates.captionColor")}
                  onChange={(color) => patch({ caption_defaults: { ...caption, color } })}
                />
              </Field>
            </>
          )}
        </>
      }
    />
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
    <EditorShell
      title={t("templates.editLayout")}
      open={open}
      onOpenChange={onOpenChange}
      onSubmit={() => onSubmit(name.trim(), document)}
      error={error}
      pending={pending}
      canSave={Boolean(name.trim())}
      preview={<LayoutPreview layout={document} recipe={recipe} />}
      controls={
        <>
          <Field label={t("templates.name")}>
            <input
              className="h-7 w-full rounded border border-border bg-panel-2 px-2 text-xs"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </Field>
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
              <ColorField
                color={border.color}
                label={t("templates.borderColor")}
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
        </>
      }
    />
  );
}
