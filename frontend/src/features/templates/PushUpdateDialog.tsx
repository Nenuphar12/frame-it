// Push update: before/after on the artworks a template made (docs/templates.md §5).
//
// The preview is a dry run on the server — the same walk as the real thing, applying nothing —
// so what it lists is exactly what the button will touch, including what it will skip and why.
// Applying snapshots every artwork first (`pre_template_update`), which is what makes it undoable.
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { artworkThumbUrl, type ArtworkSummary } from "@/api/client";
import { usePushUpdate, useTemplateUsage, type TemplateKind } from "@/api/queries";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { Badge, Spinner } from "@/shared/ui/Misc";

function Thumb({ artwork }: { artwork: ArtworkSummary }) {
  return (
    <div className="aspect-video overflow-hidden rounded border border-border bg-panel-2">
      {artwork.render_hash ? (
        <img src={artworkThumbUrl(artwork, 256)} alt="" className="h-full w-full object-cover" />
      ) : null}
    </div>
  );
}

export function PushUpdateDialog({
  kind,
  templateId,
  templateName,
  revision,
  open,
  onOpenChange,
}: {
  kind: TemplateKind;
  templateId: string;
  templateName: string;
  revision: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const usage = useTemplateUsage(kind, open ? templateId : null);
  const push = usePushUpdate();
  const preview = push.data?.dry_run ? push.data : null;

  useEffect(() => {
    if (open) push.mutate({ kind, id: templateId, dryRun: true });
    else push.reset();
    // The preview is fetched once per opening; `push` is a stable mutation object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, templateId, kind]);

  const applied = push.data && !push.data.dry_run ? push.data : null;
  const artworks = usage.data ?? [];
  const reasonOf = (id: string) => preview?.items.find((item) => item.artwork_id === id)?.reason;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("templates.pushUpdate")}
      description={t("templates.pushUpdateHint", { name: templateName })}
      className="w-[min(94vw,52rem)]"
    >
      <div className="flex flex-col gap-3">
        {usage.isLoading && <Spinner />}
        {artworks.length === 0 && !usage.isLoading && (
          <p className="text-sm text-muted">{t("templates.noUsage")}</p>
        )}
        {artworks.length > 0 && (
          <div className="max-h-80 overflow-y-auto">
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {artworks.map((artwork) => {
                const reason = reasonOf(artwork.id);
                const stale =
                  kind === "frame_style"
                    ? (artwork.origin_style_revision ?? revision) < revision
                    : (artwork.origin_layout_revision ?? revision) < revision;
                return (
                  <li key={artwork.id} className="flex flex-col gap-1">
                    <Thumb artwork={artwork} />
                    <span className="truncate text-xs">{artwork.title || artwork.id}</span>
                    <span className="flex flex-wrap gap-1">
                      {reason ? (
                        <Badge tone="warning">{t(`templates.skipped.${reason}`)}</Badge>
                      ) : (
                        <Badge tone={stale ? "accent" : "neutral"}>
                          {stale ? t("templates.outdated") : t("templates.upToDate")}
                        </Badge>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {preview && (
          <p className="text-xs text-muted">
            {t("templates.pushSummary", { applied: preview.applied, skipped: preview.skipped })}
          </p>
        )}
        {applied && (
          <p className="text-sm text-accent">
            {t("templates.pushDone", { count: applied.applied })}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common.close")}
          </Button>
          <Button
            variant="primary"
            disabled={push.isPending || !preview || preview.applied === 0}
            onClick={() => push.mutate({ kind, id: templateId, dryRun: false })}
          >
            {push.isPending && <Spinner size={14} />}
            {t("templates.applyToAll", { count: preview?.applied ?? 0 })}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
