import { Cast, MonitorPlay, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DisplaySource } from "@/api/client";
import { useDisplayActions, useDisplayTargets } from "@/api/queries";
import { toast } from "@/shared/toast";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Badge, EmptyState, Spinner } from "@/shared/ui/Misc";

/**
 * "Show this on the TV": pick a TV, then push.
 *
 * The wording is deliberate. A push **mirrors** — the Frame's slideshow plays a whole category, so
 * everything else on the TV stops being shown (and is deleted, if the user says so). Saying that
 * here is the only warning the user gets before an irreversible delete (`docs/tv-display.md`).
 */
export function ShowOnTvDialog({
  open,
  onOpenChange,
  source,
  label,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** What to show: a collection, the current filter, or an explicit list of artworks. */
  source: Partial<DisplaySource>;
  label: string;
}) {
  const { t } = useTranslation();
  const targets = useDisplayTargets();
  const { setSource, push } = useDisplayActions();
  const list = targets.data?.targets ?? [];
  const ready = list.filter((target) => target.paired);
  const [picked, setPicked] = useState<string | null>(null);
  const [deleteForeign, setDeleteForeign] = useState(false);
  // Derived, not stored: the first paired TV is the default until one is chosen, so the list
  // arriving late does not need an effect to fix the selection.
  const targetId = picked ?? ready[0]?.id ?? null;

  const send = () => {
    if (!targetId) return;
    setSource.mutate(
      // `include_nested` and `sort` carry the server's defaults so callers pass only what varies.
      { id: targetId, include_nested: false, sort: "created_desc", ...source, label },
      {
        onSuccess: () =>
          push.mutate(
            { id: targetId, allowDeleteForeign: deleteForeign },
            {
              onSuccess: () => {
                toast.info("display.pushQueued");
                onOpenChange(false);
              },
            },
          ),
      },
    );
  };

  const busy = setSource.isPending || push.isPending;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("display.showOnTv")}
      description={t("display.showOnTvDescription", { name: label })}
    >
      {targets.isLoading ? (
        <Spinner />
      ) : ready.length === 0 ? (
        <EmptyState
          compact
          icon={<MonitorPlay size={24} />}
          title={t("display.noTvTitle")}
          description={t("display.noTvDescription")}
        />
      ) : (
        <div className="space-y-4">
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm text-muted">{t("display.chooseTv")}</legend>
            {ready.map((target) => (
              <label
                key={target.id}
                className="flex cursor-pointer items-center gap-2 rounded-md border border-border p-2.5 text-sm has-[:checked]:border-accent has-[:checked]:bg-accent/10"
              >
                <input
                  type="radio"
                  name="tv"
                  checked={targetId === target.id}
                  onChange={() => setPicked(target.id)}
                  className="accent-[var(--color-accent)]"
                />
                <span className="flex-1">{target.name}</span>
                <span className="text-xs text-muted">{target.host}</span>
                {target.item_count > 0 && (
                  <Badge>{t("display.itemCount", { count: target.item_count })}</Badge>
                )}
              </label>
            ))}
          </fieldset>

          <p className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2.5 text-xs">
            <TriangleAlert size={14} className="mt-px shrink-0 text-warning" />
            <span>{t("display.mirrorWarning")}</span>
          </p>

          <label className="flex items-start gap-2 text-xs">
            <input
              type="checkbox"
              checked={deleteForeign}
              onChange={(event) => setDeleteForeign(event.target.checked)}
              className="mt-0.5"
            />
            <span>
              {t("display.deleteForeignOption")}
              <span className="block text-muted">{t("display.deleteForeignHint")}</span>
            </span>
          </label>

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button variant="primary" disabled={!targetId || busy} onClick={send}>
              {busy ? <Spinner /> : <Cast size={14} />} {t("display.push")}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
