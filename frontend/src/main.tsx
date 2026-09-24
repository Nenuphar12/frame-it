import "./styles.css";
import "./i18n";

import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { ApiError } from "./api/client";
import { router } from "./app/router";
import { initTheme } from "./app/theme";
import { toast } from "./shared/toast";

initTheme();

/**
 * Every mutation that fails says so (§14.3). A page that renders the failure itself — a dialog
 * with a red line under its form — opts out with `meta: { silentError: true }`, so the same
 * problem is never reported twice.
 */
const mutationCache = new MutationCache({
  onError: (error, _variables, _context, mutation) => {
    if (mutation.options.meta?.silentError) return;
    toast.error(error);
  },
});

const queryClient = new QueryClient({
  mutationCache,
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
