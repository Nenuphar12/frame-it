import { Link, useNavigate } from "@tanstack/react-router";
import { Cast } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { useDisplayTargets } from "@/api/queries";
import { useToasts } from "@/shared/toast";

import { livePush, pushFraction, usePushes, watchPushes } from "./pushStore";
import { phaseLabel, pushSummary } from "./summary";

/**
 * Pushes to a TV take minutes (4–6 s per image on the Frame), so they are shown wherever the user
 * is: a line per TV in the sidebar, and a summary toast when one ends. A failure is said by the
 * activity centre's toast (`job.failed`), which already names the reason.
 */
export function PushTray() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const targets = useDisplayTargets();
  const state = usePushes();

  useEffect(
    () =>
      watchPushes((result) => {
        const warn = result.foreign_remaining > 0 || Boolean(result.moved_to);
        useToasts.getState().push({
          tone: warn ? "info" : "success",
          title: "display.pushDone",
          detail: pushSummary(t, result),
          action: { label: "display.viewTv", run: () => void navigate({ to: "/display" }) },
          // Something the user should act on stays until dismissed.
          ...(warn ? { timeout: 0 } : {}),
        });
      }),
    [navigate, t],
  );

  const running = (targets.data?.targets ?? []).flatMap((target) => {
    const progress = livePush(target, state);
    return progress ? [{ target, progress }] : [];
  });
  if (running.length === 0) return null;

  return (
    <div className="space-y-1.5" aria-live="polite">
      {running.map(({ target, progress }) => (
        <Link
          key={target.id}
          to="/display"
          className="block rounded-md border border-border bg-bg px-2.5 py-2 text-xs hover:border-border-strong"
        >
          <span className="flex items-center gap-1.5 font-medium">
            <Cast size={13} className="shrink-0 text-accent" />
            <span className="truncate">{target.name}</span>
          </span>
          <span className="mt-0.5 block text-muted">{phaseLabel(t, progress)}</span>
          <span className="mt-1 block h-1 overflow-hidden rounded bg-panel-2">
            <span
              className="block h-full bg-accent transition-[width]"
              style={{ width: `${Math.round(pushFraction(progress) * 100)}%` }}
            />
          </span>
        </Link>
      ))}
    </div>
  );
}
