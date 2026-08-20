/** Slim workspace registry for Obsidience (replaces HEREBRUM's Hermes-coupled one).
 *  Keeps the same contracts pane-frame.tsx expects: PaneRect/PaneViewport/clampPaneRect. */

export type JarvisPaneId = "chat" | "library" | "jobs" | "reviews" | "reader" | "status" | "terminal";

export interface PaneRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PaneViewport {
  width: number;
  height: number;
}

export interface PaneDefinition {
  id: JarvisPaneId;
  title: string;
  minWidth: number;
  minHeight: number;
  resizable: boolean;
  defaultOpen: boolean;
  defaultRect: (viewport: PaneViewport) => PaneRect;
}

export const PANE_GRID_PX = 10;

export const OBSIDIENCE_PANES: readonly PaneDefinition[] = [
  {
    id: "chat", title: "Operator", minWidth: 360, minHeight: 320,
    resizable: true, defaultOpen: true,
    defaultRect: (v) => ({ x: v.width - 500, y: v.height - 620, width: 460, height: 560 }),
  },
  {
    id: "library", title: "Library", minWidth: 420, minHeight: 300,
    resizable: true, defaultOpen: true,
    defaultRect: (v) => ({ x: v.width / 2 - 260, y: 80, width: 520, height: 500 }),
  },
  {
    id: "jobs", title: "Jobs", minWidth: 380, minHeight: 240,
    resizable: true, defaultOpen: true,
    defaultRect: () => ({ x: 40, y: 80, width: 460, height: 340 }),
  },
  {
    id: "reviews", title: "Review Queue", minWidth: 380, minHeight: 240,
    resizable: true, defaultOpen: true,
    defaultRect: (v) => ({ x: 40, y: v.height - 440, width: 460, height: 380 }),
  },
  {
    id: "reader", title: "Reader", minWidth: 420, minHeight: 320,
    resizable: true, defaultOpen: false,
    defaultRect: (v) => ({ x: v.width / 2 - 260, y: 120, width: 520, height: 520 }),
  },
  {
    id: "status", title: "Harness", minWidth: 320, minHeight: 180,
    resizable: true, defaultOpen: false,
    defaultRect: (v) => ({ x: v.width - 380, y: 80, width: 340, height: 220 }),
  },
  {
    id: "terminal", title: "Terminal", minWidth: 620, minHeight: 300,
    resizable: true, defaultOpen: true,
    defaultRect: (v) => ({ x: v.width / 2 - 350, y: 80, width: 700, height: 480 }),
  },
];

export function paneDefinition(id: JarvisPaneId): PaneDefinition {
  const def = OBSIDIENCE_PANES.find((p) => p.id === id);
  if (!def) throw new Error(`Unknown pane: ${id}`);
  return def;
}

const snap = (v: number) => Math.round(v / PANE_GRID_PX) * PANE_GRID_PX;

export function clampPaneRect(id: JarvisPaneId, rect: PaneRect, viewport: PaneViewport): PaneRect {
  const def = paneDefinition(id);
  const width = Math.min(Math.max(snap(rect.width), def.minWidth), viewport.width);
  const height = Math.min(Math.max(snap(rect.height), def.minHeight), viewport.height);
  const x = Math.min(Math.max(snap(rect.x), 0), Math.max(viewport.width - width, 0));
  const y = Math.min(Math.max(snap(rect.y), 0), Math.max(viewport.height - height, 0));
  return { x, y, width, height };
}

export interface PaneState {
  open: boolean;
  rect: PaneRect | null;
  z: number;
}

export type WorkspaceState = Record<JarvisPaneId, PaneState>;

const STORAGE_KEY = "obsidience.workspace.v2";

export function defaultWorkspace(): WorkspaceState {
  const out = {} as WorkspaceState;
  let z = 1;
  for (const def of OBSIDIENCE_PANES) {
    out[def.id] = { open: def.defaultOpen, rect: null, z: z++ };
  }
  return out;
}

export function loadWorkspace(): WorkspaceState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultWorkspace();
    const parsed = JSON.parse(raw) as Partial<WorkspaceState>;
    const base = defaultWorkspace();
    for (const def of OBSIDIENCE_PANES) {
      const stored = parsed[def.id];
      if (stored && typeof stored === "object") {
        base[def.id] = {
          open: Boolean(stored.open),
          rect: stored.rect ?? null,
          z: Number(stored.z) || base[def.id].z,
        };
      }
    }
    return base;
  } catch {
    return defaultWorkspace();
  }
}

export function saveWorkspace(state: WorkspaceState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* quota — layout persistence is best-effort */
  }
}
