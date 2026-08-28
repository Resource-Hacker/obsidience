export type ReaderModuleId = "knowledge" | "source";
export type ReaderModulePlacement = "left" | "right" | "floating";
export type ReaderDockPosition = "top" | "bottom";

export interface ReaderModuleState {
  placement: ReaderModulePlacement;
  order: number;
  collapsed: boolean;
}

export type ReaderDockLayout = Record<ReaderModuleId, ReaderModuleState>;

const STORAGE_KEY = "obsidience.reader.docking.v1";

export function defaultReaderDockLayout(): ReaderDockLayout {
  return {
    knowledge: {
      placement: "left",
      order: 0,
      collapsed: localStorage.getItem("obsidience.reader.knowledge-open") === "0",
    },
    source: {
      placement: "right",
      order: 0,
      collapsed: localStorage.getItem("obsidience.reader.source-open") === "0",
    },
  };
}

export function loadReaderDockLayout(): ReaderDockLayout {
  const fallback = defaultReaderDockLayout();
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as Partial<ReaderDockLayout> | null;
    if (!parsed) return fallback;
    for (const id of ["knowledge", "source"] as const) {
      const item = parsed[id];
      if (!item || !["left", "right", "floating"].includes(item.placement)) continue;
      fallback[id] = {
        placement: item.placement,
        order: Number.isFinite(item.order) ? item.order : fallback[id].order,
        collapsed: Boolean(item.collapsed),
      };
    }
    return fallback;
  } catch {
    return fallback;
  }
}

export function saveReaderDockLayout(layout: ReaderDockLayout): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  } catch {
    /* Layout persistence is best-effort. */
  }
}
