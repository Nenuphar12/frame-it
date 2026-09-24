import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/shared/cn";
import { messageForCode } from "@/shared/problem";
import { useToasts, type Toast, type ToastTone } from "@/shared/toast";

const tones: Record<ToastTone, { ring: string; icon: typeof Info }> = {
  error: { ring: "border-danger/40 bg-danger/10", icon: AlertCircle },
  success: { ring: "border-accent/40 bg-accent/10", icon: CheckCircle2 },
  info: { ring: "border-info/40 bg-info/10", icon: Info },
};

function ToastCard({ toast }: { toast: Toast }) {
  const { t } = useTranslation();
  const dismiss = useToasts((s) => s.dismiss);
  const { ring, icon: Icon } = tones[toast.tone];

  useEffect(() => {
    if (toast.timeout <= 0) return;
    const timer = window.setTimeout(() => dismiss(toast.id), toast.timeout);
    return () => window.clearTimeout(timer);
  }, [dismiss, toast.id, toast.timeout]);

  const title = toast.title ? t(toast.title) : undefined;
  const body = toast.code ? messageForCode(t, toast.code, toast.detail) : toast.detail;

  return (
    <div
      className={cn(
        "pointer-events-auto flex w-80 items-start gap-2.5 rounded-lg border p-3 shadow-lg",
        "bg-panel/95 backdrop-blur",
        ring,
      )}
    >
      <Icon
        size={16}
        className={cn(
          "mt-px shrink-0",
          toast.tone === "error" ? "text-danger" : toast.tone === "success" ? "text-accent" : "text-info",
        )}
        aria-hidden
      />
      <div className="min-w-0 flex-1 space-y-1">
        {title && <p className="text-sm font-medium">{title}</p>}
        {body && <p className={cn("text-xs break-words", title ? "text-muted" : "text-text")}>{body}</p>}
        {toast.action && (
          <button
            onClick={() => {
              toast.action?.run();
              dismiss(toast.id);
            }}
            className="text-xs font-medium text-accent underline-offset-2 hover:underline"
          >
            {t(toast.action.label)}
          </button>
        )}
      </div>
      <button
        onClick={() => dismiss(toast.id)}
        aria-label={t("common.dismiss")}
        className="shrink-0 rounded p-0.5 text-muted hover:bg-panel-2 hover:text-text"
      >
        <X size={14} />
      </button>
    </div>
  );
}

/**
 * Bottom-left, above the upload tray's corner. `role="status"` + `aria-live="polite"` so a
 * failure raised by a background job is announced rather than only drawn (phase 11, §14.2).
 */
export function Toaster() {
  const toasts = useToasts((s) => s.toasts);
  return (
    <div
      role="status"
      aria-live="polite"
      aria-relevant="additions text"
      className="pointer-events-none fixed bottom-4 left-4 z-50 flex flex-col gap-2"
    >
      {toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} />
      ))}
    </div>
  );
}
