import { Download, FileArchive, Images } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { exportDownloadUrl, type ExportJob } from "@/api/client";
import { useExportActions, useExports } from "@/api/queries";
import { formatBytes } from "@/shared/format";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Spinner } from "@/shared/ui/Misc";

interface ExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** A selection makes the export partial (docs/archive-format.md §12.1); empty = whole library. */
  artworkIds?: string[];
  collectionIds?: string[];
}

type Kind = "library" | "renders";

/**
 * Start an export and watch it finish. The same dialog serves the Backup page (whole library) and
 * a selection on any grid of artworks — the only difference is what it was given.
 */
export function ExportDialog({
  open,
  onOpenChange,
  artworkIds = [],
  collectionIds = [],
}: ExportDialogProps) {
  const { t } = useTranslation();
  const { start } = useExportActions();
  const exports = useExports();
  const [kind, setKind] = useState<Kind>("library");
  const [includeRenders, setIncludeRenders] = useState(false);
  const [includeTemplates, setIncludeTemplates] = useState(true);
  const [includeNested, setIncludeNested] = useState(true);
  const [format, setFormat] = useState<"jpg" | "png">("jpg");
  const [jobId, setJobId] = useState<string | null>(null);
  const partial = artworkIds.length > 0 || collectionIds.length > 0;
  // "3 artworks and 1 collection": two counts, so two plural keys joined rather than one string.
  const what = [
    artworkIds.length > 0 ? t("archive.exportScopeArtworks", { count: artworkIds.length }) : null,
    collectionIds.length > 0
      ? t("archive.exportScopeCollections", { count: collectionIds.length })
      : null,
  ]
    .filter(Boolean)
    .join(t("archive.and"));
  const job = (exports.data ?? []).find((row) => row.job_id === jobId) ?? null;

  const submit = () => {
    void start
      .mutateAsync({
        kind,
        artwork_ids: artworkIds,
        collection_ids: collectionIds,
        include_nested: includeNested,
        include_renders: kind === "library" && includeRenders,
        include_templates: includeTemplates,
        render_format: format,
      })
      .then((created) => setJobId(created.job_id));
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setJobId(null);
      }}
      title={t("archive.exportTitle")}
      description={
        partial ? t("archive.exportScopePartial", { what }) : t("archive.exportScopeFull")
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2">
          <KindCard
            active={kind === "library"}
            icon={<FileArchive size={16} />}
            label={t("archive.kindLibrary")}
            hint={t("archive.kindLibraryHint")}
            onClick={() => setKind("library")}
          />
          <KindCard
            active={kind === "renders"}
            icon={<Images size={16} />}
            label={t("archive.kindRenders")}
            hint={t("archive.kindRendersHint")}
            onClick={() => setKind("renders")}
          />
        </div>

        <div className="space-y-2 text-sm">
          {kind === "library" ? (
            <>
              <Check
                checked={includeRenders}
                onChange={setIncludeRenders}
                label={t("archive.includeRenders")}
                hint={t("archive.includeRendersHint")}
              />
              <Check
                checked={includeTemplates}
                onChange={setIncludeTemplates}
                label={t("archive.includeTemplates")}
              />
            </>
          ) : (
            <label className="flex items-center gap-2">
              <span className="text-muted">{t("archive.renderFormat")}</span>
              <select
                value={format}
                onChange={(event) => setFormat(event.target.value as "jpg" | "png")}
                className="rounded-md border border-border bg-bg px-2 py-1 text-sm"
              >
                <option value="jpg">JPEG</option>
                <option value="png">PNG</option>
              </select>
            </label>
          )}
          {collectionIds.length > 0 && (
            <Check
              checked={includeNested}
              onChange={setIncludeNested}
              label={t("archive.includeNested")}
            />
          )}
        </div>

        {job ? <JobRow job={job} /> : null}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.close")}
          </Button>
          <Button variant="primary" onClick={submit} disabled={start.isPending}>
            {start.isPending ? <Spinner size={14} /> : null} {t("archive.startExport")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function KindCard({
  active,
  icon,
  label,
  hint,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-lg border p-3 text-left transition ${
        active ? "border-accent bg-accent/10" : "border-border bg-panel-2 hover:border-accent/40"
      }`}
    >
      <span className="flex items-center gap-2 text-sm font-medium">
        {icon} {label}
      </span>
      <span className="mt-1 block text-xs text-muted">{hint}</span>
    </button>
  );
}

function Check({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <label className="flex items-start gap-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5"
      />
      <span>
        {label}
        {hint && <span className="block text-xs text-muted">{hint}</span>}
      </span>
    </label>
  );
}

/** One export's state: progress while it runs, a download link when it is done. */
export function JobRow({ job }: { job: ExportJob }) {
  const { t } = useTranslation();
  const running = job.state === "queued" || job.state === "running";
  return (
    <div className="rounded-lg border border-border bg-panel-2 p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="min-w-0 truncate">
          {job.filename ?? t(`archive.state.${job.state}`)}
          {job.bytes !== null && <span className="text-muted"> · {formatBytes(job.bytes)}</span>}
        </span>
        {running ? (
          <Spinner size={14} />
        ) : job.state === "done" && job.filename ? (
          <Button size="sm" asChild>
            {/* A plain link: the browser streams it to disk, no secure-context API involved. */}
            <a href={exportDownloadUrl(job.job_id)} download={job.filename}>
              <Download size={14} /> {t("archive.download")}
            </a>
          </Button>
        ) : null}
      </div>
      {running && (
        <div className="mt-2 h-1 overflow-hidden rounded bg-border">
          <div
            className="h-full bg-accent transition-[width]"
            style={{ width: `${Math.round(job.progress * 100)}%` }}
          />
        </div>
      )}
      {job.error && <p className="mt-1 text-xs text-danger">{job.error}</p>}
    </div>
  );
}
