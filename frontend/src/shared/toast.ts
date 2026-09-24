/**
 * Toasts: the one place a failure the user did not ask about gets said out loud.
 *
 * The store lives outside React (like the upload queue) so anything can raise one — a mutation's
 * `onError`, an SSE `job.failed`, a keyboard action — without a hook or a provider. A toast
 * carries a **problem code**, not a sentence: the component translates `errors.<code>`, so the
 * same failure reads the same wherever it is raised (invariant 7).
 */
import { create } from "zustand";

import { ApiError } from "@/api/client";

export type ToastTone = "error" | "success" | "info";

export interface ToastAction {
  /** i18n key for the button. */
  label: string;
  run: () => void;
}

export interface Toast {
  id: number;
  tone: ToastTone;
  /** i18n key for the headline (`toast.*`), or undefined to use the problem code alone. */
  title?: string;
  /** Problem code: rendered through `errors.<code>` with `detail` as the fallback. */
  code?: string;
  /** Server-supplied text, shown when no `errors.<code>` string exists. */
  detail?: string;
  action?: ToastAction;
  /** Milliseconds before it fades; 0 keeps it until dismissed. */
  timeout: number;
}

interface ToastState {
  toasts: Toast[];
  push: (toast: Omit<Toast, "id" | "timeout"> & { timeout?: number }) => number;
  dismiss: (id: number) => void;
}

/** Errors stay until dismissed; anything else goes on its own. */
const DEFAULT_TIMEOUT: Record<ToastTone, number> = { error: 0, success: 4000, info: 6000 };
/** Older toasts are dropped rather than stacked off-screen (a failing batch raises one each). */
const MAX_VISIBLE = 4;

let nextId = 1;

export const useToasts = create<ToastState>((set) => ({
  toasts: [],
  push(toast) {
    const id = nextId++;
    const timeout = toast.timeout ?? DEFAULT_TIMEOUT[toast.tone];
    set((state) => ({ toasts: [...state.toasts, { ...toast, id, timeout }].slice(-MAX_VISIBLE) }));
    return id;
  },
  dismiss(id) {
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) }));
  },
}));

/** Raise a toast from anywhere, including outside React. */
export const toast = {
  error(error: unknown, title?: string, action?: ToastAction) {
    const problem =
      error instanceof ApiError
        ? { code: error.code, detail: error.problem.detail ?? error.problem.title }
        : { code: "unknown", detail: error instanceof Error ? error.message : undefined };
    return useToasts.getState().push({ tone: "error", title, action, ...problem });
  },
  /** A failure whose code is already known (an SSE event, an upload item). */
  problem(code: string | undefined, title?: string, action?: ToastAction) {
    return useToasts.getState().push({ tone: "error", code, title, action });
  },
  success(title: string, action?: ToastAction) {
    return useToasts.getState().push({ tone: "success", title, action });
  },
  info(title: string, action?: ToastAction) {
    return useToasts.getState().push({ tone: "info", title, action });
  },
  dismiss(id: number) {
    useToasts.getState().dismiss(id);
  },
};

declare module "@tanstack/react-query" {
  interface Register {
    /** `silentError`: this mutation renders its own failure; the global toast stands down. */
    mutationMeta: { silentError?: boolean };
  }
}
