/** The Knowledge stage's reading of the page's /ws/activity stream: the lit
 *  thinking packet, Tool operations, cleared runs and speech playback. A
 *  presentation of Harness events, never an inference or execution source. */

import { useEffect, useRef, useState } from "react";
import type { KnowledgeActivity, LinkReviewChange } from "@/lib/api";
import { subscribeActivity } from "@/lib/activity-client";
import { MAIN_GRAPH_ID } from "@/graph/tuning";
import { currentOperations, operationDeadline, type GraphOperation } from "./graph-activity";

const FOCUS_LINGER_MS = 6_000; // The lit route stays on screen this long after its run ends.

interface ActivityWireEntry {
  run_id?: string;
  turn_id?: string;
  phase?: KnowledgeActivity["phase"] | "review_changed" | "graph_changed";
  review?: LinkReviewChange;
  refs?: string[];
  query?: string;
  graph_id?: string;
  at?: number;
  retrieval_ms?: number;
}

interface ActivityWireMessage extends ActivityWireEntry {
  type?: "activity" | "snapshot" | "playback" | "operation";
  entries?: ActivityWireEntry[];
  playback?: SpeechPlayback;
  operation?: GraphOperation;
  operations?: GraphOperation[];
}

interface SpeechPlayback {
  status: "idle" | "pending" | "speaking";
  level: number;
  run_id: string;
  playback_id: string;
}

function activityFromWire(entry: ActivityWireEntry): KnowledgeActivity | null {
  if (!entry.phase || entry.phase === "review_changed" || entry.phase === "graph_changed") return null;
  return {
    phase: entry.phase,
    runId: entry.run_id,
    turnId: entry.turn_id,
    refs: Array.isArray(entry.refs) ? entry.refs : [],
    query: entry.query,
    at: typeof entry.at === "number" ? entry.at : undefined,
    graphId: entry.graph_id,
    retrievalMs: typeof entry.retrieval_ms === "number"
      ? entry.retrieval_ms : undefined,
  };
}

/** Replay only the newest coherent transaction. Activity history is recovery
 * state, not a second animation source or a backlog of old turns. */
function latestActivityTransaction(entries: ActivityWireEntry[], playbackRunId = ""): KnowledgeActivity[] {
  const activity = entries.map(activityFromWire).filter((entry): entry is KnowledgeActivity => entry !== null);
  let startIndex = -1;
  for (let index = activity.length - 1; index >= 0; index -= 1) {
    if ((activity[index].phase === "query_started" || activity[index].phase === "admission_started")
      && (!playbackRunId || activity[index].runId === playbackRunId)) {
      startIndex = index;
      break;
    }
  }
  if (startIndex < 0) return [];

  const started = activity[startIndex];
  const graphId = started.graphId ?? MAIN_GRAPH_ID;
  const query = started.query ?? "";
  let path: KnowledgeActivity | null = null;
  let speaking: KnowledgeActivity | null = null;
  let terminal: KnowledgeActivity | null = null;
  for (const entry of activity.slice(startIndex + 1)) {
    if ((entry.graphId ?? MAIN_GRAPH_ID) !== graphId
      || (started.runId ? entry.runId !== started.runId
        : started.turnId ? entry.turnId !== started.turnId : (entry.query ?? "") !== query)) continue;
    if (entry.phase === "path") path = entry;
    else if (entry.phase === "speaking") speaking = entry;
    else if (entry.phase === "query_completed" || entry.phase === "cleared" || entry.phase === "admission_completed") terminal = entry;
  }
  if (terminal?.phase === "cleared" || terminal?.phase === "admission_completed") return [];
  if (!playbackRunId && terminal?.at !== undefined && Date.now() - terminal.at >= FOCUS_LINGER_MS) return [];
  // A reconnect may land between start and packet compilation. Preserve that
  // start so the popup includes the Task trace emitted before its graph path.
  return [started, path, speaking, terminal].filter(
    (entry): entry is KnowledgeActivity => entry !== null,
  );
}

export interface ActiveThinking {
  runId?: string;
  refs: string[];
  phase: "thinking" | "speaking";
  key: number;
  graphId?: string;
  query?: string;
  retrievalMs?: number;
  startedAt: number;
}

export function useThinkingActivity(handlers: {
  /** A link proposal's Review outcome arrived. */
  onReview: (review: LinkReviewChange) => void;
  /** Accepted knowledge changed: reload the graph snapshot. */
  onGraphChanged: () => void;
}) {
  const listeners = useRef(handlers);
  listeners.current = handlers;
  const [activity, setActivity] = useState<ActiveThinking | null>(null);
  const [operations, setOperations] = useState<GraphOperation[]>([]);
  const activityKey = useRef(0);
  const lingerTimer = useRef<number | null>(null);
  const activityTransaction = useRef<KnowledgeActivity | null>(null);
  const finishedRuns = useRef(new Map<string, number>()); // Per-run presentation expiry.
  const [clearedRuns, setClearedRuns] = useState<ReadonlySet<string>>(new Set());
  const playback = useRef<SpeechPlayback>({ status: "idle", level: 0, run_id: "", playback_id: "" });
  const speechEnvelope = useRef({ level: 0, updatedAt: 0 });

  // One finite expiry deadline; the existing Scene still owns animation frames.
  useEffect(() => {
    const settled = operations.filter((entry) => operationDeadline(entry));
    if (!settled.length) return;
    const deadline = Math.min(...settled.map(operationDeadline));
    const timer = window.setTimeout(() => setOperations((current) => currentOperations(current)),
      Math.max(1, deadline - Date.now()));
    return () => window.clearTimeout(timer);
  }, [operations]);

  function speechHolds(next: KnowledgeActivity): boolean {
    return playback.current.status !== "idle" && Boolean(next.runId)
      && next.runId === playback.current.run_id && (next.graphId ?? MAIN_GRAPH_ID) === MAIN_GRAPH_ID;
  }

  function finishRun(runId: string | undefined, at = Date.now(), lingerMs = FOCUS_LINGER_MS): void {
    if (!runId || finishedRuns.current.has(runId)) return;
    const expiresAt = at + lingerMs;
    finishedRuns.current.set(runId, expiresAt);
    if (finishedRuns.current.size > 100) finishedRuns.current.delete(finishedRuns.current.keys().next().value!);
    // This is a finite presentation tail, never a change to the operation's
    // outcome or the Harness's ownership of its run.
    setOperations(current => currentOperations(current.map(entry => entry.run_id === runId
      ? { ...entry, expires_at: expiresAt } : entry)));
  }

  function settleActivity(next: KnowledgeActivity): void {
    if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
    lingerTimer.current = null;
    if (speechHolds(next)) return;
    const deadline = finishedRuns.current.get(next.runId ?? "") ?? (next.at ?? Date.now()) + FOCUS_LINGER_MS;
    const remaining = Math.max(0, deadline - Date.now());
    const clear = () => {
      if (activityTransaction.current !== next || speechHolds(next)) return;
      setActivity(null);
      lingerTimer.current = null;
    };
    if (remaining === 0) clear();
    else lingerTimer.current = window.setTimeout(clear, remaining);
  }

  useEffect(() => {
    let recent: ActivityWireEntry[] = [];
    const applyPlayback = (next?: SpeechPlayback, restore = true) => {
      if (!next || !["idle", "pending", "speaking"].includes(next.status)
        || !Number.isFinite(next.level) || typeof next.run_id !== "string"
        || typeof next.playback_id !== "string") return;
      const previous = playback.current;
      playback.current = next;
      // Levels reach the scene's existing frame loop without React renders.
      speechEnvelope.current = {
        level: next.status === "speaking" ? Math.max(0, Math.min(1, next.level)) : 0,
        updatedAt: performance.now(),
      };
      if (previous.status === next.status && previous.playback_id === next.playback_id && previous.run_id === next.run_id) return;
      if (next.status === "speaking" && next.run_id) {
        setActivity(current => current?.runId === next.run_id ? { ...current, phase: "speaking" } : current);
      }
      if (next.status === "idle" && next.playback_id && next.playback_id === previous.playback_id
        && next.run_id === previous.run_id) {
        // Audio has ended; the route lingers like a text-only one before the Scene fades.
        finishRun(next.run_id);
      }
      const transaction = activityTransaction.current;
      if (next.status !== "idle" && next.run_id) {
        if (transaction && speechHolds(transaction)) {
          if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
          lingerTimer.current = null;
        } else if (restore) {
          const transaction = latestActivityTransaction(recent, next.run_id);
          if (transaction.length) {
            resetActivity();
            transaction.forEach(receiveActivity);
          }
        }
      } else if (transaction?.runId && transaction.runId === previous.run_id) {
        if (!next.playback_id) {
          // STOP, replacement, or transport loss ends only the old reply.
          if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
          lingerTimer.current = null;
          activityTransaction.current = null;
          setClearedRuns(current => new Set([...current, previous.run_id].slice(-100)));
          setOperations(current => current.filter(entry => entry.run_id !== previous.run_id));
          setActivity(null);
        } else if (transaction.phase === "query_completed") {
          settleActivity(transaction);
        }
      }
    };
    const reviewChanged = (entry: ActivityWireEntry) => {
      if (entry.phase === "graph_changed") {
        listeners.current.onGraphChanged();
        return;
      }
      if (entry.phase !== "review_changed" || !entry.review) return;
      listeners.current.onReview(entry.review);
      listeners.current.onGraphChanged();
    };
    const resetActivity = () => {
      if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
      lingerTimer.current = null;
      activityTransaction.current = null;
      setActivity(null);
    };
    const stop = subscribeActivity({
      message: (frame) => {
        try {
          const message = frame as ActivityWireMessage;
          if (message.type === "activity") {
            recent = [...recent, message].slice(-100);
            reviewChanged(message);
            const activity = activityFromWire(message);
            if (activity) receiveActivity(activity);
          } else if (message.type === "snapshot" && Array.isArray(message.entries)) {
            resetActivity(); // Replace stale display state with the current stream snapshot.
            recent = message.entries.slice(-100);
            applyPlayback(message.playback, false);
            setOperations(currentOperations((message.operations ?? []).map(entry => {
              const expiresAt = finishedRuns.current.get(entry.run_id);
              return expiresAt === undefined ? entry : { ...entry, expires_at: expiresAt };
            })));
            message.entries.forEach(reviewChanged);
            latestActivityTransaction(message.entries,
              playback.current.status !== "idle" ? playback.current.run_id : "",
            ).forEach(receiveActivity);
          } else if (message.type === "playback") {
            applyPlayback(message.playback);
          } else if (message.type === "operation" && message.operation) {
            const operation = message.operation;
            const expiresAt = finishedRuns.current.get(operation.run_id);
            const presented = expiresAt === undefined ? operation
              : { ...operation, expires_at: expiresAt };
            setOperations((current) => currentOperations([...current, presented]));
            if (operation.refresh) listeners.current.onGraphChanged();
          }
        } catch { /* malformed activity frames are ignored */ }
      },
      close: () => {
        resetActivity(); // A lost stream is not evidence that a graph is still thinking.
        setOperations([]);
        applyPlayback({ status: "idle", level: 0, run_id: "", playback_id: "" });
      },
    });
    return () => {
      stop();
      speechEnvelope.current = { level: 0, updatedAt: 0 };
    };
  }, []);

  function receiveActivity(next: KnowledgeActivity): void {
    // Each specialist can finish independently of the foreground packet.
    // Voice remains animated through queued and playing audio, until playback ends.
    if (next.phase === "query_completed" && !speechHolds(next)) finishRun(next.runId, next.at);
    if (next.phase === "cleared" && next.runId) {
      const runId = next.runId;
      setClearedRuns(current => new Set([...current, runId].slice(-100)));
      setOperations(current => current.filter(entry => entry.run_id !== runId));
    }
    const previous = activityTransaction.current;
    // Background work cannot replace the Executive packet during its reply.
    if (previous && speechHolds(previous) && next.runId !== previous.runId) return;
    // Admission has a real user-turn identity but no Task/run yet. Its terminal
    // edge may clear only that preparation state, never a compiled Task path.
    if (next.phase === "admission_completed") {
      if (previous?.phase !== "admission_started" || !next.turnId || previous.turnId !== next.turnId) return;
      activityTransaction.current = null;
      setActivity(null);
      return;
    }
    const admissionHandoff = previous?.phase === "admission_started"
      && next.phase === "query_started" && Boolean(next.turnId) && previous.turnId === next.turnId;
    const same = previous && (previous.graphId ?? "main") === (next.graphId ?? "main")
      && (previous.runId || next.runId ? previous.runId === next.runId : previous.query === next.query);
    const terminal = next.phase === "query_completed" || next.phase === "cleared";
    if (terminal && !same) return; // Another run cannot finish the visible run.
    if (!terminal && previous && next.at !== undefined && previous.at !== undefined
      && next.at < previous.at) return;
    if (same && (previous.phase === "query_completed" || previous.phase === "cleared")
      && !terminal && (next.phase !== "query_started" || Boolean(next.runId))) return;
    if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
    lingerTimer.current = null;
    activityTransaction.current = next;
    if (next.phase === "cleared") {
      setActivity(null);
      return;
    }
    if (next.phase === "query_started" || next.phase === "admission_started") {
      activityKey.current += 1;
      setActivity((current) => ({
        refs: next.phase === "admission_started" ? next.refs : [],
        phase: "thinking", key: activityKey.current, query: next.query,
        retrievalMs: next.retrievalMs, graphId: next.graphId, runId: next.runId,
        startedAt: admissionHandoff && current ? current.startedAt : next.at ?? Date.now(),
      }));
      return;
    }
    if (next.phase === "path") {
      activityKey.current += 1;
      setActivity((current) => ({
        refs: next.refs, phase: "thinking", key: activityKey.current, query: next.query,
        retrievalMs: next.retrievalMs ?? (same ? current?.retrievalMs : undefined),
        graphId: next.graphId, runId: next.runId,
        startedAt: same && current ? current.startedAt : next.at ?? Date.now(),
      }));
      return;
    }
    if (next.phase === "speaking") {
      setActivity((current) => ({
        refs: next.refs.length > 0 ? next.refs : (same ? current?.refs ?? [] : []),
        phase: speechHolds(next) && playback.current.status === "pending" ? "thinking" : "speaking", key: same && current ? current.key : ++activityKey.current,
        query: next.query, retrievalMs: next.retrievalMs ?? (same ? current?.retrievalMs : undefined),
        graphId: next.graphId, runId: next.runId,
        startedAt: same && current ? current.startedAt : next.at ?? Date.now(),
      }));
      return;
    }
    setActivity((current) => current ? { ...current, phase: speechHolds(next) && playback.current.status === "pending" ? "thinking" : "speaking" } : null);
    settleActivity(next);
  }

  useEffect(() => () => {
    if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
  }, []);

  return { activity, setActivity, operations, clearedRuns, finishedRuns, playback, speechEnvelope, activityKey };
}
