/** Slim workspace registry for Obsidience (replaces Obsidience's Obsidience-coupled one).
 *  Keeps the same contracts pane-frame.tsx expects: PaneRect/PaneViewport/clampPaneRect. */

export type PaneId =
  | "chat" | "library" | "tasks" | "reviews" | "reader" | "knowledge" | "source"
  | "status" | "hardware" | "camera" | "tuning";

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
  id: PaneId;
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
    id: "chat", title: "Executive", minWidth: 360, minHeight: 320,
    resizable: true, defaultOpen: true,
    defaultRect: (v) => ({ x: v.width - 500, y: v.height - 620, width: 460, height: 560 }),
  },
  {
    id: "library", title: "Library", minWidth: 420, minHeight: 300,
    resizable: true, defaultOpen: true,
    defaultRect: (v) => ({ x: v.width / 2 - 260, y: 80, width: 520, height: 500 }),
  },
  {
    id: "tasks", title: "Tasks", minWidth: 380, minHeight: 240,
    resizable: true, defaultOpen: true,
    defaultRect: () => ({ x: 40, y: 80, width: 460, height: 340 }),
  },
  {
    id: "reviews", title: "Review Queue", minWidth: 380, minHeight: 240,
    resizable: true, defaultOpen: true,
    defaultRect: (v) => ({ x: 40, y: v.height - 440, width: 460, height: 380 }),
  },
  {
    id: "reader", title: "Reader", minWidth: 520, minHeight: 360,
    resizable: true, defaultOpen: false,
    defaultRect: (v) => {
      const width = Math.min(1_180, v.width - 160);
      const height = Math.min(760, v.height - 200);
      return { x: (v.width - width) / 2, y: 120, width, height };
    },
  },
  {
    id: "knowledge", title: "Knowledge", minWidth: 320, minHeight: 320,
    resizable: true, defaultOpen: false,
    defaultRect: (v) => ({ x: 80, y: 120, width: 420, height: Math.min(760, v.height - 180) }),
  },
  {
    id: "source", title: "Source", minWidth: 340, minHeight: 280,
    resizable: true, defaultOpen: false,
    defaultRect: (v) => ({ x: v.width - 500, y: 120, width: 420, height: Math.min(700, v.height - 180) }),
  },
  {
    id: "status", title: "Models", minWidth: 360, minHeight: 260,
    resizable: true, defaultOpen: false,
    defaultRect: (v) => ({ x: v.width - 380, y: 80, width: 340, height: 220 }),
  },
  {
    id: "hardware", title: "Hardware", minWidth: 360, minHeight: 300,
    resizable: true, defaultOpen: false,
    defaultRect: (v) => ({ x: v.width - 440, y: 320, width: 400, height: 510 }),
  },
  {
    id: "camera", title: "Camera", minWidth: 420, minHeight: 300,
    resizable: true, defaultOpen: false,
    defaultRect: (v) => {
      const width = Math.min(720, v.width - 120);
      const height = Math.min(480, v.height - 160);
      return { x: (v.width - width) / 2, y: 100, width, height };
    },
  },
  {
    id: "tuning", title: "Graph Tuning", minWidth: 520, minHeight: 360,
    resizable: true, defaultOpen: false,
    defaultRect: (v) => ({ x: v.width - 620, y: 80, width: 580, height: 600 }),
  },
];

export function paneDefinition(id: PaneId): PaneDefinition {
  const def = OBSIDIENCE_PANES.find((p) => p.id === id);
  if (!def) throw new Error(`Unknown pane: ${id}`);
  return def;
}

const snap = (v: number) => Math.round(v / PANE_GRID_PX) * PANE_GRID_PX;

export function clampPaneRect(id: PaneId, rect: PaneRect, viewport: PaneViewport): PaneRect {
  const def = paneDefinition(id);
  const width = Math.min(Math.max(snap(rect.width), def.minWidth), viewport.width);
  const height = Math.min(Math.max(snap(rect.height), def.minHeight), viewport.height);
  const x = Math.min(Math.max(snap(rect.x), 0), Math.max(viewport.width - width, 0));
  const y = Math.min(Math.max(snap(rect.y), 0), Math.max(viewport.height - height, 0));
  return { x, y, width, height };
}

export interface PaneState {
  open: boolean;
  surfaceId: SurfaceId;
  rect: PaneRect | null;
  z: number;
}

export type WorkspaceState = Record<PaneId, PaneState>;

export type SurfaceId = string;
export const DEFAULT_SURFACE_ID: SurfaceId = "usb-c";

const STORAGE_KEY = "obsidience.workspace.v4";
const LEGACY_STORAGE_KEY = "obsidience.workspace.v3";
const SURFACE_ID = /^[a-z0-9][a-z0-9-]{0,63}$/;

export function normalizeSurfaceId(
  candidate: unknown,
  fallback: SurfaceId = DEFAULT_SURFACE_ID,
): SurfaceId {
  return typeof candidate === "string" && SURFACE_ID.test(candidate)
    ? candidate
    : fallback;
}

export function defaultWorkspace(surfaceId: SurfaceId = DEFAULT_SURFACE_ID): WorkspaceState {
  const out = {} as WorkspaceState;
  const homeSurface = normalizeSurfaceId(surfaceId);
  let z = 1;
  for (const def of OBSIDIENCE_PANES) {
    out[def.id] = {
      open: def.defaultOpen,
      surfaceId: homeSurface,
      rect: null,
      z: z++,
    };
  }
  return out;
}

export function loadWorkspace(): WorkspaceState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY) ?? localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!raw) return defaultWorkspace();
    const parsed = JSON.parse(raw) as Partial<WorkspaceState>;
    const base = defaultWorkspace();
    for (const def of OBSIDIENCE_PANES) {
      const stored = parsed[def.id];
      if (stored && typeof stored === "object") {
        base[def.id] = {
          open: Boolean(stored.open),
          surfaceId: normalizeSurfaceId(stored.surfaceId),
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

export function panesOnSurface(
  state: WorkspaceState,
  surfaceId: SurfaceId,
): PaneId[] {
  const target = normalizeSurfaceId(surfaceId);
  return OBSIDIENCE_PANES
    .filter((pane) => state[pane.id].surfaceId === target)
    .map((pane) => pane.id);
}

export function placePaneOnSurface(
  state: WorkspaceState,
  paneId: PaneId,
  surfaceId: SurfaceId,
  rect: PaneRect | null = null,
): WorkspaceState {
  return {
    ...state,
    [paneId]: {
      ...state[paneId],
      open: true,
      surfaceId: normalizeSurfaceId(surfaceId),
      rect,
      z: Math.max(...Object.values(state).map((pane) => pane.z)) + 1,
    },
  };
}
