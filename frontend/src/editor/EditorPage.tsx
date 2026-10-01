// The editor: canvas in the middle, properties on the right, review queue at the bottom.
//
// Everything the user changes goes through `editor/actions` → `editor/store` (undo/redo +
// autosave). The document shown here is the working copy; the authoritative pixels are the server
// render, reachable at any time through the loupe (`Z`) and the TV preview (`P`).
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import {
  Check,
  Crop,
  Heart,
  Loader2,
  Maximize2,
  MousePointer2,
  Redo2,
  SkipForward,
  Undo2,
  ZoomIn,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { artworkThumbUrl } from "@/api/client";
import {
  useArtwork,
  useArtworkActions,
  useArtworks,
  useFrameStyles,
  useLayouts,
  usePhotosByIds,
  useRecipes,
  type TemplateKind,
} from "@/api/queries";
import { useRegisterCommands, type Command } from "@/app/commands";
import { cn } from "@/shared/cn";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Kbd, Spinner } from "@/shared/ui/Misc";
import { problemMessage } from "@/shared/problem";
import { ShowOnTvDialog } from "@/features/display/ShowOnTvDialog";
import { EditorStage } from "./canvas/EditorStage";
import * as actions from "./actions";
import type { Side } from "./core/snapping.ts";
import { AlternativesPanel } from "./panels/AlternativesPanel";
import { ArrangePanel } from "./panels/ArrangePanel";
import { CaptionsPanel } from "./panels/CaptionsPanel";
import { FramingPanel } from "./panels/FramingPanel";
import { InfoSheet } from "./panels/InfoSheet";
import { Loupe } from "./panels/Loupe";
import { DocumentQualityBadge } from "./panels/QualityBadge";
import { SaveAsTemplateDialog } from "./panels/SaveAsTemplateDialog";
import { SimplePanel } from "./panels/SimplePanel";
import { SlotsPanel } from "./panels/SlotsPanel";
import { PhotoPicker } from "./panels/PhotoPicker";
import { StylePanel } from "./panels/StylePanel";
import {
  canRedo,
  canUndo,
  closeEditor,
  openArtwork,
  redo,
  replaceDocument,
  resolveConflict,
  save,
  setRecipes,
  select,
  selectCaption,
  selectMany,
  selectedCaption,
  selectedSlot,
  setTool,
  undo,
  useEditor,
} from "./store";
import { TvPreview } from "./TvPreview";

type Tab = "design" | "artwork";
type Mode = "simple" | "advanced";

export function EditorPage() {
  const { t } = useTranslation();
  const { artworkId } = useParams({ from: "/shell/editor/$artworkId" });
  const search = useSearch({ from: "/shell/editor/$artworkId" });
  const navigate = useNavigate();
  const artwork = useArtwork(artworkId);
  const { validate, update } = useArtworkActions();
  const recipes = useRecipes();
  const styles = useFrameStyles();
  const layouts = useLayouts();
  const [savingTemplate, setSavingTemplate] = useState<TemplateKind | null>(null);
  /** "Show on the TV" for the artwork being edited (one artwork: "Don't change" by default). */
  const [showingOnTv, setShowingOnTv] = useState(false);

  const photoIds = useMemo(
    () => [
      ...new Set(
        (artwork.data?.document.slots ?? []).flatMap((s) => (s.photo_id ? [s.photo_id] : [])),
      ),
    ],
    [artwork.data],
  );
  const { photos } = usePhotosByIds(photoIds);
  // Keyed on the values, not on the query result: `photos` is a new array on every render.
  const sizesKey = photos.map((p) => `${p.id}:${p.width}x${p.height}`).join(",");
  const sizes = useMemo(
    () =>
      Object.fromEntries(
        sizesKey
          .split(",")
          .filter(Boolean)
          .map((entry) => {
            const [id, size] = entry.split(":");
            const [w, h] = (size ?? "0x0").split("x");
            return [id ?? "", { w: Number(w), h: Number(h) }];
          }),
      ),
    [sizesKey],
  );

  const doc = useEditor((state) => state.doc);
  const catalogue = useEditor((state) => state.recipes);
  const slot = useEditor(selectedSlot);
  const storeSizes = useEditor((state) => state.sizes);
  const selectedSlotIds = useEditor((state) => state.selectedSlotIds);
  const selectedCaptionId = useEditor((state) => state.selectedCaptionId);
  const caption = useEditor(selectedCaption);
  const tool = useEditor((state) => state.tool);
  const saveState = useEditor((state) => state.saveState);
  const saveError = useEditor((state) => state.saveError);
  const conflict = useEditor((state) => state.conflict);
  const openedSnapshotId = useEditor((state) => state.openedSnapshotId);
  const undoable = useEditor(canUndo);
  const redoable = useEditor(canRedo);

  const [tab, setTab] = useState<Tab>("design");
  // Simple is the default for every artwork (§6.1); Advanced is today's panel stack, in beta.
  const [mode, setMode] = useState<Mode>("simple");
  const [loupe, setLoupe] = useState(false);
  const [tv, setTv] = useState(false);
  const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null);
  const [guides, setGuides] = useState<{ x?: number | null; y?: number | null }>({});
  const [stageScale, setStageScale] = useState(0.25);
  const [picking, setPicking] = useState(false);

  // ---- queue (review flow) ---------------------------------------------------------------------
  const queueFilter = useMemo(() => ({ status: "draft" as const }), []);
  const drafts = useArtworks(queueFilter);
  const queue = useMemo(() => {
    if (search.queue) return search.queue.split(",").filter(Boolean);
    return (drafts.data?.pages ?? []).flatMap((page) => page.items.map((item) => item.id));
  }, [search.queue, drafts.data]);
  const queueItems = useMemo(
    () => (drafts.data?.pages ?? []).flatMap((page) => page.items),
    [drafts.data],
  );
  const index = queue.indexOf(artworkId);

  const goTo = useCallback(
    (id: string) => {
      void save();
      void navigate({
        to: "/editor/$artworkId",
        params: { artworkId: id },
        search: search.queue ? { queue: search.queue } : {},
      });
    },
    [navigate, search.queue],
  );

  const step = useCallback(
    (delta: number) => {
      const next = queue[index + delta];
      if (next) goTo(next);
    },
    [queue, index, goTo],
  );

  /** The heart is an artwork property, not a document one: it never touches the working copy. */
  const toggleFavorite = useCallback(() => {
    const current = artwork.data;
    if (current) update.mutate({ id: current.id, favorite: !current.favorite });
  }, [artwork.data, update]);

  const validateAndNext = useCallback(() => {
    const current = artwork.data;
    if (!current) return;
    void save().then(() =>
      validate.mutate(current.id, {
        onSuccess: () => {
          const next = queue[index + 1];
          if (next) goTo(next);
        },
      }),
    );
  }, [artwork.data, goTo, index, queue, validate]);

  // ---- lifecycle -------------------------------------------------------------------------------
  useEffect(() => {
    if (artwork.data && photoIds.every((id) => sizes[id])) openArtwork(artwork.data, sizes);
  }, [artwork.data, photoIds, sizes]);

  // The catalogue is what the composition operations solve with (`editor/operations`).
  useEffect(() => {
    if (recipes.data) setRecipes(recipes.data);
  }, [recipes.data]);

  useEffect(
    () => () => {
      void save();
      closeEditor();
    },
    [],
  );

  // ---- shortcuts (§11.5) -----------------------------------------------------------------------
  const commands = useMemo<Command[]>(() => {
    const group = "commands.groups.editor";
    const nudge = (dx: number, dy: number) => () => actions.nudge(dx, dy);
    return [
      { id: "editor.undo", label: "editor.commands.undo", group, shortcut: "$mod+z", run: undo },
      {
        id: "editor.redo",
        label: "editor.commands.redo",
        group,
        shortcut: "$mod+Shift+z",
        run: redo,
      },
      {
        id: "editor.tool.select",
        label: "editor.commands.select",
        group,
        shortcut: "v",
        run: () => setTool("select"),
      },
      {
        id: "editor.tool.crop",
        label: "editor.commands.crop",
        group,
        shortcut: "c",
        run: () => setTool("crop"),
      },
      {
        id: "editor.lock.native",
        label: "editor.commands.lockNative",
        group,
        shortcut: "1",
        run: () => actions.setLock("native"),
      },
      {
        id: "editor.lock.noUpscale",
        label: "editor.commands.lockNoUpscale",
        group,
        shortcut: "2",
        run: () => actions.setLock("no_upscale"),
      },
      {
        id: "editor.lock.free",
        label: "editor.commands.lockFree",
        group,
        shortcut: "3",
        run: () => actions.setLock("free"),
      },
      {
        id: "editor.rotate",
        label: "editor.commands.rotate",
        group,
        shortcut: "r",
        run: () => actions.rotateSource(1),
      },
      {
        id: "editor.rotateLeft",
        label: "editor.commands.rotateLeft",
        group,
        shortcut: "Shift+R",
        run: () => actions.rotateSource(-1),
      },
      {
        id: "editor.flip",
        label: "editor.commands.flip",
        group,
        shortcut: "h",
        run: actions.flipSource,
      },
      {
        id: "editor.zoomIn",
        label: "editor.commands.zoomIn",
        group,
        shortcut: "+",
        run: () => actions.zoomCrop(1 / 1.08),
      },
      {
        id: "editor.zoomOut",
        label: "editor.commands.zoomOut",
        group,
        shortcut: "-",
        run: () => actions.zoomCrop(1.08),
      },
      {
        id: "editor.mode",
        label: "editor.commands.toggleMode",
        group,
        run: () => setMode((value) => (value === "simple" ? "advanced" : "simple")),
      },
      {
        id: "editor.loupe",
        label: "editor.commands.loupe",
        group,
        shortcut: "z",
        run: () => setLoupe((value) => !value),
      },
      {
        id: "editor.tv",
        label: "editor.commands.tvPreview",
        group,
        shortcut: "p",
        run: () => setTv((value) => !value),
      },
      {
        id: "editor.validate",
        label: "editor.commands.validate",
        group,
        shortcut: "Enter",
        run: validateAndNext,
      },
      {
        id: "editor.favorite",
        label: "artworks.toggleFavorite",
        group,
        shortcut: "f",
        run: () => toggleFavorite(),
      },
      {
        id: "editor.skip",
        label: "editor.commands.skip",
        group,
        shortcut: "s",
        run: () => step(1),
      },
      {
        id: "editor.next",
        label: "editor.commands.next",
        group,
        shortcut: "j",
        run: () => step(1),
      },
      {
        id: "editor.previous",
        label: "editor.commands.previous",
        group,
        shortcut: "k",
        run: () => step(-1),
      },
      {
        id: "editor.close",
        label: "editor.commands.close",
        group,
        shortcut: "Escape",
        run: () => void navigate({ to: "/artworks" }),
      },
      {
        id: "editor.addSlot",
        label: "editor.commands.addSlot",
        group,
        shortcut: "a",
        run: () => setPicking(true),
      },
      {
        id: "editor.deleteSelection",
        label: "editor.commands.deleteSelection",
        group,
        shortcut: "Delete",
        run: () => {
          if (useEditor.getState().selectedCaptionId) actions.removeCaption();
          else actions.removeSelectedSlots();
        },
      },
      {
        id: "editor.bringForward",
        label: "editor.commands.bringForward",
        group,
        shortcut: "]",
        run: () => actions.moveInOrder(1),
      },
      {
        id: "editor.sendBackward",
        label: "editor.commands.sendBackward",
        group,
        shortcut: "[",
        run: () => actions.moveInOrder(-1),
      },
      {
        id: "editor.addCaption",
        label: "editor.commands.addCaption",
        group,
        shortcut: "t",
        run: () => actions.addCaption(t("editor.captions.placeholder")),
      },
      {
        id: "editor.selectAllSlots",
        label: "editor.commands.selectAllSlots",
        group,
        shortcut: "$mod+a",
        run: () => selectMany((useEditor.getState().doc?.slots ?? []).map((item) => item.id)),
      },
      {
        id: "editor.nudgeLeft",
        label: "editor.commands.nudge",
        group,
        shortcut: "ArrowLeft",
        run: nudge(-1, 0),
      },
      {
        id: "editor.nudgeRight",
        label: "editor.commands.nudge",
        group,
        shortcut: "ArrowRight",
        run: nudge(1, 0),
      },
      {
        id: "editor.nudgeUp",
        label: "editor.commands.nudge",
        group,
        shortcut: "ArrowUp",
        run: nudge(0, -1),
      },
      {
        id: "editor.nudgeDown",
        label: "editor.commands.nudge",
        group,
        shortcut: "ArrowDown",
        run: nudge(0, 1),
      },
      {
        id: "editor.nudgeLeft10",
        label: "editor.commands.nudge10",
        group,
        shortcut: "Shift+ArrowLeft",
        run: nudge(-10, 0),
      },
      {
        id: "editor.nudgeRight10",
        label: "editor.commands.nudge10",
        group,
        shortcut: "Shift+ArrowRight",
        run: nudge(10, 0),
      },
      {
        id: "editor.nudgeUp10",
        label: "editor.commands.nudge10",
        group,
        shortcut: "Shift+ArrowUp",
        run: nudge(0, -10),
      },
      {
        id: "editor.nudgeDown10",
        label: "editor.commands.nudge10",
        group,
        shortcut: "Shift+ArrowDown",
        run: nudge(0, 10),
      },
      {
        id: "editor.showOnTv",
        label: "display.showOnTv",
        group,
        run: () => setShowingOnTv(true),
      },
    ];
  }, [navigate, step, t, toggleFavorite, validateAndNext]);
  // While the TV dialog is open its own buttons own the keyboard (Enter would validate otherwise).
  useRegisterCommands(showingOnTv ? [] : commands);

  if (artwork.error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-sm">
        <p className="text-danger">
          {problemMessage(t, artwork.error)}
        </p>
        <Button variant="secondary" onClick={() => void navigate({ to: "/artworks" })}>
          {t("nav.artworks")}
        </Button>
      </div>
    );
  }
  if (artwork.isLoading || !doc || !artwork.data) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={22} />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex min-h-12 flex-wrap items-center gap-2 border-b border-border px-3 py-1.5">
        <span className="truncate text-sm font-medium">
          {artwork.data.title || t("artworks.untitled")}
        </span>
        <DocumentQualityBadge doc={doc} />
        <Button
          size="sm"
          variant="ghost"
          onClick={toggleFavorite}
          aria-label={t("artworks.toggleFavorite")}
          aria-pressed={artwork.data.favorite}
          title={t("artworks.toggleFavorite")}
          className={artwork.data.favorite ? "text-danger" : undefined}
        >
          <Heart size={14} fill={artwork.data.favorite ? "currentColor" : "none"} />
        </Button>
        <div
          className="mx-2 flex rounded-md border border-border p-0.5"
          role="radiogroup"
          aria-label={t("editor.mode.label")}
        >
          {(["simple", "advanced"] as Mode[]).map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={mode === value}
              onClick={() => setMode(value)}
              className={cn(
                "rounded px-2 py-1 text-[11px] text-muted",
                mode === value && "bg-panel-2 text-text",
              )}
            >
              {t(`editor.mode.${value}`)}
              {value === "advanced" && (
                <sup className="ml-0.5 text-[8px]">{t("editor.mode.beta")}</sup>
              )}
            </button>
          ))}
        </div>
        {/* The select/crop tools belong to the free-form editor; Simple always reframes. */}
        {mode === "advanced" && (
          <div className="flex rounded-md border border-border p-0.5">
            <ToolButton
              active={tool === "select"}
              onClick={() => setTool("select")}
              label={t("editor.commands.select")}
            >
              <MousePointer2 size={14} />
            </ToolButton>
            <ToolButton
              active={tool === "crop"}
              onClick={() => setTool("crop")}
              label={t("editor.commands.crop")}
            >
              <Crop size={14} />
            </ToolButton>
          </div>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={undo}
          disabled={!undoable}
          aria-label={t("editor.commands.undo")}
        >
          <Undo2 size={14} />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={redo}
          disabled={!redoable}
          aria-label={t("editor.commands.redo")}
        >
          <Redo2 size={14} />
        </Button>
        <Button size="sm" variant={loupe ? "primary" : "ghost"} onClick={() => setLoupe((v) => !v)}>
          <ZoomIn size={14} /> {t("editor.loupe.title")} <Kbd>Z</Kbd>
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setTv(true)}>
          <Maximize2 size={14} /> {t("editor.tv.title")} <Kbd>P</Kbd>
        </Button>
        <SaveState state={saveState} error={saveError} />
        <div className="ml-auto flex items-center gap-2">
          {index >= 0 && queue.length > 1 && (
            <span className="text-xs text-muted tabular-nums">
              {t("editor.queue.progress", { current: index + 1, total: queue.length })}
            </span>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => step(1)}
            disabled={index < 0 || index >= queue.length - 1}
          >
            <SkipForward size={14} /> {t("editor.queue.skip")} <Kbd>S</Kbd>
          </Button>
          <Button size="sm" variant="primary" onClick={validateAndNext}>
            <Check size={14} />
            {artwork.data.status === "ready"
              ? t("editor.queue.validated")
              : t("artworks.markReady")}
            <Kbd>↵</Kbd>
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          <EditorStage
            doc={doc}
            sizes={storeSizes}
            tool={mode === "simple" ? "crop" : tool}
            selectedSlotIds={selectedSlotIds}
            selectedCaptionId={selectedCaptionId}
            onSelectSlot={select}
            onSelectCaption={selectCaption}
            onPanCrop={actions.panCrop}
            onZoomCrop={actions.zoomCrop}
            onMoveSlots={actions.moveSlots}
            onResizeSlot={actions.resizeSlot}
            onRotateSlot={actions.setRotation}
            onMoveCaption={actions.moveCaption}
            onEditCaption={(id, text) => {
              selectCaption(id);
              actions.updateCaption({ text }, null);
            }}
            onDropPhoto={(photoId, slotId, at) =>
              void (slotId ? actions.setSlotPhoto(slotId, photoId) : actions.addSlot(photoId, at))
            }
            onPointer={setPointer}
            onScaleChange={setStageScale}
            guides={guides}
          />
          {loupe && <Loupe doc={doc} point={pointer} />}
        </div>

        <aside className="flex w-80 shrink-0 flex-col overflow-y-auto border-l border-border bg-panel">
          <div className="flex border-b border-border" role="tablist">
            {(["design", "artwork"] as Tab[]).map((key) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={cn(
                  "flex-1 px-3 py-2 text-xs text-muted",
                  tab === key && "border-b-2 border-accent text-text",
                )}
              >
                {t(`editor.tabs.${key}`)}
              </button>
            ))}
          </div>
          {tab === "design" && mode === "simple" ? (
            <SimplePanel
              doc={doc}
              recipes={catalogue}
              styles={styles.data ?? []}
              layouts={layouts.data ?? []}
              sizes={storeSizes}
              selectedSlotId={slot?.id ?? null}
              onSelectSlot={(slotId) => select(slotId)}
              onSaveAsTemplate={setSavingTemplate}
            />
          ) : tab === "design" ? (
            <>
              <p className="border-b border-border bg-panel-2 px-3 py-2 text-[11px] text-muted">
                {t("editor.mode.betaWarning")}
              </p>
              {slot && <AlternativesPanel doc={doc} slot={slot} sizes={storeSizes} />}
              <SlotsPanel
                doc={doc}
                selectedIds={selectedSlotIds}
                onSelect={(slotId, additive) => select(slotId, additive ? "toggle" : "replace")}
              />
              {selectedSlotIds.length > 1 && (
                <ArrangePanel selectedCount={selectedSlotIds.length} />
              )}
              <FramingPanel
                doc={doc}
                slot={slot}
                sizes={storeSizes}
                stageScale={stageScale}
                onSnap={(side: Side, value) =>
                  setGuides(
                    side === "left" || side === "right"
                      ? { ...guides, x: value === null ? null : value }
                      : { ...guides, y: value === null ? null : value },
                  )
                }
              />
              <StylePanel doc={doc} slot={slot} />
              <CaptionsPanel doc={doc} caption={caption} onSelect={selectCaption} />
            </>
          ) : (
            <InfoSheet artwork={artwork.data} photos={photos} openedSnapshotId={openedSnapshotId} />
          )}
        </aside>
      </div>

      {queueItems.length > 1 && (
        <footer className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-t border-border px-3 py-2">
          {queueItems.slice(0, 40).map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => goTo(item.id)}
              title={item.title}
              className={cn(
                "h-11 w-20 shrink-0 overflow-hidden rounded border",
                item.id === artworkId ? "border-accent" : "border-border opacity-70",
              )}
            >
              <img src={artworkThumbUrl(item, 256)} alt="" className="h-full w-full object-cover" />
            </button>
          ))}
        </footer>
      )}

      <PhotoPicker
        open={picking}
        onOpenChange={setPicking}
        used={photoIds}
        onPickEmpty={() => void actions.addSlot(null)}
        onPick={(photoId) => {
          void actions.addSlot(photoId);
          setPicking(false);
        }}
      />

      <ShowOnTvDialog
        open={showingOnTv}
        onOpenChange={setShowingOnTv}
        label={artwork.data.title || t("artworks.untitled")}
        source={{ artwork_ids: [artwork.data.id] }}
      />

      {savingTemplate && (
        <SaveAsTemplateDialog
          kind={savingTemplate}
          artworkId={artworkId}
          suggestedName={artwork.data?.title || t("templates.newStyleName")}
          onClose={() => setSavingTemplate(null)}
        />
      )}

      {tv && (
        <TvPreview
          artwork={artwork.data}
          ids={queue}
          onNavigate={goTo}
          onClose={() => setTv(false)}
        />
      )}

      <Dialog
        open={conflict !== null}
        onOpenChange={(open) => !open && resolveConflict("mine")}
        title={t("editor.conflict.title")}
        description={t("editor.conflict.description")}
      >
        <div className="flex justify-end gap-2">
          <Button
            variant="secondary"
            onClick={() => {
              if (conflict) replaceDocument(conflict.server);
              resolveConflict("theirs");
            }}
          >
            {t("editor.conflict.takeServer")}
          </Button>
          <Button variant="primary" onClick={() => resolveConflict("mine")}>
            {t("editor.conflict.keepMine")}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

function ToolButton({
  active,
  onClick,
  label,
  children,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={label}
      title={label}
      className={cn("rounded px-2 py-1 text-muted", active && "bg-panel-2 text-text")}
    >
      {children}
    </button>
  );
}

function SaveState({ state, error }: { state: string; error: string | null }) {
  const { t } = useTranslation();
  if (state === "saving") {
    return (
      <span className="flex items-center gap-1 text-xs text-muted">
        <Loader2 size={12} className="animate-spin" /> {t("editor.save.saving")}
      </span>
    );
  }
  if (state === "error") {
    return (
      <span className="text-xs text-danger">
        {error
          ? t(`errors.${error}`, { defaultValue: t("editor.save.error") })
          : t("editor.save.error")}
      </span>
    );
  }
  if (state === "dirty")
    return <span className="text-xs text-muted">{t("editor.save.pending")}</span>;
  if (state === "saved")
    return <span className="text-xs text-muted">{t("editor.save.saved")}</span>;
  return null;
}
