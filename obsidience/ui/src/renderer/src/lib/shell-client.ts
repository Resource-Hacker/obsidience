import {
  KNOWLEDGE_3D_TUNING_FIELDS,
  clampKnowledge3dTuning,
  type Knowledge3dTuning,
} from "@/components/themes/obsidience/knowledge-3d";
import {
  LIBRARY_GRAPH_ID,
  MAIN_GRAPH_ID,
  announceGraphTuning,
  defaultGraphTuning,
  graphTuningProfilesFor,
  loadGraphTuning,
  loadGraphTuningProfileStore,
  onGraphSelected,
  requestGraphThinkingTest,
  saveGraphTuningProfile,
  selectGraphTuningProfile,
} from "@/lib/graph-tuning";

const SHELL_URL = "ws://127.0.0.1:8768";
const SHELL_SUBPROTOCOL = "obsidience.shell.v1";
const COMMAND_SCHEMA = "obsidience.shell.command.v1";
const EVENT_SCHEMA = "obsidience.shell.event.v1";

const pending: string[] = [];
const knowledgeVisibilityListeners = new Map<
  string,
  Set<(visible: boolean) => void>
>();
const graphDisplayListeners = new Set<(surfaceId: string) => void>();
/** A region of one Surface as fractions of its full logical size. */
export type StageRegion = { x: number; y: number; width: number; height: number };
type StageListener = { listener: (visible: boolean) => void; region?: () => StageRegion | null };
const stageVisibilityListeners = new Map<string, Set<StageListener>>();
type WindowRect = { x: number; y: number; width: number; height: number };
const stageWindows = new Map<string, WindowRect[]>();
/** Logical Surface size from the Shell's surface-layout.json, per application.state. */
const stageSizes = new Map<string, [number, number]>();
// Tiles sit 5 px apart plus a 1 px border each and 6 px from the Surface edge;
// growing every window by this margin closes those gaps.
const COVER_GAP_PX = 8;
export type ShellOledPolicy = { enabled: boolean; shiftPx: number; travelSeconds: number };
const oledPolicyListeners = new Set<(policy: ShellOledPolicy) => void>();
let oledPolicy: ShellOledPolicy = { enabled: false, shiftPx: 32, travelSeconds: 3600 };
export type ProviderGraphSettings = { bank?: string; memoryType?: string; follow?: boolean; allSymbols?: boolean; graphId?: string; refresh?: boolean; fit?: boolean };
const providerViewListeners = new Map<string, Set<(settings: ProviderGraphSettings) => void>>();
const providerViews = new Map<string, ProviderGraphSettings>();
export type GraphView = "knowledge" | "memory" | "code";
let graphViewerView: GraphView = "knowledge";
const graphViewerListeners = new Set<(view: GraphView) => void>();
export type GraphSource = GraphView | "library" | "knowledge:Darwin" | "knowledge:Alexandria" | "knowledge:Heimdall";
export type GraphSignal = { action: string; id?: string; role?: string; signal?: RTCSessionDescriptionInit | RTCIceCandidateInit; reason?: string };
const graphPorts = new Map<string, {view: GraphSource; role: "stage" | "viewer"; receive: (event: GraphSignal) => void}>();
const stageAwake = new Map<string, boolean>();
let sessionLocked = false;
const readerSelectionListeners = new Set<(ref: string, graphId: string) => void>();
let receivedReaderState = false;
let socket: WebSocket | null = null;
let connecting = false;
let tokenWarned = false;
let reconnect: ReturnType<typeof setTimeout> | null = null;
const knowledgeVisibility = new Map<string, boolean>([["samsung", true]]);
let selectedGraphSurfaceId = "samsung";
let selectedGraphId = MAIN_GRAPH_ID;
let knowledgePresenter: "knowledge" | "library" | null = null;

export function claimShellKnowledgePresenter(source: "knowledge" | "library" = "knowledge"): () => void {
  knowledgePresenter = source;
  return () => { knowledgePresenter = null; };
}

const LIBRARY_NODE_STYLE_KEYS = new Set([
  "subjectStyle",
  "subnodeStyle",
  "articleStyle",
]);

function needsConnection(): boolean {
  return pending.length > 0
    || knowledgeVisibilityListeners.size > 0
    || readerSelectionListeners.size > 0
    || graphDisplayListeners.size > 0
    || graphViewerListeners.size > 0
    || providerViewListeners.size > 0
    || graphPorts.size > 0
    || oledPolicyListeners.size > 0
    || stageVisibilityListeners.size > 0;
}

onGraphSelected((graphId) => {
  selectedGraphId = graphId || MAIN_GRAPH_ID;
  sendCommand({ type: "graph.selection.publish", graph_id: selectedGraphId });
});

function sendCommand(payload: Record<string, unknown>): void {
  const encoded = JSON.stringify({ schema: COMMAND_SCHEMA, ...payload });
  if (socket?.readyState === WebSocket.OPEN) socket.send(encoded);
  else {
    pending.push(encoded);
    connect();
  }
}

function publishGraphState(graphId: string): void {
  const id = graphId || MAIN_GRAPH_ID;
  const profiles = graphTuningProfilesFor(loadGraphTuningProfileStore(), id);
  const fields = KNOWLEDGE_3D_TUNING_FIELDS
    .filter((field) => id !== MAIN_GRAPH_ID || !field.satelliteOnly)
    .filter((field) => id === MAIN_GRAPH_ID || !field.mainOnly)
    .map((field) => {
      if (id !== LIBRARY_GRAPH_ID && LIBRARY_NODE_STYLE_KEYS.has(field.key)) {
        return { ...field, max: 3, options: field.options?.slice(0, 4) };
      }
      return field;
    });
  sendCommand({
    type: "graph.state.publish",
    graph_id: id,
    tuning: clampKnowledge3dTuning(
      profiles.profiles[profiles.active] ?? loadGraphTuning(id),
    ),
    default_tuning: defaultGraphTuning(id),
    fields,
    profile: profiles.active,
    profiles: Object.keys(profiles.profiles),
  });
}

function handleGraphCommand(message: {
  type?: unknown;
  action?: unknown;
  graph_id?: unknown;
  tuning?: unknown;
  profile?: unknown;
}): boolean {
  if (message.type !== "graph.command" || typeof message.graph_id !== "string") {
    return false;
  }
  if (!knowledgePresenter) return true;
  const graphId = message.graph_id || MAIN_GRAPH_ID;
  if ((graphId === LIBRARY_GRAPH_ID) !== (knowledgePresenter === "library")) return true;
  if (message.action === "state.request") {
    publishGraphState(graphId);
  } else if (message.action === "thinking.test") {
    requestGraphThinkingTest(graphId);
  } else if (message.action === "tuning.preview") {
    announceGraphTuning({
      graphId,
      tuning: clampKnowledge3dTuning(message.tuning),
    });
  } else if (message.action === "tuning.save") {
    const tuning: Knowledge3dTuning = clampKnowledge3dTuning(message.tuning);
    const profiles = graphTuningProfilesFor(loadGraphTuningProfileStore(), graphId);
    saveGraphTuningProfile(graphId, profiles.active, tuning);
    publishGraphState(graphId);
  } else if (message.action === "profile.select" && typeof message.profile === "string") {
    selectGraphTuningProfile(graphId, message.profile);
    publishGraphState(graphId);
  } else if (message.action === "profile.create" && typeof message.profile === "string") {
    saveGraphTuningProfile(
      graphId,
      message.profile,
      clampKnowledge3dTuning(message.tuning),
    );
    publishGraphState(graphId);
  }
  return true;
}

function handleMessage(event: MessageEvent): void {
  if (typeof event.data !== "string" || event.data.length > 65536) return;
  try {
    const stream = JSON.parse(event.data);
    if (stream.schema === EVENT_SCHEMA && stream.type === "graph.stream") {
      graphPorts.get(stream.to)?.receive(stream);
      return;
    }
    const message = JSON.parse(event.data) as {
      schema?: unknown;
      type?: unknown;
      action?: unknown;
      graph_id?: unknown;
      tuning?: unknown;
      profile?: unknown;
      session_locked?: unknown; surface_id?: string; surface_awake?: boolean;
      logical_width?: unknown; logical_height?: unknown;
      oled_mode_enabled?: unknown; oled_shift_distance_px?: unknown; oled_travel_duration_seconds?: unknown;
      windows?: { minimized?: boolean; visible_on_workspace?: boolean; local_rect?: Partial<WindowRect> }[];
      surface?: { surface_id?: unknown; visible?: unknown };
      selected_surface_id?: unknown;
      pane?: { pane_id?: unknown; open?: unknown };
      pane_id?: string;
      selection?: { kind?: unknown; ref?: unknown; graph_id?: unknown; view?: unknown };
      view?: string; settings?: ProviderGraphSettings;
    };
    if (message.schema !== EVENT_SCHEMA) return;
    if (message.type === "pane.selection" && message.pane_id === "knowledge-graph"
      && message.selection?.kind === "graph" && ["knowledge", "memory", "code"].includes(String(message.selection.view))) {
      graphViewerView = message.selection.view as GraphView;
      for (const listener of graphViewerListeners) listener(graphViewerView);
      return;
    }
    if (message.type === "graph.viewer.state" && message.view && message.settings) {
      const { refresh: _refresh, fit: _fit, ...settings } = message.settings;
      providerViews.set(message.view, settings);
      for (const listener of providerViewListeners.get(message.view) || []) listener(message.settings);
      return;
    }
    if (message.type === "workspace.state" && typeof message.session_locked === "boolean") {
      sessionLocked = message.session_locked;
      notifyStageVisibility();
    }
    if (message.type === "workspace.state" && typeof message.oled_mode_enabled === "boolean") {
      const shift = message.oled_shift_distance_px, travel = message.oled_travel_duration_seconds;
      const next = {
        enabled: message.oled_mode_enabled,
        shiftPx: typeof shift === "number" && Number.isFinite(shift) ? Math.max(1, Math.min(50, shift)) : oledPolicy.shiftPx,
        travelSeconds: typeof travel === "number" && Number.isFinite(travel) ? Math.max(60, Math.min(86400, travel)) : oledPolicy.travelSeconds,
      };
      if (next.enabled !== oledPolicy.enabled || next.shiftPx !== oledPolicy.shiftPx || next.travelSeconds !== oledPolicy.travelSeconds) {
        oledPolicy = next;
        for (const listener of oledPolicyListeners) listener(oledPolicy);
      }
    }
    if (message.type === "application.state" && typeof message.surface_id === "string") {
      stageWindows.set(message.surface_id, (message.windows || []).flatMap(w => {
        const r = w.local_rect;
        return !w.minimized && w.visible_on_workspace !== false && r
          && [r.x, r.y, r.width, r.height].every(Number.isFinite) ? [r as WindowRect] : [];
      }));
      stageAwake.set(message.surface_id, message.surface_awake !== false);
      const width = message.logical_width, height = message.logical_height;
      if (typeof width === "number" && typeof height === "number" && width > 0 && height > 0)
        stageSizes.set(message.surface_id, [width, height]);
      notifyStageVisibility();
    }

    if (message.type === "pane.state" && message.pane?.pane_id === "reader") {
      const intentional = receivedReaderState;
      receivedReaderState = true;
      const selection = message.selection;
      if (intentional) for (const listener of readerSelectionListeners) {
        listener(message.pane.open !== false && selection?.kind === "article" && typeof selection.ref === "string" ? selection.ref : "",
          typeof selection?.graph_id === "string" ? selection.graph_id : MAIN_GRAPH_ID);
      }
      return;
    }
    if (handleGraphCommand(message)) return;
    if (
      message.type === "graph.display.state"
      && typeof message.selected_surface_id === "string"
      && ["samsung", "usb-c", "dp-4"].includes(message.selected_surface_id)
    ) {
      selectedGraphSurfaceId = message.selected_surface_id;
      for (const listener of graphDisplayListeners) {
        listener(selectedGraphSurfaceId);
      }
      return;
    }
    if (
      message.type !== "surface.state"
      || typeof message.surface?.surface_id !== "string"
      || typeof message.surface.visible !== "boolean"
    ) return;
    const surfaceId = message.surface.surface_id;
    knowledgeVisibility.set(surfaceId, message.surface.visible);
    for (const listener of knowledgeVisibilityListeners.get(surfaceId) ?? []) {
      listener(message.surface.visible);
    }
  } catch {
    // Ignore malformed local shell events.
  }
}

function scheduleReconnect(): void {
  if (needsConnection() && !reconnect) {
    reconnect = setTimeout(() => {
      reconnect = null;
      connect();
    }, 500);
  }
}

/** The Shell admits only clients presenting its user-only runtime token, which
 * this page's own Harness origin hands out; read it again for every connection. */
async function shellCommandUrl(): Promise<string> {
  const response = await fetch("/api/shell/command-token", { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const { token } = await response.json() as { token?: unknown };
  if (typeof token !== "string" || !/^[0-9a-f]{64}$/.test(token)) throw new Error("invalid token");
  return `${SHELL_URL}/?token=${token}`;
}

function connect(): void {
  if (connecting || (socket && socket.readyState <= WebSocket.OPEN)) return;
  connecting = true;
  shellCommandUrl().then((url) => {
    connecting = false;
    tokenWarned = false;
    socket = new WebSocket(url, SHELL_SUBPROTOCOL);
    receivedReaderState = false;
    socket.onopen = () => {
      for (const [id, port] of graphPorts) sendGraphPort({action: "join", id, view: port.view, role: port.role});
      while (pending.length) socket?.send(pending.shift()!);
    };
    socket.onmessage = handleMessage;
    socket.onclose = () => {
      socket = null;
      for (const port of graphPorts.values()) port.receive({action: "disconnect"});
      scheduleReconnect();
    };
  }, (error: unknown) => {
    connecting = false;
    if (!tokenWarned) console.warn("Shell command token unavailable:", error);
    tokenWarned = true;
    scheduleReconnect();
  });
}

function sendGraphPort(message: Record<string, unknown>): void {
  // Presentation signals have no durable queue: a reconnect creates new peers.
  if (socket?.readyState === WebSocket.OPEN)
    socket.send(JSON.stringify({schema: COMMAND_SCHEMA, type: "graph.stream", ...message}));
}

export function openGraphPort(view: GraphSource, role: "stage" | "viewer", receive: (event: GraphSignal) => void) {
  const id = crypto.randomUUID();
  graphPorts.set(id, {view, role, receive});
  connect();
  if (socket?.readyState === WebSocket.OPEN) sendGraphPort({action: "join", id, view, role});
  return {
    signal: (to: string, signal: RTCSessionDescriptionInit | RTCIceCandidateInit) => sendGraphPort({action: "signal", id, to, signal}),
    dispose: () => { sendGraphPort({action: "leave", id}); graphPorts.delete(id); },
  };
}

export function presentShellReader(ref: string, graphId = ""): void {
  sendCommand({
    type: "pane.present",
    pane_id: "reader",
    selection: { kind: "article", ref, graph_id: graphId },
  });
}

export function presentShellSource(key: string): void {
  sendCommand({ type: "pane.present", pane_id: "reader", selection: { kind: "source", key } });
}

export function presentShellGraph(view: "knowledge" | "memory" | "code"): void {
  sendCommand({ type: "pane.present", pane_id: "knowledge-graph", selection: {kind: "graph", view} });
}

export function selectShellGraphView(view: GraphView): void {
  sendCommand({type: "pane.select", pane_id: "knowledge-graph", selection: {kind: "graph", view}});
}

export function onShellGraphView(listener: (view: GraphView) => void): () => void {
  graphViewerListeners.add(listener); listener(graphViewerView); connect();
  return () => { graphViewerListeners.delete(listener); };
}

export function onShellProviderGraph(view: "knowledge" | "memory" | "code", listener: (settings: ProviderGraphSettings) => void): () => void {
  const listeners = providerViewListeners.get(view) || new Set();
  listeners.add(listener); providerViewListeners.set(view, listeners);
  if (providerViews.has(view)) listener(providerViews.get(view)!);
  connect();
  return () => { listeners.delete(listener); if (!listeners.size) providerViewListeners.delete(view); };
}

/** Intentional native selection edges; reconnect hydration is passive. */
export function onShellReaderSelection(listener: (ref: string, graphId: string) => void): () => void {
  readerSelectionListeners.add(listener);
  connect();
  return () => { readerSelectionListeners.delete(listener); };
}

export function onShellKnowledgeVisibility(
  surfaceId: string,
  listener: (visible: boolean) => void,
): () => void {
  const listeners = knowledgeVisibilityListeners.get(surfaceId) ?? new Set();
  listeners.add(listener);
  knowledgeVisibilityListeners.set(surfaceId, listeners);
  listener(knowledgeVisibility.get(surfaceId) ?? true);
  connect();
  return () => {
    listeners.delete(listener);
    if (!listeners.size) knowledgeVisibilityListeners.delete(surfaceId);
  };
}

export function onShellGraphDisplay(
  listener: (surfaceId: string) => void,
): () => void {
  graphDisplayListeners.add(listener);
  listener(selectedGraphSurfaceId);
  connect();
  sendCommand({ type: "graph.display.request", graph_id: MAIN_GRAPH_ID });
  return () => graphDisplayListeners.delete(listener);
}

/** Whether the visible windows together hide a Surface region, treating the
 * narrow tile gaps as covered. Without a region the caller may itself be one
 * of those windows (a pane page), so only one full-Surface window counts. */
function stageCovered(surfaceId: string, region?: StageRegion | null): boolean {
  const size = stageSizes.get(surfaceId), windows = stageWindows.get(surfaceId);
  if (!size || !windows?.length) return false;
  if (!region) return windows.some(w => w.width >= size[0] - 12 && w.height >= size[1] - 12);
  const left = region.x * size[0], top = region.y * size[1];
  const right = (region.x + region.width) * size[0], bottom = (region.y + region.height) * size[1];
  if (!(right > left && bottom > top)) return false;
  const boxes = windows.map(w => [Math.max(left, w.x - COVER_GAP_PX), Math.max(top, w.y - COVER_GAP_PX),
    Math.min(right, w.x + w.width + COVER_GAP_PX), Math.min(bottom, w.y + w.height + COVER_GAP_PX)])
    .filter(([l, t, rr, b]) => rr > l && b > t);
  // Unusually many windows: keep rendering rather than spend time on the test.
  if (!boxes.length || boxes.length > 64) return false;
  const edges = (low: number, high: number, a: number, b: number) =>
    [...new Set([low, high, ...boxes.flatMap(box => [box[a], box[b]])])].sort((m, n) => m - n);
  const xs = edges(left, right, 0, 2), ys = edges(top, bottom, 1, 3);
  for (let i = 1; i < xs.length; i++) for (let j = 1; j < ys.length; j++) {
    const cx = (xs[i - 1] + xs[i]) / 2, cy = (ys[j - 1] + ys[j]) / 2;
    if (!boxes.some(([l, t, rr, b]) => l <= cx && cx < rr && t <= cy && cy < b)) return false;
  }
  return true;
}

function stageVisible(surfaceId: string, region?: () => StageRegion | null): boolean {
  return !sessionLocked && stageAwake.get(surfaceId) !== false && !stageCovered(surfaceId, region?.());
}

function notifyStageVisibility(): void {
  for (const [surfaceId, listeners] of stageVisibilityListeners)
    for (const { listener, region } of listeners) listener(stageVisible(surfaceId, region));
}

/** Read-only presentation of the existing Shell OLED policy; no second settings owner. */
export function onShellOledPolicy(listener: (policy: ShellOledPolicy) => void): () => void {
  oledPolicyListeners.add(listener);
  listener(oledPolicy);
  connect();
  return () => { oledPolicyListeners.delete(listener); };
}

/** The existing Shell owns lock, output wake and covering-window state. A
 * region limits the covering test to that part of the Surface. */
export function onShellStageVisibility(surfaceId: string, listener: (visible: boolean) => void,
  region?: () => StageRegion | null): () => void {
  const listeners = stageVisibilityListeners.get(surfaceId) || new Set();
  const entry = { listener, region };
  listeners.add(entry); stageVisibilityListeners.set(surfaceId, listeners);
  listener(stageVisible(surfaceId, region));
  connect();
  return () => { listeners.delete(entry); if (!listeners.size) stageVisibilityListeners.delete(surfaceId); };
}
