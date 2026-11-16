import { ChevronDown, ChevronRight, Folder, FolderOpen, Home } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Collection } from "@/api/client";
import { cn } from "@/shared/cn";

import { buildTree, type TreeNode } from "./tree";

interface ParentPickerProps {
  /** Every collection; only manual ones can hold others, so smart ones are not offered. */
  rows: Collection[];
  /** The chosen parent's id, or `""` for the top level. */
  value: string;
  onChange: (parentId: string) => void;
  /** Never offered: the collection being edited and its own descendants (a cycle). */
  excluded: ReadonlySet<string>;
}

/**
 * Where a collection lives, picked **in the tree** rather than from a flat list of names (user
 * feedback: "the *inside* must be reworked to show the arborescence"). Closed, it reads as the
 * path — *Top level › Travel › 2026* — so a sub-collection started from its parent says where it
 * will land at a glance; open, it is the tree itself, one click per choice.
 */
export function ParentPicker({ rows, value, onChange, excluded }: ParentPickerProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const tree = useMemo(
    () => buildTree(rows.filter((c) => c.kind === "manual" && !excluded.has(c.id))),
    [excluded, rows],
  );
  const byId = useMemo(() => new Map(rows.map((c) => [c.id, c])), [rows]);
  const path = useMemo(() => {
    const out: Collection[] = [];
    let current = value ? byId.get(value) : undefined;
    while (current && out.length < 64) {
      out.unshift(current);
      current = current.parent_id ? byId.get(current.parent_id) : undefined;
    }
    return out;
  }, [byId, value]);

  const choose = (parentId: string) => {
    onChange(parentId);
    setOpen(false);
  };

  return (
    <div className="rounded-md border border-border bg-bg">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center gap-1 px-2.5 py-1.5 text-left text-sm"
      >
        {open ? (
          <ChevronDown size={14} className="shrink-0 text-muted" />
        ) : (
          <ChevronRight size={14} className="shrink-0 text-muted" />
        )}
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1 text-muted">
          <span className={cn(path.length === 0 && "text-text")}>{t("collections.topLevel")}</span>
          {path.map((collection, index) => (
            <span key={collection.id} className="flex min-w-0 items-center gap-1">
              <span aria-hidden>›</span>
              <span className={cn("truncate", index === path.length - 1 && "text-text")}>
                {collection.name}
              </span>
            </span>
          ))}
        </span>
        <span className="shrink-0 text-xs text-muted">{t("collections.changeParent")}</span>
      </button>
      {open && (
        <ul
          role="listbox"
          aria-label={t("collections.parent")}
          className="max-h-56 space-y-0.5 overflow-y-auto border-t border-border p-1"
        >
          <li>
            <Row
              depth={0}
              selected={value === ""}
              onClick={() => choose("")}
              icon={<Home size={14} className="shrink-0" />}
              label={t("collections.topLevel")}
            />
          </li>
          <Branch nodes={tree} depth={1} value={value} choose={choose} />
        </ul>
      )}
    </div>
  );
}

function Branch({
  nodes,
  depth,
  value,
  choose,
}: {
  nodes: TreeNode[];
  depth: number;
  value: string;
  choose: (id: string) => void;
}) {
  return (
    <>
      {nodes.map((node) => (
        <li key={node.collection.id}>
          <Row
            depth={depth}
            selected={value === node.collection.id}
            onClick={() => choose(node.collection.id)}
            icon={
              node.children.length > 0 ? (
                <FolderOpen size={14} className="shrink-0" />
              ) : (
                <Folder size={14} className="shrink-0" />
              )
            }
            label={node.collection.name}
          />
          {node.children.length > 0 && (
            <ul className="space-y-0.5">
              <Branch nodes={node.children} depth={depth + 1} value={value} choose={choose} />
            </ul>
          )}
        </li>
      ))}
    </>
  );
}

function Row({
  depth,
  selected,
  onClick,
  icon,
  label,
}: {
  depth: number;
  selected: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={onClick}
      style={{ paddingLeft: `${depth * 0.9 + 0.4}rem` }}
      className={cn(
        "flex w-full items-center gap-1.5 rounded py-1 pr-2 text-left text-sm",
        selected ? "bg-accent/10 text-accent" : "text-muted hover:bg-panel-2 hover:text-text",
      )}
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  );
}
