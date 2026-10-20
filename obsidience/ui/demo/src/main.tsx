// The stand-in Harness must replace fetch and WebSocket before any app module runs.
import { dataJson } from "./runtime";
import React from "react";
import { createRoot } from "react-dom/client";
import "./demo.css";
import { Tour, type TourData } from "./tour";
import { DemoApp } from "./demo-app";

/** Hold the tour and the renderers while the page is scrolled well out of view
 *  (also inside an iframe: the implicit root is the top-level viewport). */
function followViewport(tour: Tour): void {
  const root = document.documentElement;
  const show = (visible: boolean) => {
    root.dataset.paneVisible = String(visible);
    window.dispatchEvent(new Event("obsidience-pane-visibility"));
    tour.setVisible(visible && !document.hidden);
  };
  new IntersectionObserver(entries => show(entries.at(-1)!.isIntersecting), { rootMargin: "200px" })
    .observe(document.body);
  document.addEventListener("visibilitychange", () => tour.setVisible(root.dataset.paneVisible !== "false" && !document.hidden));
}

/** Embedded in a page, a plain wheel over the graph scrolls the page; Ctrl or
 *  ⌘ with the wheel (and trackpad pinches, which arrive that way) zooms. */
function wheelScrollsPage(): void {
  window.addEventListener("wheel", event => {
    if (!event.ctrlKey && !event.metaKey && event.target instanceof HTMLCanvasElement) event.stopImmediatePropagation();
  }, { capture: true, passive: true });
}

async function start(): Promise<void> {
  const [data, tuning] = await Promise.all([
    dataJson<TourData>("tour.json"), dataJson<Record<string, unknown>>("tuning.json"),
  ]);
  // The owner's own graph tuning is the demo's look (graph/tuning.ts reads these keys).
  for (const [graphId, value] of Object.entries(tuning)) {
    try { localStorage.setItem(`obsidience.tuning3d.${encodeURIComponent(graphId)}.v3`, JSON.stringify(value)); }
    catch { /* storage blocked: the app announces the same values after mounting */ }
  }
  const embed = new URLSearchParams(location.search).get("embed") === "1";
  if (embed) {
    wheelScrollsPage();
    // A page's hero shares its thread with the page: draw it at one device
    // pixel per CSS pixel (the full-screen demo keeps the renderers' 1.5 cap).
    Object.defineProperty(window, "devicePixelRatio", { configurable: true, get: () => 1 });
  }
  const tour = new Tour(data);
  followViewport(tour);
  createRoot(document.getElementById("root")!).render(
    <React.StrictMode><DemoApp tour={tour} ownerTuning={tuning} embed={embed}/></React.StrictMode>,
  );
}

void start();
