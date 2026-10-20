import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

// The Harness serves out/renderer at /shell/knowledge/.
export default defineConfig({
  root: resolve(import.meta.dirname, "src/renderer"),
  base: "./",
  resolve: { alias: { "@": resolve(import.meta.dirname, "src/renderer/src") } },
  plugins: [react(), tailwindcss()],
  build: {
    outDir: resolve(import.meta.dirname, "out/renderer"),
    emptyOutDir: true,
    target: "chrome108",
    modulePreload: { polyfill: false },
    reportCompressedSize: false,
    minify: false,
  },
});
