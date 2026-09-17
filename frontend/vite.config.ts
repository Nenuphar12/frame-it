import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = process.env.THE_FRAME_V2_BACKEND ?? "http://127.0.0.1:8765";

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
    outDir: "../backend/src/the_frame_v2/static",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 800,
  },
});
