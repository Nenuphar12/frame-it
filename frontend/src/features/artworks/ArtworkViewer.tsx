import * as RadixDialog from "@radix-ui/react-dialog";
import {
  Cast,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Heart,
  Layers,
  Pencil,
  Plus,
  Sparkles,
  Tag as TagIcon,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { artworkRenderUrl, artworkThumbUrl } from "@/api/client";
import {
  useArtwork,
  useArtworkActions,
  useCollections,
  useFrameStyles,
  useLayouts,
} from "@/api/queries";
import { useRegisterCommands, type Command } from "@/app/commands";
import { AddToCollectionMenu } from "@/features/collections/AddToCollectionMenu";
import { ShowOnTvDialog } from "@/features/display/ShowOnTvDialog";
import { TagPicker } from "@/features/tags/TagPicker";
import { Badge, Kbd, Spinner } from "@/shared/ui/Misc";
import { Button } from "@/shared/ui/Button";

import { ArtworkBadges } from "./ArtworkBadges";

interface ArtworkViewerProps {
  artworkId: string;
  ids: string[];
  onNavigate: (id: string) => void;
  /** Open the artwork in the editor (Phase 5). */
  onEdit: (id: string) => void;
  onClose: () => void;
}

/** Full-screen review of the server render (authoritative pixels) with the Phase 4 actions. */
export function ArtworkViewer({ artworkId, ids, onNavigate, onEdit, onClose }: ArtworkViewerProps) {
  const { t } = useTranslation();
  const artwork = useArtwork(artworkId);
  const styles = useFrameStyles();
  const layouts = useLayouts();
  const collections = useCollections();
  const [collectionMenuOpen, setCollectionMenuOpen] = useState(false);
  const [editingTags, setEditingTags] = useState(false);
  const [showingOnTv, setShowingOnTv] = useState(false);
  const { update, validate, duplicate, trash } = useArtworkActions();
  const [confirmTrash, setConfirmTrash] = useState<string | null>(null);
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const data = artwork.data;
  const index = ids.indexOf(artworkId);

  const go = (delta: number) => {
    const next = ids[index + delta];
    if (next) onNavigate(next);
  };
  const actions = useMemo(
    () => ({
      favorite: () => data && update.mutate({ id: data.id, favorite: !data.favorite }),
      toggleReady: () => {
        if (!data) return;
        if (data.status === "ready") update.mutate({ id: data.id, status: "draft" });
        else validate.mutate(data.id);
      },
      duplicate: () =>
        data && duplicate.mutate(data.id, { onSuccess: (copy) => onNavigate(copy.id) }),
      trash: () => {
        if (!data) return;
        if (confirmTrash !== data.id) {
          setConfirmTrash(data.id);
          return;
        }
        const next = ids[index + 1] ?? ids[index - 1];
        trash.mutate(data.id, { onSuccess: () => (next ? onNavigate(next) : onClose()) });
      },
    }),
    [confirmTrash, data, duplicate, ids, index, onClose, onNavigate, trash, update, validate],
  );

  const commands = useMemo<Command[]>(
    () => [
      {
        id: "artwork.next",
        label: "artworks.next",
        group: "commands.groups.artworks",
        shortcut: "ArrowRight",
        run: () => go(1),
      },
      {
        id: "artwork.previous",
        label: "artworks.previous",
        group: "commands.groups.artworks",
        shortcut: "ArrowLeft",
        run: () => go(-1),
      },
      {
        id: "artwork.favorite",
        label: "artworks.toggleFavorite",
        group: "commands.groups.artworks",
        shortcut: "f",
        run: actions.favorite,
      },
      {
        id: "artwork.ready",
        label: "artworks.toggleReady",
        group: "commands.groups.artworks",
        shortcut: "Enter",
        run: actions.toggleReady,
      },
      {
        id: "artwork.edit",
        label: "editor.open",
        group: "commands.groups.artworks",
        shortcut: "e",
        run: () => data && onEdit(data.id),
      },
      {
        id: "artwork.duplicate",
        label: "artworks.duplicate",
        group: "commands.groups.artworks",
        shortcut: "Shift+D",
        run: actions.duplicate,
      },
      {
        id: "artwork.trash",
        label: "artworks.trash",
        group: "commands.groups.artworks",
        shortcut: "Delete",
        run: actions.trash,
      },
      {
        id: "artwork.addToCollection",
        label: "collections.addTo",
        group: "commands.groups.artworks",
        shortcut: "c",
        run: () => setCollectionMenuOpen(true),
      },
      {
        id: "artwork.showOnTv",
        label: "display.showOnTv",
        group: "commands.groups.artworks",
        run: () => setShowingOnTv(true),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `go` only depends on ids/index
    [actions, data, ids, index, onEdit],
  );
  // The TV dialog is a modal of its own: the viewer's keys (Enter, Delete...) stand down meanwhile.
  useRegisterCommands(showingOnTv ? [] : commands);

  const styleName = styles.data?.find((s) => s.id === data?.origin_style_id)?.name;
  const layoutName = layouts.data?.find((l) => l.id === data?.origin_layout_id)?.name;
  /** Where this artwork lives. Manual membership is a row it can leave; smart membership is a
   *  filter that happens to match it, so it is shown but never offered for removal. */
  const memberOf = data?.collection_ids ?? [];
  const matchedBy = data?.smart_collection_ids ?? [];
  const artworkTags = data?.tags ?? [];
  const all = collections.data ?? [];
  const inCollections = all.filter((c) => memberOf.includes(c.id));
  const inSmart = all.filter((c) => matchedBy.includes(c.id));
  const full = data ? artworkRenderUrl(data, "jpg") : null;

  return (
    <RadixDialog.Root open onOpenChange={(open) => !open && onClose()}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/90" />
        <RadixDialog.Content
          // `Escape` only closes the viewer (see `shared/ui/Dialog`).
          onEscapeKeyDown={(event) => event.stopPropagation()}
          className="fixed inset-0 z-50 flex flex-col outline-none"
        >
          <RadixDialog.Title className="sr-only">
            {data?.title || t("artworks.untitled")}
          </RadixDialog.Title>
          <RadixDialog.Description className="sr-only">
            {t("artworks.viewerHint")}
          </RadixDialog.Description>
          <div className="relative flex min-h-0 flex-1 items-center justify-center p-4">
            {data && full ? (
              <>
                <img
                  key={`thumb-${data.id}`}
                  src={artworkThumbUrl(data, 768)}
                  alt=""
                  className="absolute max-h-[calc(100%-2rem)] max-w-[calc(100%-2rem)] object-contain"
                  style={{
                    aspectRatio: "16 / 9",
                    width: "100%",
                    visibility: loadedSrc === full ? "hidden" : "visible",
                  }}
                />
                <img
                  key={full}
                  src={full}
                  alt={data.title}
                  onLoad={() => setLoadedSrc(full)}
                  className="relative max-h-full max-w-full object-contain"
                  style={{ aspectRatio: "16 / 9", width: "100%" }}
                />
                {loadedSrc !== full && (
                  <div className="absolute top-6 right-6">
                    <Spinner size={18} />
                  </div>
                )}
              </>
            ) : (
              <Spinner size={24} />
            )}
            <button
              type="button"
              className="absolute top-1/2 left-2 -translate-y-1/2 rounded-full p-2 text-white/70 hover:bg-white/10 disabled:opacity-20"
              onClick={() => go(-1)}
              disabled={index <= 0}
              aria-label={t("artworks.previous")}
            >
              <ChevronLeft size={28} />
            </button>
            <button
              type="button"
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded-full p-2 text-white/70 hover:bg-white/10 disabled:opacity-20"
              onClick={() => go(1)}
              disabled={index < 0 || index >= ids.length - 1}
              aria-label={t("artworks.next")}
            >
              <ChevronRight size={28} />
            </button>
          </div>
          {data && (
            <div className="flex flex-col gap-2 border-t border-white/10 bg-panel px-4 py-2.5">
              {/* Row 1: what it is, and what you can do to it. Row 2: where it is filed. */}
              <div className="flex flex-wrap items-center gap-2">
                <div className="mr-auto flex min-w-0 flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-medium">
                    {data.title || t("artworks.untitled")}
                  </span>
                  <ArtworkBadges artwork={data} />
                  <span className="text-xs text-muted">
                    {[styleName, layoutName].filter(Boolean).join(" · ")}
                    {data.min_scale !== null &&
                      ` · ${t("artworks.scale", {
                        min: Math.round(data.min_scale * 100),
                        max: Math.round((data.max_scale ?? data.min_scale) * 100),
                      })}`}
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={actions.favorite}
                  aria-pressed={data.favorite}
                >
                  <Heart size={14} fill={data.favorite ? "currentColor" : "none"} />{" "}
                  {t("artworks.favorite")} <Kbd>F</Kbd>
                </Button>
                <Button
                  size="sm"
                  variant={data.status === "ready" ? "ghost" : "primary"}
                  onClick={actions.toggleReady}
                >
                  {data.status === "ready" ? <Undo2 size={14} /> : <CheckCircle2 size={14} />}
                  {data.status === "ready"
                    ? t("artworks.backToDraft")
                    : t("artworks.markReady")}{" "}
                  <Kbd>↵</Kbd>
                </Button>
                <Button size="sm" variant="secondary" onClick={() => onEdit(data.id)}>
                  <Pencil size={14} /> {t("editor.open")} <Kbd>E</Kbd>
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setShowingOnTv(true)}>
                  <Cast size={14} /> {t("display.showOnTv")}
                </Button>
                <Button size="sm" variant="ghost" onClick={actions.duplicate}>
                  <Copy size={14} /> {t("artworks.duplicate")}
                </Button>
                <Button size="sm" variant="ghost" asChild>
                  <a href={artworkRenderUrl(data, "png")} download>
                    <Download size={14} /> PNG
                  </a>
                </Button>
                <Button size="sm" variant="ghost" asChild>
                  <a href={artworkRenderUrl(data, "jpg")} download>
                    <Download size={14} /> JPEG
                  </a>
                </Button>
                <Button size="sm" variant="danger" onClick={actions.trash}>
                  <Trash2 size={14} />{" "}
                  {confirmTrash === data.id ? t("artworks.confirmTrash") : t("artworks.trash")}
                </Button>
                <RadixDialog.Close
                  className="rounded p-1.5 text-muted hover:bg-panel-2 hover:text-text"
                  aria-label={t("common.close")}
                >
                  <X size={16} />
                </RadixDialog.Close>
              </div>
              {/* Its own row under the actions: where the artwork is filed and how it is labelled,
                  both editable here (remarks.md #3, #5). Sharing the actions' row pushed the
                  buttons onto a third line, left-aligned and cramped. */}
              <div className="flex flex-wrap items-center gap-1.5 border-t border-border pt-2 text-xs">
                <Layers size={13} className="text-muted" />
                {inCollections.length + inSmart.length === 0 ? (
                  <span className="text-muted">{t("collections.none")}</span>
                ) : (
                  <>
                    {inCollections.map((collection) => (
                      <Badge key={collection.id} tone="neutral">
                        {collection.name}
                      </Badge>
                    ))}
                    {inSmart.map((collection) => (
                      <Badge key={collection.id} tone="accent" title={t("collections.smartMember")}>
                        <Sparkles size={10} />
                        {collection.name}
                      </Badge>
                    ))}
                  </>
                )}
                <AddToCollectionMenu
                  artworkIds={[data.id]}
                  memberOf={memberOf}
                  open={collectionMenuOpen}
                  onOpenChange={setCollectionMenuOpen}
                  trigger={
                    <button
                      type="button"
                      aria-label={t("collections.addTo")}
                      className="rounded px-1 text-muted hover:bg-panel-2 hover:text-text"
                    >
                      <Plus size={13} />
                    </button>
                  }
                />
                <span className="mx-1 h-3 w-px bg-border" />
                <TagIcon size={13} className="text-muted" />
                {editingTags ? (
                  <span className="min-w-56 flex-1">
                    <TagPicker
                      value={artworkTags}
                      onChange={(tags) =>
                        update.mutate({ id: data.id, tag_ids: tags.map((tag) => tag.id) })
                      }
                    />
                  </span>
                ) : (
                  <>
                    {artworkTags.length === 0 ? (
                      <span className="text-muted">{t("tags.none")}</span>
                    ) : (
                      artworkTags.map((tag) => (
                        <Badge key={tag.id} tone="neutral">
                          {tag.name}
                        </Badge>
                      ))
                    )}
                    <button
                      type="button"
                      onClick={() => setEditingTags(true)}
                      aria-label={t("tags.edit")}
                      className="rounded px-1 text-muted hover:bg-panel-2 hover:text-text"
                    >
                      <Plus size={13} />
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
          {/* One artwork: the dialog starts at "Don't change" (it stays on screen, and nothing
              else on the TV is touched, docs/tv-display.md). */}
          {data && (
            <ShowOnTvDialog
              open={showingOnTv}
              onOpenChange={setShowingOnTv}
              label={data.title || t("artworks.untitled")}
              source={{ artwork_ids: [data.id] }}
            />
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
