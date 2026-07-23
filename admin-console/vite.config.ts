import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Admin console dev server runs on 5174 (the player frontend uses 5173).
//
// Backend switching is done at RUNTIME inside the app (local / production /
// custom). The "local" preset talks to the API through this dev proxy using a
// relative `/api` path, so local development needs NO CORS change on the
// backend. The "production"/"custom" presets call their absolute URL directly
// (CORS is then governed by that backend).
//
// VITE_LOCAL_API_TARGET overrides the local proxy target (default :8000).
const LOCAL_TARGET = process.env.VITE_LOCAL_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": {
        target: LOCAL_TARGET,
        changeOrigin: true,
        // SSE / streaming responses must not be buffered by the proxy.
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            // Let event-streams flow through chunk-by-chunk.
            if ((proxyRes.headers["content-type"] || "").includes("text/event-stream")) {
              proxyRes.headers["cache-control"] = "no-cache, no-transform";
            }
          });
        },
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
