import { Cast, Link2, MonitorPlay, Plus, RefreshCw, Trash2, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DisplayTarget } from "@/api/client";
import {
  useDisplayActions,
  useDisplayCapabilities,
  useDisplayStatus,
  useDisplayTargets,
} from "@/api/queries";
import { problemMessage } from "@/shared/problem";
import { formatRelative } from "@/shared/format";
import { toast } from "@/shared/toast";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Badge, EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

/**
 * The TVs this library pushes to (`docs/tv-display.md`).
 *
 * Two things here are honesty rather than decoration: a push **mirrors** (the Frame's slideshow
 * plays a whole category, so the set is everything the TV shows), and photos this app did not
 * upload are only removed after an explicit confirmation — the TV cannot give an image back.
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
  const { create } = useDisplayActions();
  const [name, setName] = useState("");
  const [host, setHost] = useState("");

  const submit = () => {
    create.mutate(
      { name, host: host.trim() },
      {
        onSuccess: () => {
          setName("");
          setHost("");
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("display.addTv")}
      description={t("display.addHint")}
    >
      <div className="space-y-3">
        <label className="block space-y-1 text-sm">
          {t("display.name")}
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("display.namePlaceholder")}
            className="w-full rounded-md border border-border bg-bg px-2 py-1.5"
          />
        </label>
        <label className="block space-y-1 text-sm">
          {t("display.address")}
          <input
            value={host}
            onChange={(event) => setHost(event.target.value)}
            placeholder="192.168.1.71"
            className="w-full rounded-md border border-border bg-bg px-2 py-1.5"
          />
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" disabled={host.trim().length < 3} onClick={submit}>
            {t("common.add")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function TargetCard({ target }: { target: DisplayTarget }) {
  const { t } = useTranslation();
  const caps = useDisplayCapabilities();
  const { update, remove, pair, push } = useDisplayActions();
  const [checking, setChecking] = useState(false);
  const status = useDisplayStatus(checking ? target.id : null);
  const [confirmForeign, setConfirmForeign] = useState(false);

  const foreign = status.data?.foreign ?? 0;
  const minutes = caps.data?.slideshow_minutes ?? [3, 15, 60, 720, 1440];

  const doPush = (allowDeleteForeign: boolean) => {
    push.mutate(
      { id: target.id, allowDeleteForeign },
      { onSuccess: () => toast.info("display.pushQueued") },
    );
    setConfirmForeign(false);
  };

  return (
    <section className="space-y-3 rounded-lg border border-border bg-panel p-4">
      <header className="flex flex-wrap items-center gap-2">
        <MonitorPlay size={16} className="text-accent" />
        <h2 className="text-sm font-semibold">{target.name}</h2>
        <span className="text-xs text-muted">{target.host}</span>
        {target.model && <Badge>{target.model}</Badge>}
        {target.paired ? (
          <Badge tone="accent">{t("display.paired")}</Badge>
        ) : (
          <Badge tone="danger">{t("display.notPaired")}</Badge>
        )}
        {target.last_error && <Badge tone="danger">{t(`errors.${target.last_error}`)}</Badge>}
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
        <Button size="sm" variant="ghost" onClick={() => remove.mutate(target.id)}>
          <Trash2 size={14} />
        </Button>
      </header>

      {pair.isPending && <p className="text-xs text-muted">{t("display.pairWaiting")}</p>}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <Fact label={t("display.showing")} value={target.source_label ?? t("display.noSet")} />
        <Fact
          label={t("display.onTheTv")}
          value={t("display.itemCount", { count: target.item_count })}
        />
        <Fact
          label={t("display.lastPush")}
          value={target.last_pushed_at ? formatRelative(target.last_pushed_at) : "—"}
        />
        <Fact label={t("display.artApi")} value={target.api_version ?? "—"} />
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
              {foreign > 0 && (
                <span className="flex items-center gap-1 text-warning">
                  <TriangleAlert size={12} /> {t("display.foreignCount", { count: foreign })}
                </span>
              )}
            </div>
          ) : null}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-2">
          {t("display.every")}
          <select
            value={target.slideshow_minutes}
            onChange={(event) =>
              update.mutate({ id: target.id, slideshow_minutes: Number(event.target.value) })
            }
            className="rounded border border-border bg-bg px-1.5 py-1"
          >
            {minutes.map((value) => (
              <option key={value} value={value}>
                {t(`display.intervals.${value}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={target.slideshow_ordered}
            onChange={(event) =>
              update.mutate({ id: target.id, slideshow_ordered: event.target.checked })
            }
          />
          {t("display.playInOrder")}
        </label>
        <span className="flex-1" />
        <Button
          size="sm"
          variant="primary"
          disabled={!target.paired || !target.source || push.isPending}
          title={!target.source ? t("display.noSetHint") : t("display.pushHint")}
          onClick={() => (foreign > 0 ? setConfirmForeign(true) : doPush(false))}
        >
          <Cast size={14} /> {t("display.push")}
        </Button>
      </div>

      <Dialog
        open={confirmForeign}
        onOpenChange={setConfirmForeign}
        title={t("display.foreignTitle")}
        description={t("display.foreignDescription", { count: foreign })}
      >
        <div className="space-y-3 text-sm">
          <p className="text-muted">{t("display.foreignWarning")}</p>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmForeign(false)}>
              {t("common.cancel")}
            </Button>
            <Button variant="ghost" onClick={() => doPush(false)}>
              {t("display.keepThem")}
            </Button>
            <Button variant="danger" onClick={() => doPush(true)}>
              {t("display.deleteThem", { count: foreign })}
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
