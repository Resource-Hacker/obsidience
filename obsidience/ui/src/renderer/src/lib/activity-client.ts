/** The page's one /ws/activity stream, shared by every consumer on the page.
 *  Each subscriber starts from a snapshot of the stream, as if it had just
 *  connected; the socket lives while anyone listens. */

import { WS_BASE } from "@/lib/api";

interface ActivityOperation { id: string; status?: string; expires_at?: number }
/** The frame fields this client keeps; consumers read the rest. */
export interface ActivityFrame {
  type?: string;
  entries?: unknown[];
  playback?: unknown;
  operation?: ActivityOperation;
  operations?: ActivityOperation[];
}
export interface ActivityListener {
  open?(): void;
  message(frame: ActivityFrame): void;
  /** The stream was lost; it reconnects while anyone listens. */
  close?(): void;
}

const RECONNECT_MS = 1_000;
// The Harness snapshot's own bounds: retained history and display operations.
const HISTORY = 100;
const MAX_OPERATIONS = 96;

const listeners = new Set<ActivityListener>();
let socket: WebSocket | null = null;
let opened = false;
let retry: ReturnType<typeof setTimeout> | null = null;
/** The stream since its last snapshot, replayed to a later subscriber. */
let state: { entries: unknown[]; playback: unknown; operations: Map<string, ActivityOperation> } | null = null;

function call(run: () => void): void {
  // One consumer's failure must not starve the others of the stream.
  try { run(); } catch (error) { reportError(error); }
}

function prune(operations: Map<string, ActivityOperation>): void {
  const now = Date.now();
  for (const [id, entry] of operations) if (entry.expires_at && now >= entry.expires_at) operations.delete(id);
}

function remember(frame: ActivityFrame): void {
  if (frame.type === "snapshot") {
    state = { entries: Array.isArray(frame.entries) ? frame.entries.slice(-HISTORY) : [], playback: frame.playback,
      operations: new Map((Array.isArray(frame.operations) ? frame.operations : [])
        .filter(entry => typeof entry?.id === "string").map(entry => [entry.id, entry])) };
  } else if (!state) {
    return;
  } else if (frame.type === "activity") {
    const { type: _type, ...entry } = frame;
    state.entries = [...state.entries, entry].slice(-HISTORY);
  } else if (frame.type === "playback") {
    state.playback = frame.playback;
  } else if (frame.type === "operation" && typeof frame.operation?.id === "string") {
    const operations = state.operations;
    operations.delete(frame.operation.id);
    operations.set(frame.operation.id, frame.operation);
    prune(operations);
    // Running work stays ahead of settled flashes, as the Harness keeps it.
    for (const [id, entry] of operations) {
      if (operations.size <= MAX_OPERATIONS) break;
      if (entry.status !== "running") operations.delete(id);
    }
    for (const id of operations.keys()) {
      if (operations.size <= MAX_OPERATIONS) break;
      operations.delete(id);
    }
  }
}

function snapshot(current: NonNullable<typeof state>): ActivityFrame {
  prune(current.operations);
  return { type: "snapshot", entries: [...current.entries], playback: current.playback,
    operations: [...current.operations.values()] };
}

function connect(): void {
  retry = null;
  const next = new WebSocket(`${WS_BASE}/ws/activity`);
  socket = next;
  next.onopen = () => {
    if (socket !== next) return;
    opened = true;
    for (const listener of [...listeners]) if (listener.open) call(() => listener.open!());
  };
  next.onmessage = (event) => {
    if (socket !== next) return;
    let frame: ActivityFrame;
    try { frame = JSON.parse(event.data as string); } catch { return; }
    if (!frame || typeof frame !== "object") return;
    remember(frame);
    for (const listener of [...listeners]) call(() => listener.message(frame));
  };
  next.onerror = () => next.close();
  next.onclose = () => {
    if (socket !== next) return;
    socket = null; opened = false; state = null;
    for (const listener of [...listeners]) if (listener.close) call(() => listener.close!());
    if (listeners.size && !socket) retry = setTimeout(connect, RECONNECT_MS);
  };
}

export function subscribeActivity(listener: ActivityListener): () => void {
  listeners.add(listener);
  if (!socket) {
    if (retry) clearTimeout(retry);
    connect();
  } else if (opened) {
    // Delivered before the next frame, in the order a new socket gives them.
    queueMicrotask(() => {
      if (!listeners.has(listener)) return;
      if (listener.open) call(() => listener.open!());
      if (state) { const frame = snapshot(state); call(() => listener.message(frame)); }
    });
  }
  return () => {
    if (!listeners.delete(listener) || listeners.size) return;
    if (retry) clearTimeout(retry);
    retry = null;
    const closing = socket;
    socket = null; opened = false; state = null;
    closing?.close();
  };
}
