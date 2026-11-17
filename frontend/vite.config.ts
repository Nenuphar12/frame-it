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
    // The main chunk is ~880 kB raw / ~270 kB gzip; the editor (Konva + its React reconciler) is
    // its own ~480 kB chunk, loaded by its route (`lazyRouteComponent`, which reloads the page
    // once when a rebuild removed the chunk an open tab asks for). The server gzips `/assets` and
    // marks it immutable. The limit sits just above today's size so the warning still trips when a
    // new dependency lands.
    chunkSizeWarningLimit: 950,
  },
});
