import React from "react";
import { createRoot } from "react-dom/client";
import "./styles/globals.css";

async function render(): Promise<void> {
  const surface = new URLSearchParams(window.location.search).get("surface");
  if (surface) document.documentElement.dataset.obsidienceSurface = surface;
  const Component = surface === "knowledge"
    ? (await import("./surfaces/knowledge-desktop")).KnowledgeDesktopSurface
    : (await import("./App")).default;

  createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <Component />
    </React.StrictMode>,
  );
}

void render();
