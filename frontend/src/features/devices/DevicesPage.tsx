import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Laptop, QrCode, Smartphone, Trash2 } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, unwrap, type Device } from "@/api/client";
import { queryKeys, useDevices, useMe } from "@/api/queries";
import { formatRelative } from "@/shared/format";
import { Button } from "@/shared/ui/Button";
import { Dialog } from "@/shared/ui/Dialog";
import { LocalSendSection } from "@/features/localsend/LocalSendSection";
import { Badge, EmptyState, PageHeader, Spinner } from "@/shared/ui/Misc";

type Role = Device["role"];

function PairDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const [role, setRole] = useState<Role>("uploader");
  const [qr, setQr] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const devices = useDevices(open ? 2000 : false);
  const [initialCount, setInitialCount] = useState<number | null>(null);
  const create = useMutation({
    mutationFn: (r: Role) =>
      unwrap(api.POST("/api/v1/devices/pairing-codes", { body: { role: r } })),
    onSuccess: async (data) => {
      setQr(await QRCode.toDataURL(data.url, { margin: 1, width: 320 }));
      setRemaining(data.expires_in_seconds);
      setInitialCount(devices.data?.length ?? 0);
    },
  });

  useEffect(() => {
    if (!create.data) return;
    const timer = setInterval(() => setRemaining((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(timer);
  }, [create.data]);

  const paired = initialCount !== null && (devices.data?.length ?? 0) > initialCount;

  const reset = (next: boolean) => {
    if (!next) {
      create.reset();
      setQr(null);
      setInitialCount(null);
    }
    onOpenChange(next);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={reset}
      title={t("devices.pairTitle")}
      description={t("devices.pairDescription")}
    >
      {paired ? (
        <div className="space-y-4 text-center">
          <p className="text-accent">{t("devices.pairSuccess")}</p>
          <Button variant="primary" onClick={() => reset(false)}>
            {t("common.done")}
          </Button>
        </div>
      ) : !create.data ? (
        <div className="space-y-4">
          <fieldset className="grid grid-cols-2 gap-2">
            <legend className="mb-2 text-sm text-muted">{t("devices.roleQuestion")}</legend>
            {(["uploader", "admin"] as const).map((r) => (
              <label
                key={r}
                className="flex cursor-pointer flex-col gap-1 rounded-md border border-border p-3 has-[:checked]:border-accent has-[:checked]:bg-accent/10"
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  <input
                    type="radio"
                    name="role"
                    checked={role === r}
                    onChange={() => setRole(r)}
                    className="accent-[var(--color-accent)]"
                  />
                  {t(`devices.roles.${r}`)}
                </span>
                <span className="text-xs text-muted">{t(`devices.roleHints.${r}`)}</span>
              </label>
            ))}
          </fieldset>
          <Button
            variant="primary"
            className="w-full"
            onClick={() => create.mutate(role)}
            disabled={create.isPending}
          >
            <QrCode size={16} /> {t("devices.generate")}
          </Button>
        </div>
      ) : (
        <div className="space-y-3 text-center">
          {qr && (
            <img src={qr} alt={t("devices.qrAlt")} className="mx-auto rounded-lg bg-white p-2" />
          )}
          <p className="text-sm text-muted">{t("devices.scanHint")}</p>
          <p className="font-mono text-lg tracking-widest">{create.data.code}</p>
          <p className="text-xs break-all text-muted">{create.data.url}</p>
          <p className="text-xs text-muted">
            {remaining > 0
              ? t("devices.expiresIn", {
                  time: `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}`,
                })
              : t("devices.expired")}
          </p>
          {remaining === 0 && (
            <Button onClick={() => create.mutate(role)}>{t("devices.regenerate")}</Button>
          )}
        </div>
      )}
    </Dialog>
  );
}

export function DevicesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const me = useMe();
  const devices = useDevices();
  const [pairing, setPairing] = useState(false);
  const invalidate = () => void qc.invalidateQueries({ queryKey: queryKeys.devices });

  const update = useMutation({
    mutationFn: (vars: { id: string; name?: string; role?: Role }) =>
      unwrap(
        api.PATCH("/api/v1/devices/{device_id}", {
          params: { path: { device_id: vars.id } },
          body: { name: vars.name ?? null, role: vars.role ?? null },
        }),
      ),
    onSuccess: invalidate,
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/v1/devices/{device_id}", { params: { path: { device_id: id } } })),
    onSuccess: invalidate,
  });

  const sorted = useMemo(
    () => [...(devices.data ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [devices.data],
  );

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("nav.devices")}
        subtitle={t("devices.subtitle")}
        actions={
          <Button variant="primary" onClick={() => setPairing(true)}>
            <QrCode size={16} /> {t("devices.pair")}
          </Button>
        }
      />
      <div className="flex-1 overflow-y-auto p-5">
        {me.data?.via === "localhost" && (
          <p className="mb-4 rounded-md border border-border bg-panel p-3 text-sm text-muted">
            {t("devices.localhostNote")}
          </p>
        )}
        {devices.isLoading ? (
          <Spinner />
        ) : sorted.length === 0 ? (
          <EmptyState
            icon={<Smartphone size={40} />}
            title={t("devices.emptyTitle")}
            description={t("devices.emptyDescription")}
            compact
          />
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border bg-panel">
            {sorted.map((device) => {
              const isSelf = device.id === me.data?.device_id;
              const isMobile = /Android|Mobile/i.test(device.user_agent);
              return (
                <li key={device.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  {isMobile ? (
                    <Smartphone size={18} className="text-muted" />
                  ) : (
                    <Laptop size={18} className="text-muted" />
                  )}
                  <div className="min-w-0 flex-1">
                    <input
                      defaultValue={device.name}
                      aria-label={t("devices.name")}
                      onBlur={(event) => {
                        const name = event.target.value.trim();
                        if (name && name !== device.name) update.mutate({ id: device.id, name });
                      }}
                      className="w-full rounded bg-transparent px-1 text-sm font-medium outline-none hover:bg-panel-2 focus:bg-panel-2"
                    />
                    <div className="px-1 text-xs text-muted">
                      {t("devices.lastSeen", { time: formatRelative(device.last_seen_at) })}
                      {isSelf && (
                        <Badge tone="accent" className="ml-2">
                          {t("devices.thisDevice")}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <select
                    value={device.role}
                    disabled={isSelf}
                    onChange={(event) =>
                      update.mutate({ id: device.id, role: event.target.value as Role })
                    }
                    className="rounded-md border border-border bg-bg px-2 py-1 text-sm"
                    aria-label={t("devices.role")}
                  >
                    <option value="uploader">{t("devices.roles.uploader")}</option>
                    <option value="admin">{t("devices.roles.admin")}</option>
                  </select>
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={isSelf}
                    onClick={() => {
                      if (window.confirm(t("devices.revokeConfirm", { name: device.name })))
                        revoke.mutate(device.id);
                    }}
                  >
                    <Trash2 size={14} /> {t("devices.revoke")}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
        <LocalSendSection />
      </div>
      <PairDialog open={pairing} onOpenChange={setPairing} />
    </div>
  );
}
