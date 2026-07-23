import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Dev: proxy /api -> FastAPI read-API (porta 8000) para evitar CORS no dev.
// Em produção, VITE_API_URL aponta para a API real (build estático separado do backend).
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // Permite acessar o dev server via túnel (cloudflared quick tunnel) para
    // compartilhar/testar. Wildcard de subdomínio cobre qualquer URL trycloudflare.
    allowedHosts: [".trycloudflare.com"],
    proxy: {
      // Dev (npm run dev): VITE_API_URL fica vazio e o front chama /api/v1/... ,
      // que este proxy encaminha para a API real. Same-origin no browser, então
      // não precisa de CORS. changeOrigin ajusta o Host (TLS/SNI + vhost); secure
      // valida o certificado do domínio.
      // VITE_PROXY_TARGET permite apontar para um backend local
      // (ex.: VITE_PROXY_TARGET=http://localhost:8000 npm run dev).
      "/api": {
        target: process.env.VITE_PROXY_TARGET || "https://api.arenarank.lol",
        changeOrigin: true,
        secure: !process.env.VITE_PROXY_TARGET,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
