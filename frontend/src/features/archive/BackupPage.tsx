import { Archive, FileArchive, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useExportActions, useExports } from "@/api/queries";
import { formatRelative } from "@/shared/format";
import { Button } from "@/shared/ui/Button";
import { EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

import { ExportDialog, JobRow } from "./ExportDialog";
import { ImportPanel } from "./ImportPanel";

/**
 * Export & import (docs/archive-format.md): back the library up, move it to another machine, or
 * pull pictures out as finished images. A partial export starts from a selection on a grid of
 * artworks instead — the same dialog, given ids.
 */
export function BackupPage() {
  const { t } = useTranslation();
  const exports = useExports();
  const { remove } = useExportActions();
  const [dialogOpen, setDialogOpen] = useState(false);
  const jobs = exports.data ?? [];

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("nav.backup")}
        subtitle={t("archive.pageSubtitle")}
        actions={
          <Button variant="primary" size="sm" onClick={() => setDialogOpen(true)}>
            <FileArchive size={14} /> {t("archive.exportTitle")}
          </Button>
        }
      />
      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-4">
        <ImportPanel />

        <section className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold">{t("archive.recentExports")}</h2>
            <p className="text-xs text-muted">{t("archive.recentExportsHint", { hours: 24 })}</p>
          </div>
          {exports.isLoading ? (
            <Spinner size={18} />
          ) : jobs.length === 0 ? (
            <EmptyState
              compact
              icon={<Archive size={32} />}
              title={t("archive.noExports")}
              description={t("archive.noExportsHint")}
            />
          ) : (
            <ul className="space-y-2">
              {jobs.map((job) => (
                <li key={job.job_id} className="flex items-center gap-2">
                  <div className="min-w-0 flex-1">
                    <JobRow job={job} />
                  </div>
                  <span className="w-28 shrink-0 text-right text-xs text-muted">
                    {t(`archive.kind.${job.kind === "renders" ? "renders" : "library"}`)}
                    <br />
                    {formatRelative(job.created_at)}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t("common.delete")}
                    onClick={() => remove.mutate(job.job_id)}
                  >
                    <Trash2 size={14} />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <ExportDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
