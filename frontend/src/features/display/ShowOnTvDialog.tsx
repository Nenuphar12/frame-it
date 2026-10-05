import { Cast, ChevronDown, ChevronRight, Info, MonitorPlay, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DisplaySource } from "@/api/client";
import { useDisplayActions, useDisplayPlan, useDisplayTargets } from "@/api/queries";
import { messageForCode } from "@/shared/problem";
import { toast } from "@/shared/toast";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Badge, EmptyState, Spinner } from "@/shared/ui/Misc";

import { SlideshowSettings } from "./SlideshowSettings";
import { DONT_CHANGE, slideshowSummary } from "./summary";

interface ShowOnTvDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** What to show: a collection, the current filter, or an explicit list of artworks. */
  source: Partial<DisplaySource>;
  label: string;
}

/**
 * "Show this on the TV": pick a TV, say how it rotates, then push.
 *
 * Every number here comes from the server's dry run (`POST /display/targets/{id}/plan`), first
 * from the app's own memory (instant), then from the TV itself (a few seconds) — so the dialog
 * says how many images go up, how many of ours leave, and whether anybody else's photos are on
 * the TV *before* the user decides. The wording is deliberate: in slideshow mode a push mirrors
 * the set (the Frame plays a whole category), and this is the only warning the user gets before
 * an irreversible delete (`docs/tv-display.md`). "Don't change" deletes nothing, and says so.
 */
export function ShowOnTvDialog({ open, onOpenChange, source, label }: ShowOnTvDialogProps) {
  const { t } = useTranslation();
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("display.showOnTv")}
      description={t("display.showOnTvDescription", { name: label })}
    >
      {/* The body only exists while open: every choice starts fresh the next time. */}
      <ShowOnTvBody source={source} label={label} onDone={() => onOpenChange(false)} />
    </Dialog>
  );
}

function ShowOnTvBody({
  source,
  label,
  onDone,
}: {
  source: Partial<DisplaySource>;
  label: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const targets = useDisplayTargets();
  const { setSource, push } = useDisplayActions();
  const paired = (targets.data?.targets ?? []).filter((target) => target.paired);
  const [picked, setPicked] = useState<string | null>(null);
  // Derived, not stored: the first paired TV is the default until one is chosen, so the list
  // arriving late does not need an effect to fix the selection.
  const target = paired.find((item) => item.id === picked) ?? paired[0] ?? null;

  const explicit = (source.artwork_ids?.length ?? 0) > 0;
  const single = source.artwork_ids?.length === 1;
  // The user's choices in this dialog; until then the TV's own settings — except that a single
  // artwork is meant to stay on screen, so it starts at "Don't change".
  const [rotation, setRotation] = useState<{ minutes?: number; ordered?: boolean }>({});
  const minutes = rotation.minutes ?? (single ? DONT_CHANGE : (target?.slideshow_minutes ?? 60));
  const ordered = rotation.ordered ?? target?.slideshow_ordered ?? true;
  const isStatic = minutes === DONT_CHANGE;
  const [settingsOpen, setSettingsOpen] = useState(false);
  // A collection or a filter is a set the user did not hand-pick: its drafts stay off the wall
  // unless asked. An explicit selection is exactly what the user wants shown.
  const [draftsChoice, setDraftsChoice] = useState<boolean | null>(null);
  const leaveOutDrafts = draftsChoice ?? !explicit;
  const [deleteForeign, setDeleteForeign] = useState(false);
  // In slideshow mode the images sent before leave the TV unless the user keeps them.
  const [removeOurs, setRemoveOurs] = useState(true);

  const query: DisplaySource = {
    include_nested: false,
    sort: "created_desc",
    ...source,
    ...(leaveOutDrafts ? { status: "ready" } : {}),
  };
  const planBody = { source: query, slideshow_minutes: minutes };
  const quick = useDisplayPlan(target?.id ?? null, { ...planBody, check_tv: false });
  const live = useDisplayPlan(target?.id ?? null, { ...planBody, check_tv: true });
  const plan = live.data ?? quick.data;
  const checking = live.isFetching;
  const foreign = plan?.foreign ?? 0;
  const offerDelete = !isStatic && foreign > 0;
  // The dry run is asked without `keep_ours`: keeping them changes no upload, only this count.
  const previous = isStatic ? 0 : (plan?.ours_to_remove ?? 0);
  const keepOurs = previous > 0 && !removeOurs;

  const send = () => {
    if (!target) return;
    setSource.mutate(
      { id: target.id, ...query, label },
      {
        onSuccess: () =>
          push.mutate(
            {
              id: target.id,
              allowDeleteForeign: offerDelete && deleteForeign,
              keepOurs,
              slideshow_minutes: minutes,
              slideshow_ordered: ordered,
            },
            {
              onSuccess: () => {
                toast.info("display.pushQueued");
                onDone();
              },
            },
          ),
      },
    );
  };
  const busy = setSource.isPending || push.isPending;

  if (targets.isLoading) return <Spinner />;
  if (paired.length === 0 || !target) {
    return (
      <EmptyState
        compact
        icon={<MonitorPlay size={24} />}
        title={t("display.noTvTitle")}
        description={t("display.noTvDescription")}
      />
    );
  }

  return (
    <div className="space-y-4">
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm text-muted">{t("display.chooseTv")}</legend>
        {paired.map((item) => (
          <label
            key={item.id}
            className="flex cursor-pointer items-center gap-2 rounded-md border border-border p-2.5 text-sm has-[:checked]:border-accent has-[:checked]:bg-accent/10"
          >
            <input
              type="radio"
              name="tv"
              checked={target.id === item.id}
              onChange={() => setPicked(item.id)}
              className="accent-[var(--color-accent)]"
            />
            <span className="flex-1">{item.name}</span>
            <span className="text-xs text-muted">{item.host}</span>
            {item.item_count > 0 && (
              <Badge>{t("display.itemCount", { count: item.item_count })}</Badge>
            )}
          </label>
        ))}
      </fieldset>

      <div className="rounded-md border border-border">
        <button
          type="button"
          aria-expanded={settingsOpen}
          onClick={() => setSettingsOpen((value) => !value)}
          className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-sm"
        >
          {settingsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span className="text-muted">{t("display.rotation")}</span>
          <span className="flex-1 text-right">{slideshowSummary(t, minutes, ordered)}</span>
        </button>
        {settingsOpen && (
          <div className="border-t border-border px-2.5 py-2.5">
            <SlideshowSettings
              minutes={minutes}
              ordered={ordered}
              onChange={(next) => setRotation((current) => ({ ...current, ...next }))}
            />
          </div>
        )}
      </div>

      <div className="space-y-2 text-xs" aria-live="polite">
        <p className="flex items-center gap-2 text-sm">
          {plan
            ? plan.set_count === 0
              ? t("display.planEmpty")
              : t("display.planSummary", {
                  count: plan.set_count,
                  upload: plan.to_upload,
                  there: plan.already_there,
                })
            : t("display.planLoading")}
          {checking && (
            <span className="flex items-center gap-1 text-xs text-muted">
              <Spinner size={12} /> {t("display.checkingTv")}
            </span>
          )}
        </p>

        {plan?.tv_error && !checking && (
          <p className="text-muted">
            {t("display.planOffline", { reason: messageForCode(t, plan.tv_error) })}
          </p>
        )}
        {plan?.moved_to && (
          <p className="text-muted">{t("display.planMoved", { host: plan.moved_to })}</p>
        )}

        {plan && plan.drafts > 0 && (
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={leaveOutDrafts}
              onChange={(event) => setDraftsChoice(event.target.checked)}
              className="mt-0.5"
            />
            <span>
              {t("display.leaveOutDrafts", { count: plan.drafts })}
              <span className="block text-muted">{t("display.leaveOutDraftsHint")}</span>
            </span>
          </label>
        )}

        {isStatic ? (
          <p className="flex items-start gap-2 rounded-md border border-info/40 bg-info/10 p-2.5">
            <Info size={14} className="mt-px shrink-0 text-info" />
            <span>
              {t("display.staticNote")}
              {plan &&
                plan.ours_left > 0 &&
                ` ${t("display.planOursLeft", { count: plan.ours_left })}`}
            </span>
          </p>
        ) : (
          <p className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2.5">
            <TriangleAlert size={14} className="mt-px shrink-0 text-warning" />
            <span>
              {keepOurs
                ? t("display.mirrorKeepWarning", { count: previous })
                : t("display.mirrorWarning")}
              {previous > 0 && !keepOurs && ` ${t("display.planOursRemoved", { count: previous })}`}
              {offerDelete && ` ${t("display.planForeignShown", { count: foreign })}`}
            </span>
          </p>
        )}

        {previous > 0 && (
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={removeOurs}
              onChange={(event) => setRemoveOurs(event.target.checked)}
              className="mt-0.5"
            />
            <span>
              {t("display.removeOursOption", { count: previous })}
              <span className="block text-muted">{t("display.removeOursHint")}</span>
            </span>
          </label>
        )}

        {offerDelete && (
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={deleteForeign}
              onChange={(event) => setDeleteForeign(event.target.checked)}
              className="mt-0.5"
            />
            <span>
              {t("display.deleteForeignOption", { count: foreign })}
              <span className="block text-muted">{t("display.deleteForeignHint")}</span>
            </span>
          </label>
        )}
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onDone}>
          {t("common.cancel")}
        </Button>
        <Button
          variant={offerDelete && deleteForeign ? "danger" : "primary"}
          disabled={busy || plan?.set_count === 0}
          onClick={send}
        >
          {busy ? <Spinner /> : <Cast size={14} />} {t("display.push")}
        </Button>
      </div>
    </div>
  );
}
