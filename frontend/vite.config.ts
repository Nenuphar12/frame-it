import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = process.env.FRAME_IT_BACKEND ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      // xfwd adds X-Forwarded-For so LAN devices using the dev server are NOT trusted as localhost.
      "/api": { target: backend, changeOrigin: false, xfwd: true, ws: false },
    },
  },
  build: {
    outDir: "../backend/src/frame_it/static",
    emptyOutDir: true,
    sourcemap: false,
    // The main chunk is ~1010 kB raw / ~318 kB gzip, half of it Konva + its React reconciler for
    // the editor. Served from the LAN under immutable hashed names, that is a few milliseconds, so
    // the editor route is deliberately *not* lazy yet: it would need a stale-chunk error boundary
    // (`emptyOutDir` removes the old chunks on rebuild) — see `docs/progress.md`. The limit sits
    // just above today's size so the warning still trips when a new dependency lands.
    chunkSizeWarningLimit: 1100,
  },
});
