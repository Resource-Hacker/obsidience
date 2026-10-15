/** Whether this page is shown: its document is not hidden and its host has not
 *  covered it. The Samsung stage posts each frame's visibility; the native
 *  Graph pane sets `data-pane-visible` and dispatches an event. The page's
 *  `data-pane-visible` holds the last host report for every consumer. */

import { useSyncExternalStore } from "react";

const listeners = new Set<() => void>();
const changed = () => { for (const listener of [...listeners]) listener(); };
const stage = (event: MessageEvent) => {
  if (event.origin !== location.origin || event.data?.type !== "obsidience-stage-visibility") return;
  document.documentElement.dataset.paneVisible = String(event.data.visible === true);
  changed();
};

function subscribe(listener: () => void): () => void {
  if (!listeners.size) {
    window.addEventListener("message", stage);
    window.addEventListener("obsidience-pane-visibility", changed);
    document.addEventListener("visibilitychange", changed);
  }
  listeners.add(listener);
  return () => {
    if (!listeners.delete(listener) || listeners.size) return;
    window.removeEventListener("message", stage);
    window.removeEventListener("obsidience-pane-visibility", changed);
    document.removeEventListener("visibilitychange", changed);
  };
}

const shown = () => !document.hidden && document.documentElement.dataset.paneVisible !== "false";

export function useSurfaceVisibility(): boolean {
  return useSyncExternalStore(subscribe, shown);
}
