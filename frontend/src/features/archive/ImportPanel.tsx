import { AlertTriangle, Check, FileUp, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ImportKindReport, ImportPolicy, ImportResult } from "@/api/client";
import { useImportActions, useImportReport, useImportSession } from "@/api/queries";
import { formatBytes } from "@/shared/format";
import { Button } from "@/shared/ui/Button";
import { Badge, Spinner } from "@/shared/ui/Misc";

import { uploadArchive } from "./uploadArchive";

const POLICIES: ImportPolicy[] = ["keep_mine", "take_theirs", "keep_both"];

/**
 * Receive an archive, show the dry run, choose the policies, apply (docs/archive-format.md §12.2).
 *
 * Nothing is written until *Import*: the report is the server's own classification of every row,
 * and the policies only matter for the `conflicting` ones.
 */
export function ImportPanel() {
  const { t } = useTranslation();
  const picker = useRef<HTMLInputElement>(null);
  const [importId, setImportId] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fallback, setFallback] = useState<ImportPolicy>("keep_mine");
  const [perKind, setPerKind] = useState<Record<string, ImportPolicy>>({});
  const [result, setResult] = useState<ImportResult | null>(null);
  const session = useImportSession(importId);
  const ready = session.data?.state === "ready";
  const report = useImportReport(importId, ready);
  const { apply, discard } = useImportActions();

  const reset = () => {
    setImportId(null);
    setProgress(null);
    setResult(null);
    setPerKind({});
    setError(null);
  };

  const pick = (file: File | undefined) => {
    if (!file) return;
    reset();
    setProgress(0);
    void uploadArchive(file, setProgress)
      .then((id) => {
        setImportId(id);
        setProgress(null);
      })
      .catch((exc: unknown) => {
        setProgress(null);
        setError(exc instanceof Error ? exc.message : String(exc));
      });
  };

  const submit = () => {
    if (!importId) return;
    void apply
      .mutateAsync({ importId, default: fallback, per_kind: perKind })
      .then(setResult)
      .catch((exc: unknown) => setError(exc instanceof Error ? exc.message : String(exc)));
  };

  const kinds = (report.data?.kinds ?? []).filter((kind) => kind.total > 0);
  const conflicts = kinds.reduce((total, kind) => total + kind.conflicting, 0);

  return (
    <section className="space-y-3">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{t("archive.importTitle")}</h2>
          <p className="text-xs text-muted">{t("archive.importHint")}</p>
        </div>
        <input
          ref={picker}
          type="file"
          accept=".tfarchive,.zip,application/zip"
          className="hidden"
          onChange={(event) => pick(event.target.files?.[0])}
        />
        <Button onClick={() => picker.current?.click()} disabled={progress !== null}>
          <FileUp size={14} /> {t("archive.chooseArchive")}
        </Button>
      </header>

      {progress !== null && (
        <div className="rounded-lg border border-border bg-panel-2 p-3 text-sm">
          <span>{t("archive.sending", { percent: Math.round(progress * 100) })}</span>
          <div className="mt-2 h-1 overflow-hidden rounded bg-border">
            <div
              className="h-full bg-accent transition-[width]"
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          </div>
        </div>
      )}

      {error && (
        <p className="flex items-center gap-1.5 text-sm text-danger">
          <AlertTriangle size={14} /> {error}
        </p>
      )}

      {session.data && (
        <div className="space-y-3 rounded-lg border border-border bg-panel p-3">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="min-w-0 truncate">
              {session.data.filename}
              <span className="text-muted"> · {formatBytes(session.data.size)}</span>
            </span>
            <div className="flex items-center gap-2">
              {session.data.state === "staging" && <Spinner size={14} />}
              <Badge tone={session.data.state === "failed" ? "danger" : "neutral"}>
                {t(`archive.importState.${session.data.state}`)}
              </Badge>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  if (importId) discard.mutate(importId);
                  reset();
                }}
                aria-label={t("archive.discard")}
              >
                <Trash2 size={14} />
              </Button>
            </div>
          </div>

          {session.data.state === "failed" && (
            <p className="text-sm text-danger">
              {t([`errors.${session.data.error}`, "archive.refused"])}
            </p>
          )}

          {result ? (
            <ImportSummary result={result} />
          ) : ready ? (
            <>
              {(report.data?.warnings ?? []).map((warning) => (
                <p key={warning} className="text-xs text-warning">
                  {warning}
                </p>
              ))}
              <ReportTable
                kinds={kinds}
                perKind={perKind}
                fallback={fallback}
                onKindPolicy={(kind, policy) =>
                  setPerKind((current) => ({ ...current, [kind]: policy }))
                }
              />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label className="flex items-center gap-2 text-xs text-muted">
                  {t("archive.defaultPolicy")}
                  <PolicySelect value={fallback} onChange={setFallback} />
                </label>
                <Button variant="primary" onClick={submit} disabled={apply.isPending}>
                  {apply.isPending ? <Spinner size={14} /> : null}{" "}
                  {conflicts > 0
                    ? t("archive.applyWithConflicts", { count: conflicts })
                    : t("archive.apply")}
                </Button>
              </div>
            </>
          ) : null}
        </div>
      )}
    </section>
  );
}

function PolicySelect({
  value,
  onChange,
  disabled,
}: {
  value: ImportPolicy;
  onChange: (value: ImportPolicy) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <select
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value as ImportPolicy)}
      className="rounded-md border border-border bg-bg px-2 py-1 text-xs disabled:opacity-40"
    >
      {POLICIES.map((policy) => (
        <option key={policy} value={policy}>
          {t(`archive.policy.${policy}`)}
        </option>
      ))}
    </select>
  );
}

function ReportTable({
  kinds,
  perKind,
  fallback,
  onKindPolicy,
}: {
  kinds: ImportKindReport[];
  perKind: Record<string, ImportPolicy>;
  fallback: ImportPolicy;
  onKindPolicy: (kind: string, policy: ImportPolicy) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-md text-sm">
        <thead className="text-xs text-muted">
          <tr className="border-b border-border text-left">
            <th className="py-1 pr-2 font-medium">{t("archive.column.kind")}</th>
            <th className="py-1 pr-2 text-right font-medium">{t("archive.status.new")}</th>
            <th className="py-1 pr-2 text-right font-medium">{t("archive.status.identical")}</th>
            <th className="py-1 pr-2 text-right font-medium">{t("archive.status.matched")}</th>
            <th className="py-1 pr-2 text-right font-medium">{t("archive.status.conflicting")}</th>
            <th className="py-1 font-medium">{t("archive.column.onConflict")}</th>
          </tr>
        </thead>
        <tbody>
          {kinds.map((kind) => (
            <tr key={kind.kind} className="border-b border-border/60 last:border-0">
              <td className="py-1 pr-2">{t(`archive.kind.${kind.kind}`)}</td>
              <td className="py-1 pr-2 text-right tabular-nums">{kind.new || "—"}</td>
              <td className="py-1 pr-2 text-right tabular-nums text-muted">
                {kind.identical || "—"}
              </td>
              <td className="py-1 pr-2 text-right tabular-nums text-muted">
                {kind.matched || "—"}
              </td>
              <td
                className={`py-1 pr-2 text-right tabular-nums ${
                  kind.conflicting > 0 ? "text-warning" : "text-muted"
                }`}
              >
                {kind.conflicting || "—"}
              </td>
              <td className="py-1">
                <PolicySelect
                  value={perKind[kind.kind] ?? fallback}
                  disabled={kind.conflicting === 0}
                  onChange={(policy) => onKindPolicy(kind.kind, policy)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ImportSummary({ result }: { result: ImportResult }) {
  const { t } = useTranslation();
  const line = (label: string, counts: Record<string, number>) => {
    const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
    return total > 0 ? `${label}: ${total}` : null;
  };
  return (
    <div className="space-y-2 text-sm">
      <p className="flex items-center gap-1.5 text-accent">
        <Check size={14} /> {t("archive.imported")}
      </p>
      <p className="text-xs text-muted">
        {[
          line(t("archive.created"), result.created),
          line(t("archive.updated"), result.updated),
          line(t("archive.skipped"), result.skipped),
          result.renders_adopted > 0
            ? t("archive.rendersAdopted", { count: result.renders_adopted })
            : null,
          result.renders_queued > 0
            ? t("archive.rendersQueued", { count: result.renders_queued })
            : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {result.warnings.map((warning) => (
        <p key={warning} className="text-xs text-warning">
          {warning}
        </p>
      ))}
    </div>
  );
}
