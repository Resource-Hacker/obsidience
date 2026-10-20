import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

// The public interactive demo (demo/): the real graph surfaces on static data,
// built into out/demo. The shell's own build (vite.config.ts) is unchanged.
export default defineConfig({
  root: resolve(import.meta.dirname, "demo"),
  base: "./",
  publicDir: resolve(import.meta.dirname, "demo/public"),
  resolve: {
    alias: [
      // Stage publishers also report their selection to the demo chrome.
      { find: "@/graph/stream", replacement: resolve(import.meta.dirname, "demo/src/stream.ts") },
      { find: "@", replacement: resolve(import.meta.dirname, "src/renderer/src") },
    ],
  },
  plugins: [react(), tailwindcss()],
  build: {
    outDir: resolve(import.meta.dirname, "out/demo"),
    emptyOutDir: true,
    target: "chrome108",
    modulePreload: { polyfill: false },
    reportCompressedSize: false,
  },
});
