import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

// The Harness serves out/renderer at /shell/knowledge/. These are the
// renderer settings electron-vite applied before the Electron app retired.
export default defineConfig({
  root: resolve(__dirname, "src/renderer"),
  base: "./",
  envPrefix: ["RENDERER_VITE_", "VITE_"],
  resolve: { alias: { "@": resolve(__dirname, "src/renderer/src") } },
  plugins: [react(), tailwindcss()],
  build: {
    outDir: resolve(__dirname, "out/renderer"),
    emptyOutDir: true,
    target: "chrome108",
    modulePreload: { polyfill: false },
    reportCompressedSize: false,
    minify: false,
  },
});
