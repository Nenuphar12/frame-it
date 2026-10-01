import {
  Cast,
  Link2,
  MonitorPlay,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DiscoveredTv, DisplayPlan, DisplayTarget } from "@/api/client";
import {
  useDisplayActions,
  useDisplayDiscover,
  useDisplayStatus,
  useDisplayTargets,
} from "@/api/queries";
import { cn } from "@/shared/cn";
import { formatRelative } from "@/shared/format";
import { messageForCode, problemMessage } from "@/shared/problem";
import { toast } from "@/shared/toast";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Badge, EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

import { livePush, pushFraction, usePushes } from "./pushStore";
import { SlideshowSettings } from "./SlideshowSettings";
import { DONT_CHANGE, phaseLabel, pushSummary } from "./summary";

/**
 * The TVs this library pushes to (`docs/tv-display.md`).
 *
 * Two things here are honesty rather than decoration: a slideshow push **mirrors** (the Frame's
 * slideshow plays a whole category, so the set is everything the TV shows), and photos this app
 * did not upload are only removed after an explicit confirmation — the TV cannot give an image
 * back. "Don't change" shows one image and deletes nothing.
 */
export function DisplayPage() {
  const { t } = useTranslation();
  const targets = useDisplayTargets();
  const [adding, setAdding] = useState(false);
  const list = targets.data?.targets ?? [];

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("display.title")}
        actions={
          <Button size="sm" variant="primary" onClick={() => setAdding(true)}>
            <Plus size={14} /> {t("display.addTv")}
          </Button>
        }
      />
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        {targets.isLoading ? (
          <Spinner />
        ) : list.length === 0 ? (
          <EmptyState
            icon={<MonitorPlay size={28} />}
            title={t("display.emptyTitle")}
            description={t("display.emptyDescription")}
            action={
              <Button variant="primary" onClick={() => setAdding(true)}>
                <Plus size={14} /> {t("display.addTv")}
              </Button>
            }
          />
        ) : (
          list.map((target) => <TargetCard key={target.id} target={target} />)
        )}
      </div>
      <AddTvDialog open={adding} onOpenChange={setAdding} />
    </div>
  );
}

function AddTvDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("display.addTv")}
      description={t("display.addHint")}
    >
      {/* Mounted while open only: the scan runs each time the dialog opens. */}
      <AddTvBody onDone={() => onOpenChange(false)} />
    </Dialog>
  );
}

function AddTvBody({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const { create } = useDisplayActions();
  const scan = useDisplayDiscover(true);
  const tvs = scan.data?.tvs ?? [];
  const [picked, setPicked] = useState<string | null>(null);
  const [manual, setManual] = useState("");
  const [name, setName] = useState<string | null>(null);
  // A typed address wins; otherwise the TV picked in the list, else the recommended one.
  const chosen: DiscoveredTv | null = manual.trim()
    ? null
    : (tvs.find((tv) => tv.host === picked && !tv.target_id) ??
      tvs.find((tv) => tv.recommended) ??
      null);
  const host = manual.trim() || chosen?.host || "";
  const effectiveName = name ?? chosen?.name ?? "";

  const submit = () =>
    create.mutate(
      {
        name: effectiveName,
        host,
        ...(chosen?.mac ? { mac: chosen.mac } : {}),
        ...(chosen?.model ? { model: chosen.model } : {}),
      },
      { onSuccess: onDone },
    );

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 text-sm">
          <span className="flex-1 text-muted">
            {scan.isFetching
              ? t("display.scanning", { subnet: scan.data?.subnet ?? "…" })
              : scan.data?.subnet
                ? t("display.scanned", { subnet: scan.data.subnet })
                : t("display.scannedNoSubnet")}
          </span>
          <Button
            size="sm"
            variant="ghost"
            disabled={scan.isFetching}
            onClick={() => void scan.refetch()}
          >
            {scan.isFetching ? <Spinner /> : <Search size={14} />} {t("display.scanAgain")}
          </Button>
        </div>
        {scan.error ? (
          <p className="text-xs text-danger">{problemMessage(t, scan.error)}</p>
        ) : !scan.isFetching && tvs.length === 0 ? (
          <p className="text-xs text-muted">{t("display.noTvFound")}</p>
        ) : (
          <div role="radiogroup" aria-label={t("display.foundTvs")} className="space-y-1.5">
            {tvs.map((tv) => {
              const added = Boolean(tv.target_id);
              const checked = !manual.trim() && chosen?.host === tv.host;
              return (
                <button
                  key={tv.host}
                  type="button"
                  role="radio"
                  aria-checked={checked}
                  disabled={added}
                  onClick={() => {
                    setPicked(tv.host);
                    setManual("");
                    setName(null);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md border p-2.5 text-left text-sm disabled:opacity-60",
                    checked ? "border-accent bg-accent/10" : "border-border hover:bg-panel-2",
                  )}
                >
                  <MonitorPlay size={15} className="shrink-0 text-muted" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{tv.name ?? tv.host}</span>
                    <span className="block text-xs text-muted">
                      {[tv.model, tv.host].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  {tv.recommended && <Badge tone="accent">{t("display.recommended")}</Badge>}
                  {added ? (
                    <Badge>{t("display.alreadyAdded")}</Badge>
                  ) : (
                    !tv.frame_support && <Badge>{t("display.notAFrame")}</Badge>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <label className="block space-y-1 text-sm">
        {t("display.orAddress")}
        <input
          value={manual}
          onChange={(event) => setManual(event.target.value)}
          placeholder="192.168.1.71"
          className="w-full rounded-md border border-border-strong bg-bg px-2 py-1.5"
        />
      </label>
      <label className="block space-y-1 text-sm">
        {t("display.name")}
        <input
          value={effectiveName}
          onChange={(event) => setName(event.target.value)}
          placeholder={t("display.namePlaceholder")}
          className="w-full rounded-md border border-border-strong bg-bg px-2 py-1.5"
        />
      </label>
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" onClick={onDone}>
          {t("common.cancel")}
        </Button>
        <Button variant="primary" disabled={host.length < 3 || create.isPending} onClick={submit}>
          {t("common.add")}
        </Button>
      </div>
    </div>
  );
}

function TargetCard({ target }: { target: DisplayTarget }) {
  const { t } = useTranslation();
  const { update, remove, pair, push, plan } = useDisplayActions();
  const [checking, setChecking] = useState(false);
  const status = useDisplayStatus(checking ? target.id : null);
  const [confirm, setConfirm] = useState<DisplayPlan | null>(null);
  const progress = livePush(target, usePushes());
  const isStatic = target.slideshow_minutes === DONT_CHANGE;
  const result = target.last_result;

  const doPush = (allowDeleteForeign: boolean) => {
    push.mutate(
      { id: target.id, allowDeleteForeign },
      { onSuccess: () => toast.info("display.pushQueued") },
    );
    setConfirm(null);
  };

  /**
   * Ask the TV first (a dry run): whether photos this app did not send are there decides whether
   * the user is asked — not whether somebody happened to press "Check the TV" before.
   */
  const send = () =>
    plan.mutate(
      { id: target.id, check_tv: true },
      {
        onSuccess: (dry) => {
          if (dry.tv_error) {
            toast.problem(dry.tv_error, "display.tvDidNotAnswer");
            return;
          }
          if (dry.mode === "slideshow" && (dry.foreign ?? 0) > 0) setConfirm(dry);
          else doPush(false);
        },
      },
    );

  return (
    <section className="space-y-3 rounded-lg border border-border bg-panel p-4">
      <header className="flex flex-wrap items-center gap-2">
        <MonitorPlay size={16} className="text-accent" />
        <h2 className="text-sm font-semibold">{target.name}</h2>
        <span className="text-xs text-muted">{target.host}</span>
        {target.model && (
          <Badge title={`${t("display.artApi")} ${target.api_version ?? "—"}`}>
            {target.model}
          </Badge>
        )}
        {target.paired ? (
          <Badge tone="accent">{t("display.paired")}</Badge>
        ) : (
          <Badge tone="danger">{t("display.notPaired")}</Badge>
        )}
        {target.last_error && !progress && (
          <Badge tone="danger">{messageForCode(t, target.last_error)}</Badge>
        )}
        <span className="flex-1" />
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setChecking(true);
            void status.refetch();
          }}
        >
          <RefreshCw size={14} /> {t("display.checkTv")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={pair.isPending}
          title={t("display.pairHint")}
          onClick={() =>
            pair.mutate(target.id, {
              onSuccess: () => toast.success("display.pairedToast"),
            })
          }
        >
          {pair.isPending ? <Spinner /> : <Link2 size={14} />}{" "}
          {target.paired ? t("display.repair") : t("display.pair")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => remove.mutate(target.id)}
          aria-label={t("display.removeTv")}
          title={t("display.removeTv")}
        >
          <Trash2 size={14} />
        </Button>
      </header>

      {pair.isPending && <p className="text-xs text-muted">{t("display.pairWaiting")}</p>}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <Fact label={t("display.showing")} value={target.source_label ?? t("display.noSet")} />
        <Fact
          label={t("display.onTheTv")}
          value={
            target.item_count > target.set_count
              ? t("display.itemCountWithOld", {
                  count: target.item_count,
                  inSet: target.set_count,
                })
              : t("display.itemCount", { count: target.item_count })
          }
        />
        <Fact
          label={t("display.notFromThisApp")}
          value={
            target.foreign_count === null || target.foreign_count === undefined
              ? "—"
              : t("display.foreignAsOf", {
                  count: target.foreign_count,
                  when: formatRelative(target.checked_at),
                })
          }
        />
        <Fact
          label={t("display.lastPush")}
          value={target.last_pushed_at ? formatRelative(target.last_pushed_at) : "—"}
        />
      </dl>

      {checking && (
        <div className="rounded-md border border-border bg-bg px-3 py-2 text-xs">
          {status.isFetching ? (
            <Spinner />
          ) : status.error ? (
            <span className="text-danger">{problemMessage(t, status.error)}</span>
          ) : status.data ? (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <span>
                {t("display.artMode")}: {status.data.art_mode ? t("common.on") : t("common.off")}
              </span>
              <span>{t("display.myPhotos", { count: status.data.my_pictures })}</span>
              <span>{t("display.fromThisApp", { count: status.data.ours })}</span>
              {status.data.slideshow_minutes ? (
                <span>
                  {t("display.rotating", { minutes: status.data.slideshow_minutes })}
                  {status.data.slideshow_ordered ? ` · ${t("display.inOrder")}` : ""}
                </span>
              ) : (
                <span>{t("display.slideshowOff")}</span>
              )}
              {status.data.foreign > 0 && (
                <span className="flex items-center gap-1 text-warning">
                  <TriangleAlert size={12} />{" "}
                  {t("display.foreignCount", { count: status.data.foreign })}
                </span>
              )}
              {status.data.moved_from && (
                <span className="text-muted">
                  {t("display.movedNotice", {
                    from: status.data.moved_from,
                    to: status.data.target.host,
                  })}
                </span>
              )}
            </div>
          ) : null}
        </div>
      )}

      {progress ? (
        <div className="space-y-1 text-xs" aria-live="polite">
          <div className="flex items-center gap-2">
            <Spinner size={12} />
            <span>{phaseLabel(t, progress)}</span>
          </div>
          <div className="h-1 overflow-hidden rounded bg-panel-2">
            <div
              className="h-full bg-accent transition-[width]"
              style={{ width: `${Math.round(pushFraction(progress) * 100)}%` }}
            />
          </div>
        </div>
      ) : (
        result && (
          <p className="text-xs text-muted">
            <span className="text-text">{t("display.lastResult")}</span> {pushSummary(t, result)}
          </p>
        )
      )}

      <div className="flex flex-wrap items-center gap-3">
        <SlideshowSettings
          minutes={target.slideshow_minutes}
          ordered={target.slideshow_ordered}
          onChange={(next) =>
            update.mutate({
              id: target.id,
              ...(next.minutes !== undefined ? { slideshow_minutes: next.minutes } : {}),
              ...(next.ordered !== undefined ? { slideshow_ordered: next.ordered } : {}),
            })
          }
        />
        <span className="flex-1" />
        <Button
          size="sm"
          variant="primary"
          disabled={
            !target.paired || !target.source || push.isPending || plan.isPending || !!progress
          }
          title={
            !target.source
              ? t("display.noSetHint")
              : isStatic
                ? t("display.pushStaticHint")
                : t("display.pushHint")
          }
          onClick={send}
        >
          {plan.isPending ? <Spinner /> : <Cast size={14} />} {t("display.push")}
        </Button>
      </div>

      <Dialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={t("display.foreignTitle")}
        description={t("display.foreignDescription", { count: confirm?.foreign ?? 0 })}
      >
        <div className="space-y-3 text-sm">
          <p className="text-muted">{t("display.foreignWarning")}</p>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirm(null)}>
              {t("common.cancel")}
            </Button>
            <Button variant="ghost" onClick={() => doPush(false)}>
              {t("display.keepThem")}
            </Button>
            <Button variant="danger" onClick={() => doPush(true)}>
              {t("display.deleteThem", { count: confirm?.foreign ?? 0 })}
            </Button>
          </div>
        </div>
      </Dialog>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="truncate">{value}</dd>
    </div>
  );
}
