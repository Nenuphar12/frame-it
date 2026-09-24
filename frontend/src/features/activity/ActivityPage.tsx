import { useNavigate } from "@tanstack/react-router";
import { CheckCircle2, RefreshCw, RotateCcw, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useJobActions, useJobs } from "@/api/queries";
import { formatDateTime } from "@/shared/format";
import { messageForCode } from "@/shared/problem";
import { toast } from "@/shared/toast";
import { Button } from "@/shared/ui/Button";
import { Badge, EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

type Job = NonNullable<ReturnType<typeof useJobs>["data"]>["jobs"][number];

/** Jobs the user can act on from here: everything else is history. */
const SHOWN = ["failed", "dismissed", "done"] as const;

function subjectLink(job: Job): string | null {
  return job.kind === "render" && job.subject_id ? `/editor/${job.subject_id}` : null;
}

function JobRow({ job }: { job: Job }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { retry, dismiss } = useJobActions();
  const [busy, setBusy] = useState(false);
  const failed = job.state === "failed";
  const link = subjectLink(job);

  const run = (action: "retry" | "dismiss") => {
    setBusy(true);
    const mutation = action === "retry" ? retry : dismiss;
    mutation.mutate(job.id, {
      onSuccess: () => action === "retry" && toast.success("activity.retryQueued"),
      onError: (error) => toast.error(error, "activity.retryFailed"),
      onSettled: () => setBusy(false),
    });
  };

  return (
    <li className="flex items-start gap-3 border-b border-border px-5 py-3 last:border-b-0">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">
            {t(`activity.kinds.${job.kind.replace(".", "_")}`, { defaultValue: job.kind })}
          </span>
          <Badge tone={failed ? "danger" : job.state === "done" ? "accent" : "neutral"}>
            {t(`activity.states.${job.state}`, { defaultValue: job.state })}
          </Badge>
          {job.attempts > 1 && (
            <span className="text-[11px] text-muted">
              {t("activity.attempts", { count: job.attempts })}
            </span>
          )}
        </div>
        {job.error && (
          <p className="text-xs text-danger">{messageForCode(t, job.code ?? undefined, job.error)}</p>
        )}
        {/* The raw text stays available: a traceback is what makes a bug report useful. */}
        {job.error && job.code && (
          <details className="text-[11px] text-muted">
            <summary className="cursor-pointer select-none">{t("activity.details")}</summary>
            <pre className="mt-1 max-h-40 overflow-auto rounded bg-panel-2 p-2 whitespace-pre-wrap">
              {job.error}
            </pre>
          </details>
        )}
        <p className="text-[11px] text-muted">
          {formatDateTime(job.finished_at ?? job.created_at)}
          {link && (
            <>
              {" · "}
              <button
                className="text-accent underline-offset-2 hover:underline"
                onClick={() => void navigate({ to: link })}
              >
                {t("activity.openArtwork")}
              </button>
            </>
          )}
        </p>
      </div>
      {failed && (
        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            size="sm"
            disabled={busy || !job.retriable}
            title={job.retriable ? undefined : t("activity.notRetriable")}
            onClick={() => run("retry")}
          >
            <RotateCcw size={13} /> {t("activity.retry")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            aria-label={t("activity.dismiss")}
            onClick={() => run("dismiss")}
          >
            <X size={14} />
          </Button>
        </div>
      )}
    </li>
  );
}

/**
 * The activity centre (`docs/PLAN.md` §14 phase 11): work that happened off-screen and did not
 * succeed. A render, an ingest or an export that failed used to be visible only as an artwork
 * that never appeared; here it says what went wrong and offers the same work again.
 */
export function ActivityPage() {
  const { t } = useTranslation();
  const jobs = useJobs(SHOWN);
  const { dismissAll } = useJobActions();
  const rows = jobs.data?.jobs ?? [];
  const failed = jobs.data?.failed ?? 0;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("nav.activity")}
        subtitle={jobs.data ? t("activity.summary", { count: failed }) : undefined}
        actions={
          <>
            <Button size="sm" variant="ghost" onClick={() => void jobs.refetch()}>
              <RefreshCw size={14} /> {t("common.refresh")}
            </Button>
            <Button
              size="sm"
              disabled={failed === 0 || dismissAll.isPending}
              onClick={() =>
                dismissAll.mutate(undefined, {
                  onError: (error) => toast.error(error),
                })
              }
            >
              {t("activity.dismissAll")}
            </Button>
          </>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {jobs.isPending ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<CheckCircle2 size={28} />}
            title={t("activity.empty")}
            description={t("activity.emptyHint")}
          />
        ) : (
          <ul>
            {rows.map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
