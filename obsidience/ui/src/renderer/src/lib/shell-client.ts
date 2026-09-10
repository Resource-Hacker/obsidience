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
let socket: WebSocket | null = null;
let reconnect: ReturnType<typeof setTimeout> | null = null;
const knowledgeVisibility = new Map<string, boolean>([["samsung", true]]);
let selectedGraphSurfaceId = "samsung";
let selectedGraphId = MAIN_GRAPH_ID;

const LIBRARY_NODE_STYLE_KEYS = new Set([
  "subjectStyle",
  "subnodeStyle",
  "articleStyle",
]);

function needsConnection(): boolean {
  return pending.length > 0
    || knowledgeVisibilityListeners.size > 0
    || graphDisplayListeners.size > 0;
}

onGraphSelected((graphId) => {
  selectedGraphId = graphId || MAIN_GRAPH_ID;
  sendCommand({ type: "graph.selection.publish", graph_id: selectedGraphId });
});

function sendCommand(payload: Record<string, unknown>): void {
  const encoded = JSON.stringify({ schema: COMMAND_SCHEMA, ...payload });
  const current = connect();
  if (current.readyState === WebSocket.OPEN) current.send(encoded);
  else pending.push(encoded);
}

function publishGraphState(graphId: string): void {
  const id = graphId || MAIN_GRAPH_ID;
  const profiles = graphTuningProfilesFor(loadGraphTuningProfileStore(), id);
  const fields = KNOWLEDGE_3D_TUNING_FIELDS
    .filter((field) => id !== MAIN_GRAPH_ID || !field.satelliteOnly)
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
  const graphId = message.graph_id || MAIN_GRAPH_ID;
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
    const message = JSON.parse(event.data) as {
      schema?: unknown;
      type?: unknown;
      action?: unknown;
      graph_id?: unknown;
      tuning?: unknown;
      profile?: unknown;
      surface?: { surface_id?: unknown; visible?: unknown };
      selected_surface_id?: unknown;
    };
    if (message.schema !== EVENT_SCHEMA) return;
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

function connect(): WebSocket {
  if (socket && socket.readyState <= WebSocket.OPEN) return socket;
  socket = new WebSocket(SHELL_URL, SHELL_SUBPROTOCOL);
  socket.onopen = () => {
    while (pending.length) socket?.send(pending.shift()!);
  };
  socket.onmessage = handleMessage;
  socket.onclose = () => {
    socket = null;
    if (needsConnection() && !reconnect) {
      reconnect = setTimeout(() => {
        reconnect = null;
        connect();
      }, 500);
    }
  };
  return socket;
}

export function presentShellReader(ref: string, graphId = ""): void {
  sendCommand({
    type: "pane.present",
    pane_id: "reader",
    selection: { kind: "article", ref, graph_id: graphId },
  });
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
