import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Frame, KeyRound, Smartphone } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api, unwrap } from "@/api/client";
import { queryKeys } from "@/api/queries";
import { Button } from "@/shared/ui/Button";

function Centered({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="w-full max-w-sm space-y-5 rounded-2xl border border-border bg-panel p-6 shadow-xl">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-accent/15 p-2 text-accent">{icon}</div>
          <h1 className="text-lg font-semibold">{title}</h1>
        </div>
        {children}
      </div>
    </div>
  );
}

function defaultDeviceName(t: (key: string) => string): string {
  return t(
    /Android/i.test(navigator.userAgent) ? "auth.defaultPhoneName" : "auth.defaultBrowserName",
  );
}

function useRedeem(kind: "setup" | "pair") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { code: string; device_name: string }) =>
      unwrap(
        kind === "setup"
          ? api.POST("/api/v1/auth/setup", { body })
          : api.POST("/api/v1/auth/pair", { body }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.me }),
  });
}

function CodeForm({
  kind,
  initialCode = "",
  autoSubmit = false,
}: {
  kind: "setup" | "pair";
  initialCode?: string;
  autoSubmit?: boolean;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const redeem = useRedeem(kind);
  const [code, setCode] = useState(initialCode);
  const [name, setName] = useState(() => defaultDeviceName(t));
  const submitted = useRef(false);

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    redeem.mutate(
      { code, device_name: name },
      {
        onSuccess: (device) =>
          void navigate({ to: device.role === "admin" ? "/inbox" : "/m", replace: true }),
      },
    );
  };

  useEffect(() => {
    if (autoSubmit && initialCode && !submitted.current) {
      submitted.current = true;
      submit();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once for QR links
  }, []);

  const error =
    redeem.error instanceof ApiError ? redeem.error.code : redeem.error ? "unknown" : null;

  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block space-y-1">
        <span className="text-sm text-muted">{t("auth.code")}</span>
        <input
          value={code}
          onChange={(event) => setCode(event.target.value)}
          autoCapitalize="characters"
          autoComplete="one-time-code"
          placeholder="XXXXX-XXXXX"
          className="w-full rounded-md border border-border bg-bg px-3 py-2 font-mono tracking-widest uppercase outline-none focus:border-accent"
        />
      </label>
      <label className="block space-y-1">
        <span className="text-sm text-muted">{t("auth.deviceName")}</span>
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={128}
          className="w-full rounded-md border border-border bg-bg px-3 py-2 outline-none focus:border-accent"
        />
      </label>
      {error && (
        <p className="text-sm text-danger" role="alert">
          {t(`errors.${error}`, { defaultValue: t("errors.unknown") })}
        </p>
      )}
      <Button
        type="submit"
        variant="primary"
        size="lg"
        className="w-full"
        disabled={redeem.isPending || code.replace(/[^0-9a-z]/gi, "").length < 10}
      >
        {t(kind === "setup" ? "auth.setupSubmit" : "auth.pairSubmit")}
      </Button>
    </form>
  );
}

export function SetupPage() {
  const { t } = useTranslation();
  return (
    <Centered icon={<KeyRound size={20} />} title={t("auth.setupTitle")}>
      <p className="text-sm text-muted">{t("auth.setupDescription")}</p>
      <CodeForm kind="setup" />
    </Centered>
  );
}

export function PairPage() {
  const { t } = useTranslation();
  const code = new URLSearchParams(window.location.hash.slice(1)).get("code") ?? "";
  useEffect(() => {
    // Remove the secret from the address bar/history once read.
    if (code) history.replaceState(null, "", window.location.pathname);
  }, [code]);
  return (
    <Centered icon={<Smartphone size={20} />} title={t("auth.pairTitle")}>
      <p className="text-sm text-muted">{t("auth.pairDescription")}</p>
      <CodeForm kind="pair" initialCode={code} autoSubmit={Boolean(code)} />
    </Centered>
  );
}

export function NotPairedPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <Centered icon={<Frame size={20} />} title={t("auth.notPairedTitle")}>
      <p className="text-sm text-muted">{t("auth.notPairedDescription")}</p>
      <div className="flex flex-col gap-2">
        <Button variant="primary" onClick={() => void navigate({ to: "/pair" })}>
          {t("auth.enterPairingCode")}
        </Button>
        <Button variant="ghost" onClick={() => void navigate({ to: "/setup" })}>
          {t("auth.enterSetupCode")}
        </Button>
      </div>
    </Centered>
  );
}
