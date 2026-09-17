import { Send } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useLocalSendDecision, useLocalSendRequests, useMe } from "@/api/queries";
import { formatBytes } from "@/shared/format";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";

/** Asks an admin whether an unknown LocalSend device may send photos (the sender waits meanwhile). */
export function LocalSendRequestDialog() {
  const { t } = useTranslation();
  const me = useMe();
  const isAdmin = me.data?.role === "admin";
  const requests = useLocalSendRequests(isAdmin);
  const decide = useLocalSendDecision();
  const request = requests.data?.[0];
  if (!isAdmin || !request) return null;

  const answer = (approve: boolean) => decide.mutate({ id: request.id, approve });
  const device = request.device_model
    ? `${request.alias} (${request.device_model})`
    : request.alias;

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && answer(false)}
      title={t("localsend.requestTitle", { device: request.alias })}
      description={t("localsend.requestDescription")}
    >
      <div className="space-y-4">
        <div className="flex items-center gap-3 rounded-md border border-border bg-bg p-3">
          <Send size={20} className="text-accent" />
          <div className="min-w-0 text-sm">
            <div className="truncate font-medium">{device}</div>
            <div className="text-muted">
              {t("localsend.requestFiles", {
                count: request.file_count,
                size: formatBytes(request.total_bytes),
              })}
              {request.known_count > 0 &&
                ` (${t("localsend.requestKnown", { count: request.known_count })})`}{" "}
              · {request.ip}
            </div>
          </div>
        </div>
        <p className="text-xs text-muted">{t("localsend.requestHint")}</p>
        {(requests.data?.length ?? 0) > 1 && (
          <p className="text-xs text-muted">
            {t("localsend.moreRequests", { count: (requests.data?.length ?? 1) - 1 })}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={() => answer(false)} disabled={decide.isPending}>
            {t("localsend.decline")}
          </Button>
          <Button variant="primary" onClick={() => answer(true)} disabled={decide.isPending}>
            {t("localsend.allow")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
