import { ChevronDown, ChevronRight, Folder, FolderOpen, Sparkles } from "lucide-react";
import { useMemo, useState, type DragEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Collection } from "@/api/client";
import { cn } from "@/shared/cn";
import { ARTWORK_MIME, COLLECTION_MIME, startInternalDrag } from "@/shared/dnd";

import { buildTree, type TreeNode } from "./tree";


interface CollectionTreeProps {
  rows: Collection[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Re-parent (drop *on* a row) or reorder (drop *between* rows) — the server refuses cycles. */
  onMove?: (id: string, parentId: string | null, beforeId: string | null) => void;
  /** Artworks dropped on a manual collection are added to it. */
  onDropArtworks?: (collectionId: string, artworkIds: string[]) => void;
}

export function CollectionTree({
  rows,
  selectedId,
  onSelect,
  onMove,
  onDropArtworks,
}: CollectionTreeProps) {
  const tree = useMemo(() => buildTree(rows), [rows]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  const toggle = (id: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div>
      <ul className="space-y-0.5">
        <TreeLevel
          nodes={tree}
          depth={0}
          collapsed={collapsed}
          toggle={toggle}
          selectedId={selectedId}
          onSelect={onSelect}
          onMove={onMove}
          onDropArtworks={onDropArtworks}
          dropTarget={dropTarget}
          setDropTarget={setDropTarget}
        />
      </ul>
      {onMove && <RootDropZone onMove={onMove} />}
    </div>
  );
}

/**
 * Dropping a collection here re-parents it to the **top level**. Without it a sub-collection has
 * nowhere to go: every other target in the tree is another parent (remarks.md #4).
 */
function RootDropZone({ onMove }: { onMove: NonNullable<CollectionTreeProps["onMove"]> }) {
  const { t } = useTranslation();
  const [over, setOver] = useState(false);
  return (
    <div
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes(COLLECTION_MIME)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        const moved = event.dataTransfer.getData(COLLECTION_MIME);
        if (moved) onMove(moved, null, null);
      }}
      className={cn(
        "mt-1 rounded-md border border-dashed px-2 py-1.5 text-[11px] transition",
        over ? "border-accent bg-accent/10 text-accent" : "border-border/60 text-muted/70",
      )}
    >
      {t("collections.dropToTopLevel")}
    </div>
  );
}

interface LevelProps extends Required<Pick<CollectionTreeProps, "rows">> {
  nodes: TreeNode[];
  depth: number;
  collapsed: Set<string>;
  toggle: (id: string) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onMove?: CollectionTreeProps["onMove"];
  onDropArtworks?: CollectionTreeProps["onDropArtworks"];
  dropTarget: string | null;
  setDropTarget: (id: string | null) => void;
}

function TreeLevel({
  nodes,
  depth,
  collapsed,
  toggle,
  selectedId,
  onSelect,
  onMove,
  onDropArtworks,
  dropTarget,
  setDropTarget,
}: Omit<LevelProps, "rows">) {
  const { t } = useTranslation();

  const onDragOver = (event: DragEvent, node: TreeNode) => {
    const { types } = event.dataTransfer;
    const artworks = types.includes(ARTWORK_MIME) && node.collection.kind === "manual";
    const collections = types.includes(COLLECTION_MIME) && onMove !== undefined;
    if (!artworks && !collections) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "move";
    setDropTarget(node.collection.id);
  };

  const onDrop = (event: DragEvent, node: TreeNode) => {
    event.preventDefault();
    event.stopPropagation();
    setDropTarget(null);
    const artworkIds = event.dataTransfer.getData(ARTWORK_MIME);
    if (artworkIds && node.collection.kind === "manual") {
      onDropArtworks?.(node.collection.id, artworkIds.split(",").filter(Boolean));
      return;
    }
    const moved = event.dataTransfer.getData(COLLECTION_MIME);
    // Dropping a collection on one of its own descendants is refused by the server
    // (`collection_cycle`); the tree does not try to guess, it just never offers itself.
    if (moved && moved !== node.collection.id) onMove?.(moved, node.collection.id, null);
  };

  return (
    <>
      {nodes.map((node) => {
        const { collection } = node;
        const isOpen = !collapsed.has(collection.id);
        const isSmart = collection.kind === "smart";
        return (
          <li key={collection.id}>
            <div
              draggable={onMove !== undefined}
              onDragStart={(event) => {
                event.stopPropagation();
                startInternalDrag(event.dataTransfer, COLLECTION_MIME, collection.id);
              }}
              onDragOver={(event) => onDragOver(event, node)}
              onDragLeave={() => setDropTarget(null)}
              onDrop={(event) => onDrop(event, node)}
              style={{ paddingLeft: `${depth * 0.9 + 0.25}rem` }}
              className={cn(
                "flex items-center gap-1 rounded-md py-1 pr-1.5 text-sm",
                selectedId === collection.id ? "bg-panel-2 text-text" : "text-muted",
                dropTarget === collection.id && "ring-1 ring-accent",
              )}
            >
              <button
                type="button"
                onClick={() => toggle(collection.id)}
                aria-label={t(isOpen ? "collections.collapse" : "collections.expand")}
                className={cn("shrink-0 rounded p-0.5", node.children.length === 0 && "invisible")}
              >
                {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              </button>
              <button
                type="button"
                onClick={() => onSelect(collection.id)}
                className="flex min-w-0 flex-1 items-center gap-1.5 text-left hover:text-text"
              >
                {isSmart ? (
                  <Sparkles size={14} className="shrink-0 text-accent" />
                ) : isOpen && node.children.length > 0 ? (
                  <FolderOpen size={14} className="shrink-0" />
                ) : (
                  <Folder size={14} className="shrink-0" />
                )}
                <span className="truncate">{collection.name}</span>
                <span className="ml-auto pl-1 text-[11px] text-muted tabular-nums">
                  {collection.nested_count > collection.item_count
                    ? `${collection.item_count} / ${collection.nested_count}`
                    : collection.item_count || ""}
                </span>
              </button>
            </div>
            {isOpen && node.children.length > 0 && (
              <ul className="space-y-0.5">
                <TreeLevel
                  nodes={node.children}
                  depth={depth + 1}
                  collapsed={collapsed}
                  toggle={toggle}
                  selectedId={selectedId}
                  onSelect={onSelect}
                  onMove={onMove}
                  onDropArtworks={onDropArtworks}
                  dropTarget={dropTarget}
                  setDropTarget={setDropTarget}
                />
              </ul>
            )}
          </li>
        );
      })}
    </>
  );
}
