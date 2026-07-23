import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Testes co-localizados (*.test.ts/tsx) rodam no ambiente jsdom (DOM para os
// testes de componente). `globals: false` → cada teste importa de "vitest".
// `css: false` → imports de .css viram no-op (sem parse de CSS no jsdom).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: false,
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
