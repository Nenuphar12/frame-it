// Frame styles and layouts (docs/templates.md §7).
//
// Two tabs over the same card grid: a template is a name, a self-drawn preview and the handful of
// actions that make it reusable. Built-ins are read-only — duplicate one to get an editable copy.
// Nothing here changes an artwork except "Update artworks", which is a confirmed push update.
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Download, LayoutTemplate, Pencil, Trash2, Upload, Wand2 } from "lucide-react";

import { ApiError, type FrameStyle, type Layout } from "@/api/client";
import {
  useCreateLayout,
  useCreateStyle,
  useDeleteTemplate,
  useDuplicateTemplate,
  useFrameStyles,
  useImportTemplate,
  useLayouts,
  useRecipes,
  useUpdateLayout,
  useUpdateStyle,
  type TemplateKind,
} from "@/api/queries";
import { Button } from "@/shared/ui/Button";
import { Badge, EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";
import { cn } from "@/shared/cn";

import { LayoutEditorDialog, StyleEditorDialog } from "./TemplateEditors";
import { LayoutPreview, StylePreview } from "./TemplatePreview";
import { PushUpdateDialog } from "./PushUpdateDialog";
import { downloadTemplate, fileAccept, readTemplateFile } from "./templateFile";

const NEW_STYLE = {
  mat: { color: "#F2EFE8", texture: null },
  margins: {
    top: 280,
    right: 300,
    bottom: 320,
    left: 300,
    linked: false,
    mirror_x: false,
    mirror_y: false,
  },
  slot_defaults: { bands: [], shadow: null, quality_lock: "no_upscale" as const },
  caption_defaults: {
    font: "cormorant-garamond",
    weight: 500,
    size: 48,
    color: "#3A3A3A",
    letter_spacing: 0.02,
  },
};

const NEW_LAYOUT = {
  recipe: "single",
  balance: null,
  outer: { x: 300, y: 280 },
  gutter: { x: 80, y: 80 },
  format: "original",
  cell_formats: [],
  border: null,
  caption_place: "none" as const,
};

type Editing =
  | { kind: "frame_style"; template: FrameStyle | null }
  | { kind: "layout"; template: Layout | null }
  | null;

function Card({
  name,
  builtin,
  preview,
  actions,
}: {
  name: string;
  builtin: boolean;
  preview: React.ReactNode;
  actions: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border bg-panel p-2">
      <div className="aspect-video overflow-hidden rounded border border-border">{preview}</div>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium">{name}</span>
        {builtin && <Badge>{t("templates.builtin")}</Badge>}
      </div>
      <div className="flex flex-wrap gap-1">{actions}</div>
    </li>
  );
}

export function TemplatesPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TemplateKind>("frame_style");
  const [editing, setEditing] = useState<Editing>(null);
  const [pushing, setPushing] = useState<{
    kind: TemplateKind;
    id: string;
    name: string;
    revision: number;
  } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const styles = useFrameStyles();
  const layouts = useLayouts();
  const recipes = useRecipes();
  const createStyle = useCreateStyle();
  const createLayout = useCreateLayout();
  const updateStyle = useUpdateStyle();
  const updateLayout = useUpdateLayout();
  const duplicate = useDuplicateTemplate();
  const remove = useDeleteTemplate();
  const importTemplate = useImportTemplate();

  const loading = tab === "frame_style" ? styles.isLoading : layouts.isLoading;
  const error = remove.error ?? duplicate.error ?? importTemplate.error;

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    importTemplate.mutate({ kind: tab, file: await readTemplateFile(file) });
  };

  const actionsFor = (kind: TemplateKind, template: FrameStyle | Layout) => (
    <>
      <Button
        size="sm"
        variant="ghost"
        onClick={() =>
          setEditing(
            kind === "frame_style"
              ? { kind, template: template as FrameStyle }
              : { kind, template: template as Layout },
          )
        }
        disabled={template.builtin}
        title={template.builtin ? t("templates.builtinHint") : undefined}
      >
        <Pencil size={13} /> {t("common.edit")}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => duplicate.mutate({ kind, id: template.id })}>
        <Copy size={13} /> {t("templates.duplicate")}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => downloadTemplate(kind, template.name, template.document)}
      >
        <Download size={13} /> {t("templates.export")}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() =>
          setPushing({
            kind,
            id: template.id,
            name: template.name,
            revision: template.revision,
          })
        }
      >
        <Wand2 size={13} /> {t("templates.pushUpdate")}
      </Button>
      {!template.builtin && (
        <Button
          size="sm"
          variant={confirmDelete === template.id ? "danger" : "ghost"}
          onClick={() => {
            if (confirmDelete === template.id) {
              remove.mutate({ kind, id: template.id });
              setConfirmDelete(null);
            } else {
              setConfirmDelete(template.id);
            }
          }}
        >
          <Trash2 size={13} />
          {confirmDelete === template.id ? t("templates.confirmDelete") : t("common.delete")}
        </Button>
      )}
    </>
  );

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("nav.templates")}
        subtitle={t("templates.subtitle")}
        actions={
          <>
            <input
              ref={fileInput}
              type="file"
              accept={fileAccept(tab)}
              className="hidden"
              onChange={(event) => {
                void pickFile(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            <Button size="sm" variant="ghost" onClick={() => fileInput.current?.click()}>
              <Upload size={14} /> {t("templates.import")}
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() =>
                setEditing(
                  tab === "frame_style"
                    ? { kind: "frame_style", template: null }
                    : { kind: "layout", template: null },
                )
              }
            >
              {t("templates.new")}
            </Button>
          </>
        }
      />
      <div className="flex items-center gap-1 border-b border-border px-5 py-2">
        {(["frame_style", "layout"] as TemplateKind[]).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm text-muted hover:bg-panel-2",
              tab === value && "bg-panel-2 text-text",
            )}
          >
            {t(`templates.tabs.${value}`)}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-5">
        {error instanceof ApiError && (
          <p className="mb-3 text-sm text-danger">
            {t(`errors.${error.code}`, { defaultValue: error.message })}
          </p>
        )}
        {loading && <Spinner />}
        {tab === "frame_style" && !loading && (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {(styles.data ?? []).map((style) => (
              <Card
                key={style.id}
                name={style.name}
                builtin={style.builtin}
                preview={<StylePreview style={style.document} />}
                actions={actionsFor("frame_style", style)}
              />
            ))}
          </ul>
        )}
        {tab === "layout" && !loading && (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {(layouts.data ?? []).map((layout) => (
              <Card
                key={layout.id}
                name={layout.name}
                builtin={layout.builtin}
                preview={
                  <LayoutPreview
                    layout={layout.document}
                    recipe={(recipes.data ?? []).find((r) => r.id === layout.document.recipe)}
                  />
                }
                actions={actionsFor("layout", layout)}
              />
            ))}
          </ul>
        )}
        {!loading &&
          ((tab === "frame_style" && (styles.data ?? []).length === 0) ||
            (tab === "layout" && (layouts.data ?? []).length === 0)) && (
            <EmptyState
              icon={<LayoutTemplate size={28} />}
              title={t("templates.empty")}
              description={t("templates.emptyHint")}
            />
          )}
      </div>

      {editing?.kind === "frame_style" && (
        <StyleEditorDialog
          key={editing.template?.id ?? "new-style"}
          open
          onOpenChange={(open) => !open && setEditing(null)}
          initialName={editing.template?.name ?? t("templates.newStyleName")}
          initialDocument={editing.template?.document ?? NEW_STYLE}
          pending={createStyle.isPending || updateStyle.isPending}
          error={createStyle.error ?? updateStyle.error}
          onSubmit={(name, document) => {
            const existing = editing.template;
            const done = { onSuccess: () => setEditing(null) };
            if (existing) updateStyle.mutate({ id: existing.id, name, document }, done);
            else createStyle.mutate({ name, document }, done);
          }}
        />
      )}
      {editing?.kind === "layout" && (
        <LayoutEditorDialog
          key={editing.template?.id ?? "new-layout"}
          open
          onOpenChange={(open) => !open && setEditing(null)}
          initialName={editing.template?.name ?? t("templates.newLayoutName")}
          initialDocument={editing.template?.document ?? NEW_LAYOUT}
          pending={createLayout.isPending || updateLayout.isPending}
          error={createLayout.error ?? updateLayout.error}
          onSubmit={(name, document) => {
            const existing = editing.template;
            const done = { onSuccess: () => setEditing(null) };
            if (existing) updateLayout.mutate({ id: existing.id, name, document }, done);
            else createLayout.mutate({ name, document }, done);
          }}
        />
      )}
      {pushing && (
        <PushUpdateDialog
          kind={pushing.kind}
          templateId={pushing.id}
          templateName={pushing.name}
          revision={pushing.revision}
          open
          onOpenChange={(open) => !open && setPushing(null)}
        />
      )}
    </div>
  );
}
