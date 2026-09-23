import * as RadixDialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/shared/cn";

type DialogSize = "default" | "full";

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
  /**
   * `full` fills the window (a small gutter aside) and makes the body a flex column, for dialogs
   * whose point is a preview you have to actually see — editing a template (docs/templates.md §7).
   */
  size?: DialogSize;
  /**
   * Focus put on open. Radix otherwise focuses the first tabbable element, which is the close
   * cross: `Enter` on a freshly opened dialog then *cancels* it instead of confirming.
   */
  onOpenAutoFocus?: (event: Event) => void;
}

const sizes: Record<DialogSize, string> = {
  default: "top-1/2 left-1/2 w-[min(92vw,32rem)] -translate-x-1/2 -translate-y-1/2",
  full: "inset-3 flex flex-col overflow-hidden md:inset-6",
};

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
  size = "default",
  onOpenAutoFocus,
}: DialogProps) {
  const { t } = useTranslation();
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px]" />
        <RadixDialog.Content
          // `Escape` closes the dialog and nothing else: Radix handles it in the capture phase on
          // the document, the command registry listens on `window` (bubble) — see ColorField.
          onEscapeKeyDown={(event) => event.stopPropagation()}
          onOpenAutoFocus={onOpenAutoFocus}
          className={cn(
            "fixed z-50 rounded-xl border border-border bg-panel p-5 shadow-2xl",
            sizes[size],
            className,
          )}
        >
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <RadixDialog.Title className="text-base font-semibold">{title}</RadixDialog.Title>
              {description ? (
                <RadixDialog.Description className="mt-1 text-sm text-muted">
                  {description}
                </RadixDialog.Description>
              ) : (
                <RadixDialog.Description className="sr-only">{title}</RadixDialog.Description>
              )}
            </div>
            <RadixDialog.Close
              className="rounded p-1 text-muted hover:bg-panel-2 hover:text-text"
              aria-label={t("common.close")}
            >
              <X size={16} />
            </RadixDialog.Close>
          </div>
          {size === "full" ? (
            <div className="flex min-h-0 flex-1 flex-col">{children}</div>
          ) : (
            children
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
