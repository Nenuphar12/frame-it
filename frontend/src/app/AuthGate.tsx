import { Navigate, Outlet, useRouterState } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { useServerEvents } from "@/api/events";
import { useMe } from "@/api/queries";
import { NotPairedPage } from "@/features/auth/AuthPages";
import { Button } from "@/shared/ui/Button";
import { Spinner } from "@/shared/ui/Misc";

const PUBLIC_PATHS = new Set(["/pair", "/setup"]);
const UPLOADER_PATHS = new Set(["/m", "/pair"]);

/** Routes users by authentication state and role before rendering pages. */
export function AuthGate() {
  const { t } = useTranslation();
  const me = useMe();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  useServerEvents(Boolean(me.data?.authenticated));

  if (me.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={24} />
      </div>
    );
  }
  if (me.isError || !me.data) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-muted">{t("errors.serverUnreachable")}</p>
        <Button onClick={() => void me.refetch()}>{t("common.retry")}</Button>
      </div>
    );
  }
  const { authenticated, role, setup_required } = me.data;
  if (!authenticated) {
    if (PUBLIC_PATHS.has(pathname)) return <Outlet />;
    return setup_required ? <Navigate to="/setup" replace /> : <NotPairedPage />;
  }
  if (pathname === "/setup") return <Navigate to={role === "admin" ? "/inbox" : "/m"} replace />;
  if (role === "uploader" && !UPLOADER_PATHS.has(pathname)) return <Navigate to="/m" replace />;
  return <Outlet />;
}
