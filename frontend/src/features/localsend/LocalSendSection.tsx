import { Ban, Check, Send, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { LocalSendDevice } from "@/api/client";
import { useLocalSendDeviceActions, useLocalSendDevices, useLocalSendStatus } from "@/api/queries";
import { formatRelative } from "@/shared/format";
import { Button } from "@/shared/ui/Button";
import { Badge, Spinner } from "@/shared/ui/Misc";

const STATUS_TONE = { approved: "accent", pending: "warning", blocked: "danger" } as const;

function DeviceRow({ device }: { device: LocalSendDevice }) {
  const { t } = useTranslation();
  const { setStatus, forget } = useLocalSendDeviceActions();
  return (
    <li className="flex flex-wrap items-center gap-3 px-4 py-3">
      <Send size={18} className="text-muted" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">
          {device.alias}
          {device.device_model && <span className="text-muted"> · {device.device_model}</span>}
        </div>
        <div className="text-xs text-muted">
          {t("devices.lastSeen", { time: formatRelative(device.last_seen_at) })}
          {device.last_ip && ` · ${device.last_ip}`}
        </div>
      </div>
      <Badge tone={STATUS_TONE[device.status]}>{t(`localsend.status.${device.status}`)}</Badge>
      {device.status !== "approved" && (
        <Button size="sm" onClick={() => setStatus.mutate({ id: device.id, status: "approved" })}>
          <Check size={14} /> {t("localsend.allow")}
        </Button>
      )}
      {device.status !== "blocked" && (
        <Button size="sm" onClick={() => setStatus.mutate({ id: device.id, status: "blocked" })}>
          <Ban size={14} /> {t("localsend.block")}
        </Button>
      )}
      <Button
        variant="danger"
        size="sm"
        onClick={() => {
          if (window.confirm(t("localsend.forgetConfirm", { name: device.alias })))
            forget.mutate(device.id);
        }}
      >
        <Trash2 size={14} /> {t("localsend.forget")}
      </Button>
    </li>
  );
}

/** LocalSend receiver status and the devices that sent (or tried to send) photos with it. */
export function LocalSendSection() {
  const { t } = useTranslation();
  const status = useLocalSendStatus();
  const devices = useLocalSendDevices();
  const info = status.data;

  return (
    <section className="mt-8 space-y-3">
      <div>
        <h2 className="text-sm font-semibold">{t("localsend.title")}</h2>
        <p className="text-sm text-muted">{t("localsend.subtitle")}</p>
      </div>
      {info && (
        <div className="space-y-1 rounded-lg border border-border bg-panel p-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={info.running ? "accent" : info.enabled ? "danger" : "neutral"}>
              {t(
                info.running
                  ? "localsend.running"
                  : info.enabled
                    ? "localsend.notRunning"
                    : "localsend.disabled",
              )}
            </Badge>
            <span className="font-medium">{info.alias}</span>
            <span className="text-muted">
              {t("localsend.port", { port: info.port })}
              {info.running && !info.discovery && ` · ${t("localsend.noDiscovery")}`}
            </span>
          </div>
          {info.error && <p className="text-danger">{info.error}</p>}
          {info.fingerprint && (
            <p className="text-xs break-all text-muted">
              {t("localsend.fingerprint")}: <span className="font-mono">{info.fingerprint}</span>
            </p>
          )}
          {info.running && <p className="text-xs text-muted">{t("localsend.howTo")}</p>}
        </div>
      )}
      {devices.isLoading ? (
        <Spinner />
      ) : (devices.data ?? []).length === 0 ? (
        <p className="text-sm text-muted">{t("localsend.empty")}</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-panel">
          {devices.data?.map((device) => (
            <DeviceRow key={device.id} device={device} />
          ))}
        </ul>
      )}
    </section>
  );
}
