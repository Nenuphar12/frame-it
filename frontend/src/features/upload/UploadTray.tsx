import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  CopyPlus,
  RotateCw,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/shared/cn";
import { formatBytes } from "@/shared/format";
import { Button } from "@/shared/ui/Button";
import { Spinner } from "@/shared/ui/Misc";

import { TagBatchMenu } from "./TagBatchMenu";
import { isFinished, useUploads, type UploadItem } from "./uploadStore";
import { useUploadSummary } from "./useUploadSummary";

export function UploadRow({ item }: { item: UploadItem }) {
  const { t } = useTranslation();
  const retry = useUploads((s) => s.retry);
  const remove = useUploads((s) => s.remove);
  const running = item.status === "hashing" || item.status === "uploading";

  return (
    <li className="flex items-center gap-3 px-3 py-2">
      <div className="w-5 shrink-0">
        {item.status === "done" && <Check size={16} className="text-accent" />}
        {item.status === "duplicate" && <Copy size={16} className="text-info" />}
        {item.status === "merged" && <CopyPlus size={16} className="text-accent" />}
        {(item.status === "failed" || item.status === "rejected") && (
          <AlertTriangle size={16} className="text-danger" />
        )}
        {(running || item.status === "processing" || item.status === "queued") && <Spinner />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex justify-between gap-2 text-sm">
          <span className="truncate">{item.name}</span>
          <span className="shrink-0 text-xs text-muted">{formatBytes(item.size)}</span>
        </div>
        <div className="text-xs text-muted">
          {item.errorCode
            ? t(`errors.${item.errorCode}`, { defaultValue: t("errors.unknown") })
            : item.restored
              ? t("upload.status.restored")
              : t(`upload.status.${item.status}`)}
          {item.source && <> · {t("upload.from", { device: item.source })}</>}
        </div>
        {running && (
          <div className="mt-1 h-1 overflow-hidden rounded bg-panel-2">
            <div
              className={cn(
                "h-full transition-[width]",
                item.status === "hashing" ? "bg-muted" : "bg-accent",
              )}
              style={{ width: `${Math.round(item.progress * 100)}%` }}
            />
          </div>
        )}
      </div>
      {item.status === "failed" && item.file && (
        <button
          className="rounded p-1 text-muted hover:text-text"
          onClick={() => retry(item.id)}
          aria-label={t("upload.retry")}
          title={t("upload.retry")}
        >
          <RotateCw size={14} />
        </button>
      )}
      {isFinished(item.status) && (
        <button
          className="rounded p-1 text-muted hover:text-text"
          onClick={() => remove(item.id)}
          aria-label={t("common.remove")}
          title={t("common.remove")}
        >
          <X size={14} />
        </button>
      )}
    </li>
  );
}

/** Floating desktop panel listing uploads in progress. */
export function UploadTray() {
  const { t } = useTranslation();
  const items = useUploads((s) => s.items);
  const clearFinished = useUploads((s) => s.clearFinished);
  const summary = useUploadSummary();
  const [collapsed, setCollapsed] = useState(false);
  /** The photos this batch landed on — new ones and the ones the library already had. */
  const photoIds = useMemo(
    () => [
      ...new Set(
        items.flatMap((item) =>
          item.photoId &&
          (item.status === "done" || item.status === "duplicate" || item.status === "merged")
            ? [item.photoId]
            : [],
        ),
      ),
    ],
    [items],
  );
  if (items.length === 0) return null;

  return (
    <aside className="fixed right-4 bottom-4 z-30 w-96 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-border bg-panel shadow-2xl">
      <header className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="text-sm font-medium">
          {summary.active > 0
            ? t("upload.trayActive", { count: summary.active })
            : t("upload.trayDone", { done: summary.done, duplicate: summary.duplicate })}
          {summary.problems > 0 && (
            <span className="ml-2 text-danger">
              {t("upload.problems", { count: summary.problems })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <TagBatchMenu photoIds={photoIds} />
          {summary.active === 0 && (
            <Button size="sm" variant="ghost" onClick={clearFinished}>
              {t("upload.clear")}
            </Button>
          )}
          <button
            className="rounded p-1 text-muted hover:text-text"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? t("common.expand") : t("common.collapse")}
          >
            {collapsed ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </header>
      {!collapsed && (
        <ul className="max-h-80 divide-y divide-border overflow-y-auto">
          {items.map((item) => (
            <UploadRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </aside>
  );
}
