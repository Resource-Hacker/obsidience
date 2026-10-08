import React from "react";
import { createRoot } from "react-dom/client";
import "./styles/globals.css";

async function render(): Promise<void> {
  const surface = new URLSearchParams(window.location.search).get("surface");
  if (surface) document.documentElement.dataset.obsidienceSurface = surface;
  // Every Shell page names its surface.
  const Component = surface === "knowledge"
    ? (await import("./surfaces/knowledge-desktop")).KnowledgeDesktopSurface
    : surface === "stage"
    ? (await import("./surfaces/graph-stage")).GraphStage
    : surface === "graph"
    ? (await import("./surfaces/graph-viewer")).GraphPaneSurface
    : surface === "memory" || surface === "code"
    ? (await import("./surfaces/provider-graph")).ProviderGraphSurface
    : null;
  if (!Component) {
    console.warn("Unknown Obsidience surface:", surface);
    return;
  }

  createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <Component />
    </React.StrictMode>,
  );
}

void render();
