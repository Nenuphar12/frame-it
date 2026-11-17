import { ChevronDown, ChevronRight, Folder, FolderOpen, Plus, Sparkles } from "lucide-react";
import { useMemo, useState, type DragEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Collection } from "@/api/client";
import { cn } from "@/shared/cn";
import { ARTWORK_MIME, COLLECTION_MIME, startInternalDrag } from "@/shared/dnd";

import { buildTree, dropWhere, moveFor, type DropWhere, type TreeNode } from "./tree";

/**
 * The collection being dragged. `getData` is unreadable during `dragover` (the browser only
 * releases it on drop), and a drop target must know *what* comes to say where it may land — the
 * sidebar's tree and the page's are two instances, so it lives here rather than in either.
 */
let dragged: string | null = null;

interface DropSpot {
  id: string;
  where: DropWhere;
}

interface CollectionTreeProps {
  rows: Collection[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /**
   * Drag to reorder (drop above or below a row) or to re-parent (drop *into* a manual row's middle).
   * `beforeId` is the sibling it lands in front of, `null` for last.
   */
  onMove?: (id: string, parentId: string | null, beforeId: string | null) => void;
  /** Artworks dropped on a manual collection are added to it. */
  onDropArtworks?: (collectionId: string, artworkIds: string[]) => void;
  /** The "+" on a manual row: start a new collection inside it. */
  onCreateChild?: (parentId: string) => void;
  /**
   * Sub-collections start folded (the sidebar, where the tree must stay short); otherwise every
   * level starts unfolded. Either way a click on a chevron flips that row for as long as the tree
   * stays mounted.
   */
  defaultCollapsed?: boolean;
}

export function CollectionTree({
  rows,
  selectedId,
  onSelect,
  onMove,
  onDropArtworks,
  onCreateChild,
  defaultCollapsed = false,
}: CollectionTreeProps) {
  const tree = useMemo(() => buildTree(rows), [rows]);
  // The rows flipped away from the default: a collection created later follows the default.
  const [flipped, setFlipped] = useState<Set<string>>(new Set());
  const [dropTarget, setDropTarget] = useState<DropSpot | null>(null);
  // Only while a collection is dragged from this tree: the top-level zone is noise otherwise.
  const [dragging, setDragging] = useState(false);

  const isOpen = (id: string) => flipped.has(id) === defaultCollapsed;
  const toggle = (id: string) =>
    setFlipped((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div>
      <ul className="space-y-0.5">
        <TreeLevel
          rows={rows}
          nodes={tree}
          depth={0}
          isOpen={isOpen}
          toggle={toggle}
          selectedId={selectedId}
          onSelect={onSelect}
          onMove={onMove}
          onDropArtworks={onDropArtworks}
          onCreateChild={onCreateChild}
          dropTarget={dropTarget}
          setDropTarget={setDropTarget}
          setDragging={setDragging}
        />
      </ul>
      {onMove && dragging && <RootDropZone onMove={onMove} />}
    </div>
  );
}

/**
 * Dropping a collection here makes it the **last** of the top level — the one place no row offers
 * when the last top-level collection is open (below it is its first child). Shown during a drag.
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
        if (moved) onMove(moved, null, null); // last of the top level
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
  isOpen: (id: string) => boolean;
  toggle: (id: string) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onMove?: CollectionTreeProps["onMove"];
  onDropArtworks?: CollectionTreeProps["onDropArtworks"];
  onCreateChild?: CollectionTreeProps["onCreateChild"];
  dropTarget: DropSpot | null;
  setDropTarget: (spot: DropSpot | null) => void;
  setDragging: (dragging: boolean) => void;
}

function TreeLevel({
  rows,
  nodes,
  depth,
  isOpen,
  toggle,
  selectedId,
  onSelect,
  onMove,
  onDropArtworks,
  onCreateChild,
  dropTarget,
  setDropTarget,
  setDragging,
}: LevelProps) {
  const { t } = useTranslation();

  /** Where a collection dragged over `node` would land, and the move that is — or nothing. */
  const spotFor = (event: DragEvent, node: TreeNode) => {
    if (dragged === null) return null;
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientY - box.top) / Math.max(1, box.height);
    const where = dropWhere(ratio, node.collection.kind === "manual");
    const move = moveFor(rows, dragged, node.collection.id, where, isOpen(node.collection.id));
    return move ? { where, move } : null;
  };

  const onDragOver = (event: DragEvent, node: TreeNode) => {
    const { types } = event.dataTransfer;
    if (types.includes(ARTWORK_MIME)) {
      if (node.collection.kind !== "manual") return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "move"; // what the grid's drag allows
      setDropTarget({ id: node.collection.id, where: "inside" });
      return;
    }
    if (!types.includes(COLLECTION_MIME) || onMove === undefined) return;
    event.stopPropagation();
    // Onto itself, into its own subtree, or a place it already has: no drop is offered at all.
    const spot = spotFor(event, node);
    if (!spot) {
      setDropTarget(null);
      return;
    }
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    if (dropTarget?.id !== node.collection.id || dropTarget.where !== spot.where) {
      setDropTarget({ id: node.collection.id, where: spot.where });
    }
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
    const spot = spotFor(event, node);
    if (dragged && spot) onMove?.(dragged, spot.move.parentId, spot.move.beforeId);
  };

  return (
    <>
      {nodes.map((node) => {
        const { collection } = node;
        const open = isOpen(collection.id);
        const isSmart = collection.kind === "smart";
        const spot = dropTarget?.id === collection.id ? dropTarget.where : null;
        // The line sits where the collection will land: "after" an open parent is its first
        // child, so the line is indented one level there.
        const lineDepth =
          spot === "after" && open && !isSmart && node.children.length > 0 ? depth + 1 : depth;
        return (
          <li key={collection.id}>
            <div
              draggable={onMove !== undefined}
              onDragStart={(event) => {
                event.stopPropagation();
                dragged = collection.id;
                startInternalDrag(event.dataTransfer, COLLECTION_MIME, collection.id);
                setDragging(true);
              }}
              onDragEnd={() => {
                dragged = null;
                setDragging(false);
                setDropTarget(null);
              }}
              onDragOver={(event) => onDragOver(event, node)}
              onDragLeave={() => setDropTarget(null)}
              onDrop={(event) => onDrop(event, node)}
              style={{ paddingLeft: `${depth * 0.9 + 0.25}rem` }}
              className={cn(
                "group relative flex items-center gap-1 rounded-md py-1 pr-1.5 text-sm",
                selectedId === collection.id ? "bg-panel-2 text-text" : "text-muted",
                spot === "inside" && "ring-1 ring-accent",
              )}
            >
              {(spot === "before" || spot === "after") && (
                <span
                  aria-hidden
                  style={{ left: `${lineDepth * 0.9 + 0.25}rem` }}
                  className={cn(
                    "pointer-events-none absolute right-0 h-0.5 rounded-full bg-accent",
                    spot === "before" ? "-top-px" : "-bottom-px",
                  )}
                />
              )}
              <button
                type="button"
                onClick={() => toggle(collection.id)}
                aria-label={t(open ? "collections.collapse" : "collections.expand")}
                className={cn("shrink-0 rounded p-0.5", node.children.length === 0 && "invisible")}
              >
                {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              </button>
              <button
                type="button"
                onClick={() => onSelect(collection.id)}
                className="flex min-w-0 flex-1 items-center gap-1.5 text-left hover:text-text"
              >
                {isSmart ? (
                  <Sparkles size={14} className="shrink-0 text-accent" />
                ) : open && node.children.length > 0 ? (
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
              {/* A sub-collection starts from its parent, in one click (user feedback). Only a
                  manual collection can hold others. Shown on hover, and on keyboard focus. */}
              {onCreateChild && !isSmart && (
                <button
                  type="button"
                  onClick={() => onCreateChild(collection.id)}
                  title={t("collections.newSubIn", { name: collection.name })}
                  aria-label={t("collections.newSubIn", { name: collection.name })}
                  className="shrink-0 rounded p-0.5 text-muted opacity-0 group-hover:opacity-100 hover:bg-panel-2 hover:text-text focus-visible:opacity-100"
                >
                  <Plus size={13} />
                </button>
              )}
            </div>
            {open && node.children.length > 0 && (
              <ul className="space-y-0.5">
                <TreeLevel
                  rows={rows}
                  nodes={node.children}
                  depth={depth + 1}
                  isOpen={isOpen}
                  toggle={toggle}
                  selectedId={selectedId}
                  onSelect={onSelect}
                  onMove={onMove}
                  onDropArtworks={onDropArtworks}
                  onCreateChild={onCreateChild}
                  dropTarget={dropTarget}
                  setDropTarget={setDropTarget}
                  setDragging={setDragging}
                />
              </ul>
            )}
          </li>
        );
      })}
    </>
  );
}
