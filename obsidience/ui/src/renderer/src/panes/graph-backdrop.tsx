/** The Executive graph: the Obsidience 3D engine fed by the live vault using the
 *  hierarchy layout, paint pipeline, and owner's tuning.
 *  Structure: root "Executive" -> knowledge branches -> notes, plus literal
 *  agent satellites and the separate curated Library satellite. The Library
 *  never enters the Executive article tree. Wikilinks render as cross-link
 *  tendrils distinct from hierarchy edges. */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Knowledge3dScene,
  type Knowledge3dLabelMeta,
  type Knowledge3dRenderEdge,
  type Knowledge3dRenderNode,
} from "@/components/themes/obsidience/knowledge-3d-scene";
import {
  computeKnowledgeSweepPlan,
  knowledgeAgentNodeId,
  knowledge3dPathSpec,
  knowledge3dSweepTail,
  knowledgeSweepProgress3d,
  parseKnowledgeAgentNodeId,
  type Knowledge3dPathSpec,
  type Knowledge3dTuning,
} from "@/components/themes/obsidience/knowledge-3d";
import { layoutKnowledgeGraph } from "@/components/themes/obsidience/knowledge-layout";
import {
  DEFAULT_KNOWLEDGE_HUB_ANCHOR,
  type KnowledgeLayoutAnchor,
} from "@/components/themes/obsidience/knowledge-geometry";
import {
  knowledgeAmbientEdgeStroke,
  knowledgeNodeBaseAlpha,
  knowledgeNodeRadius,
  knowledgeSubjectGlowScale,
  knowledgeSubjectRingScale,
  knowledgeSubjectRingWidth,
  nodeCoreColor,
  paletteForAgent,
  paletteForBranch,
} from "@/components/themes/obsidience/knowledge-paint";
import {
  WS_BASE,
  announceKnowledgeActivity,
  api,
  onKnowledgeActivity,
  openReader,
  type GraphNavigation,
  type GraphLink,
  type GraphNavigationGroup,
  type GraphNode,
  type KnowledgeActivity,
  type GraphLinkProposals,
  type LinkReviewChange,
} from "@/lib/api";
import {
  MAIN_GRAPH_ID,
  loadGraphTuning,
  onGraphThinkingTest,
  onGraphTuning,
  selectGraph,
} from "@/lib/graph-tuning";
import { projectedAutoCuratedRefs } from "./graph-curation";
import { articleDisplayAliases, graphArticleIds, projectedArticleLinks, visibleArticleLinks, withoutTaxonomyLinks } from "./graph-links";
import { ActionTracePopup } from "./action-trace-popup";
import { KNOWLEDGE_LINK_APPROVAL_DURATION_MS } from "@/components/themes/obsidience/knowledge-3d-cloud";
import { previewLinkReviewCloud, projectLinkReviewEffects, recordLinkApproval, type LinkApproval } from "./graph-link-review";

const ROOT_ID = "@vault";
const FOCUS_LINGER_MS = 6_000;

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
  type?: "activity" | "snapshot" | "playback";
  entries?: ActivityWireEntry[];
  playback?: SpeechPlayback;
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

interface ThinkingRoute {
  nodeIds: Set<string>;
  pathSpec: Knowledge3dPathSpec;
}

interface GraphCloud {
  nodes: Knowledge3dRenderNode[];
  edges: Knowledge3dRenderEdge[];
}

interface VaultGraphSnapshot {
  nodes: GraphNode[];
  links: GraphLink[];
  auto_curated: string[];
  auto_curate_resolved: boolean;
  navigation: GraphNavigation;
}

/** Retain live status for node paint as well as durable graph changes.
 * Canonicalize unordered top-level collections; authored child arrays stay
 * ordered. The scene preserves cooling across paint-only refreshes. */
function graphSnapshotFingerprint(snapshot: VaultGraphSnapshot): string {
  return JSON.stringify({
    nodes: [...snapshot.nodes].sort((left, right) => left.id.localeCompare(right.id)),
    links: [...snapshot.links].sort((left, right) =>
      left.source.localeCompare(right.source) || left.target.localeCompare(right.target)),
    auto_curated: [...snapshot.auto_curated].sort(),
    auto_curate_resolved: snapshot.auto_curate_resolved,
    navigation: snapshot.navigation,
  });
}

/** Parent and index Articles retain semantic links; Brain peers are navigation only. */
function isArticleEndpoint(node: GraphNode): boolean {
  return node.kind !== "agent";
}

function buildThinkingRoute(cloud: GraphCloud, refs: readonly string[]): ThinkingRoute | null {
  const byId = new Map(cloud.nodes.map((node) => [node.id, node]));
  const targets = [...new Set(refs)].filter((ref) => byId.has(ref));
  if (targets.length === 0) return null;
  const edges = cloud.edges.map((edge, index) => ({
    id: `${index}:${edge.source}|${edge.target}`,
    source: edge.source,
    target: edge.target,
    taxonomy: edge.taxonomy,
  }));
  const taxonomyEdgeByChild = new Map(edges
    .filter((edge) => edge.taxonomy)
    .map((edge) => [edge.target, edge]));
  const nodeIds = new Set(targets);
  const routeNodeIds = new Set<string>();
  const activeEdgeIds = new Set<string>();
  for (const target of targets) {
    let cursor: string | null | undefined = target;
    const seen = new Set<string>();
    while (cursor && byId.has(cursor) && !seen.has(cursor)) {
      seen.add(cursor);
      routeNodeIds.add(cursor);
      const edge = taxonomyEdgeByChild.get(cursor);
      if (edge) activeEdgeIds.add(edge.id);
      cursor = byId.get(cursor)?.parentId;
    }
  }
  const root = cloud.nodes.find((node) => node.role === "root");
  if (!root) return null;
  routeNodeIds.add(root.id);
  // Keep the branching comets between supplied Articles. A relationship or
  // hierarchy waypoint is not evidence that another Article entered the packet.
  for (const edge of edges) {
    if (edge.taxonomy || !nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
    activeEdgeIds.add(edge.id);
  }
  const positions = new Map(cloud.nodes.map((node) => [node.id, { x: node.x, y: node.y }]));
  const plan = computeKnowledgeSweepPlan(
    root.id,
    [...routeNodeIds],
    [...activeEdgeIds],
    edges,
    positions,
    nodeIds,
  );
  const pathSpec = knowledge3dPathSpec(plan, edges);
  // A root-only acknowledgement has no beam to travel before Brain can light.
  // Keep the normal sweep timing for every route that reaches another node.
  if (nodeIds.size === 1 && nodeIds.has(root.id) && activeEdgeIds.size === 0) {
    return { nodeIds, pathSpec: { ...pathSpec,
      firstNodeProgress: 0, firstArticleProgress: 0, maxProgress: 0,
    } };
  }
  // Calculate beam timing through the full hierarchy first, then restrict node
  // ignition (including satellite sweeps and labels) to the supplied refs.
  return { nodeIds, pathSpec: { ...pathSpec,
    nodeArrival: new Map([...pathSpec.nodeArrival].filter(([id]) => nodeIds.has(id))),
  } };
}

interface NodeMenuState { id: string; x: number; y: number }
interface ActiveThinking {
  runId?: string;
  refs: string[];
  phase: "thinking" | "speaking";
  key: number;
  graphId?: string;
  query?: string;
  retrievalMs?: number;
  startedAt: number;
}

interface SatelliteThinkingTest {
  agentId: string;
  route: ThinkingRoute;
  key: number;
}

function NodeActionMenu({ menu, title, canEdit, onSelect, onRead, onClose, onClear }: {
  menu: NodeMenuState; title: string; canEdit: boolean;
  onSelect: () => void; onRead: () => void; onClose: () => void; onClear: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) onClose();
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [onClose]);
  const left = Math.max(8, Math.min(menu.x + 12, window.innerWidth - 184));
  const top = Math.max(8, Math.min(menu.y + 12, window.innerHeight - 180));
  return (
    <div ref={root} className="pointer-events-auto fixed z-50 w-44 rounded-lg border border-cyan-300/25 bg-[#030a10]/95 p-1 shadow-[0_0_30px_rgba(34,211,238,0.12)] backdrop-blur"
      style={{ left, top }}>
      <p className="truncate border-b border-cyan-300/10 px-2 py-1 font-mono text-[8px] uppercase tracking-wider text-cyan-300/45">{title}</p>
      <button type="button" onClick={onSelect} className="block w-full rounded px-2 py-1.5 text-left font-mono text-[10px] uppercase tracking-wider text-cyan-100 hover:bg-cyan-300/10">Select node</button>
      <button type="button" onClick={onRead} className="block w-full rounded px-2 py-1.5 text-left font-mono text-[10px] uppercase tracking-wider text-cyan-100 hover:bg-cyan-300/10">Read</button>
      {canEdit ? <button type="button" onClick={onRead} className="block w-full rounded px-2 py-1.5 text-left font-mono text-[10px] uppercase tracking-wider text-cyan-100 hover:bg-cyan-300/10">Edit task</button> : null}
      <button type="button" onClick={onClear} className="block w-full rounded px-2 py-1.5 text-left font-mono text-[10px] uppercase tracking-wider text-cyan-300/60 hover:bg-cyan-300/10">Clear selection</button>
    </div>
  );
}

export function GraphBackdrop({
  visible = true,
  lockMode = false,
  hub = DEFAULT_KNOWLEDGE_HUB_ANCHOR,
}: {
  visible?: boolean;
  lockMode?: boolean;
  hub?: KnowledgeLayoutAnchor;
} = {}) {
  const [graph, setGraph] = useState<VaultGraphSnapshot>({
    nodes: [], links: [], auto_curated: [], auto_curate_resolved: false,
    navigation: { groups: [] },
  });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [nodeMenu, setNodeMenu] = useState<NodeMenuState | null>(null);
  const [activity, setActivity] = useState<ActiveThinking | null>(null);
  const [traceInspectionSince, setTraceInspectionSince] = useState<number | null>(null);
  const [traceDismissedSince, setTraceDismissedSince] = useState<number | null>(null);
  const [sceneKey, setSceneKey] = useState(0);
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight });
  const titles = useRef(new Map<string, string>());
  const graphFingerprint = useRef<string | null>(null);
  const activityKey = useRef(0);
  const lingerTimer = useRef<number | null>(null);
  const activityTransaction = useRef<KnowledgeActivity | null>(null);
  const playback = useRef<SpeechPlayback>({ status: "idle", level: 0, run_id: "", playback_id: "" });
  const speechEnvelope = useRef({ level: 0, updatedAt: 0 });
  const testTimers = useRef<number[]>([]);
  const satelliteTestTimer = useRef<number | null>(null);
  const [satelliteTest, setSatelliteTest] = useState<SatelliteThinkingTest | null>(null);
  const [tuning, setTuning] = useState<Knowledge3dTuning>(() => loadGraphTuning(MAIN_GRAPH_ID));
  const [satelliteTunings, setSatelliteTunings] = useState<Record<string, Knowledge3dTuning>>({});
  const [linkProposals, setLinkProposals] = useState<GraphLinkProposals>({ entries: [], truncated: false });
  const [linkApprovals, setLinkApprovals] = useState<LinkApproval[]>([]);
  const proposalStarts = useRef(new Map<string, number>());

  function speechHolds(next: KnowledgeActivity): boolean {
    return playback.current.status !== "idle" && Boolean(next.runId)
      && next.runId === playback.current.run_id && (next.graphId ?? MAIN_GRAPH_ID) === MAIN_GRAPH_ID;
  }

  function settleActivity(next: KnowledgeActivity, completedAt = next.at ?? Date.now()): void {
    if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
    lingerTimer.current = null;
    if (speechHolds(next)) return;
    const remaining = Math.max(0, FOCUS_LINGER_MS - Math.max(0, Date.now() - completedAt));
    const clear = () => {
      if (activityTransaction.current !== next || speechHolds(next)) return;
      setActivity(null);
      lingerTimer.current = null;
    };
    if (remaining === 0) clear();
    else lingerTimer.current = window.setTimeout(clear, remaining);
  }

  // One expiry deadline for finite approval paint; the scene owns every frame.
  useEffect(() => {
    if (!linkApprovals.length) return;
    const deadline = Math.min(...linkApprovals.map((item) => item.startedAt + KNOWLEDGE_LINK_APPROVAL_DURATION_MS));
    const timer = window.setTimeout(() => setLinkApprovals((current) => current.filter(
      (item) => performance.now() - item.startedAt < KNOWLEDGE_LINK_APPROVAL_DURATION_MS,
    )), Math.max(1, deadline - performance.now()));
    return () => window.clearTimeout(timer);
  }, [linkApprovals]);

  // Reading the trace can outlive the graph's activity linger. This retains only
  // the popup's bounded presentation, never the animation or Task execution.
  useEffect(() => {
    if (visible && !lockMode) return;
    setTraceInspectionSince(null);
    setTraceDismissedSince(null);
  }, [visible, lockMode]);

  useEffect(() => {
    if (!lockMode) return;
    setHoveredId(null);
    setSelectedId(null);
    setNodeMenu(null);
  }, [lockMode]);

  useEffect(() => {
    const onResize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => onGraphTuning(({ graphId, tuning: next }) => {
    if (graphId === MAIN_GRAPH_ID) setTuning(next);
    else setSatelliteTunings((current) => ({ ...current, [graphId]: next }));
  }), []);

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | null = null;
    let retry: number | null = null;
    let recent: ActivityWireEntry[] = [];
    const applyPlayback = (next?: SpeechPlayback) => {
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
      if (previous.status === next.status && previous.playback_id === next.playback_id) return;
      const transaction = activityTransaction.current;
      if (next.status !== "idle" && next.run_id) {
        if (transaction && speechHolds(transaction)) {
          if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
          lingerTimer.current = null;
        } else {
          const transaction = latestActivityTransaction(recent, next.run_id);
          if (transaction.length) {
            resetActivity();
            transaction.forEach(announceKnowledgeActivity);
          }
        }
      } else if (transaction?.runId && transaction.runId === previous.run_id) {
        if (!next.playback_id) {
          // STOP, replacement, or transport loss ends only the old reply.
          if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
          lingerTimer.current = null;
          activityTransaction.current = null;
          setActivity(null);
        } else if (transaction.phase === "query_completed") {
          settleActivity(transaction, Date.now());
        }
      }
    };
    const reviewChanged = (entry: ActivityWireEntry) => {
      if (entry.phase === "graph_changed") {
        window.dispatchEvent(new Event("obsidience:graph-refresh"));
        return;
      }
      if (entry.phase !== "review_changed" || !entry.review) return;
      const review = entry.review;
      const wallNow = Date.now();
      const frameNow = performance.now();
      setLinkApprovals((current) => recordLinkApproval(current, review, wallNow, frameNow));
      // Approval retains its preview spring until the fresh accepted snapshot
      // replaces it. Removing it here would briefly tear out and re-add the link.
      if (review.state === "rejected") {
        setLinkProposals((current) => ({ ...current,
          entries: current.entries.filter((link) => link.proposal_id !== review.proposal_id),
        }));
      }
      window.dispatchEvent(new Event("obsidience:graph-refresh"));
    };
    const resetActivity = () => {
      if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
      lingerTimer.current = null;
      activityTransaction.current = null;
      setActivity(null);
    };
    const connect = () => {
      if (stopped) return;
      socket = new WebSocket(`${WS_BASE}/ws/activity`);
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data as string) as ActivityWireMessage;
          if (message.type === "activity") {
            recent = [...recent, message].slice(-100);
            reviewChanged(message);
            const activity = activityFromWire(message);
            if (activity) announceKnowledgeActivity(activity);
          } else if (message.type === "snapshot" && Array.isArray(message.entries)) {
            resetActivity(); // Replace stale display state with the current stream snapshot.
            recent = message.entries.slice(-100);
            applyPlayback(message.playback);
            message.entries.forEach(reviewChanged);
            latestActivityTransaction(message.entries,
              playback.current.status !== "idle" ? playback.current.run_id : "",
            ).forEach(announceKnowledgeActivity);
          } else if (message.type === "playback") {
            applyPlayback(message.playback);
          }
        } catch { /* malformed activity frames are ignored */ }
      };
      socket.onclose = () => {
        socket = null;
        if (!stopped) {
          resetActivity(); // A lost stream is not evidence that a graph is still thinking.
          applyPlayback({ status: "idle", level: 0, run_id: "", playback_id: "" });
          retry = window.setTimeout(connect, 1_000);
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry !== null) window.clearTimeout(retry);
      socket?.close();
      speechEnvelope.current = { level: 0, updatedAt: 0 };
    };
  }, []);

  useEffect(() => onKnowledgeActivity((next: KnowledgeActivity) => {
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
        phase: "speaking", key: same && current ? current.key : ++activityKey.current,
        query: next.query, retrievalMs: next.retrievalMs ?? (same ? current?.retrievalMs : undefined),
        graphId: next.graphId, runId: next.runId,
        startedAt: same && current ? current.startedAt : next.at ?? Date.now(),
      }));
      return;
    }
    setActivity((current) => current ? { ...current, phase: "speaking" } : null);
    settleActivity(next);
  }), []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSelectedId(null);
      setNodeMenu(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => () => {
    if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
    testTimers.current.forEach((timer) => window.clearTimeout(timer));
    if (satelliteTestTimer.current !== null) window.clearTimeout(satelliteTestTimer.current);
  }, []);

  useEffect(() => {
    let live = true;
    let requested = 0;
    let pulling = false;
    const pull = async () => {
      requested += 1;
      if (pulling) return;
      pulling = true;
      let request: number;
      do {
        request = requested;
        try {
          const next = await api.graph();
          // A review event invalidates any response started before that event.
          if (!live || request !== requested) continue;
          const proposals = next.link_proposals ?? { entries: [], truncated: false };
          const now = performance.now();
          proposalStarts.current = new Map(proposals.entries.map((link) => [
            link.proposal_id, proposalStarts.current.get(link.proposal_id) ?? now,
          ]));
          setLinkProposals((current) => JSON.stringify(current) === JSON.stringify(proposals) ? current : proposals);
          const snapshot: VaultGraphSnapshot = {
            nodes: next.nodes,
            links: next.links,
            auto_curated: next.auto_curated ?? [],
            auto_curate_resolved: next.auto_curate_resolved === true,
            navigation: next.navigation,
          };
          const fingerprint = graphSnapshotFingerprint(snapshot);
          // Accepted knowledge stays separate from the Scene-only spring preview.
          if (fingerprint === graphFingerprint.current) continue;
          graphFingerprint.current = fingerprint;
          setGraph(snapshot);
        } catch { /* retain the last accepted graph until a successful refresh */ }
      } while (live && request !== requested);
      pulling = false;
    };
    pull();
    const t = setInterval(pull, 15_000);
    window.addEventListener("obsidience:graph-refresh", pull);
    return () => {
      live = false;
      clearInterval(t);
      window.removeEventListener("obsidience:graph-refresh", pull);
    };
  }, []);

  const displayAliases = useMemo(() => articleDisplayAliases([
    ...graph.nodes,
    ...graph.navigation.groups.flatMap((group) => group.subjects),
  ]), [graph.nodes, graph.navigation]);
  const model = useMemo(() => {
    const all = graph.nodes;
    const linkPairs = projectedArticleLinks(graph.links, displayAliases);
    const executiveGroup = graph.navigation.groups.find((group) => group.id === "executive");
    const autoCurated = projectedAutoCuratedRefs(
      graph.auto_curate_resolved ? graph.auto_curated : [], all,
      [
        ...graph.navigation.groups.flatMap((group) => group.subjects),
        ...(executiveGroup ? [{ id: ROOT_ID, article_ref: executiveGroup.root_ref }] : []),
      ],
    );
    const executiveSubjects = executiveGroup?.subjects ?? [];
    const executiveName = executiveGroup?.title
      ?? all.find((node) => node.id === "Agents/Executive/Executive")?.title
      ?? "Executive";
    // Literal specialists are discovered from the same navigation manifest
    // that names their Reader cards and graph subjects.
    const agentGroups = graph.navigation.groups.filter((group) =>
      !["executive", "library"].includes(group.id));
    const agentGroupByName = new Map(agentGroups.map((group) => [
      group.root_ref.split("/")[1], group,
    ]));
    const agentNames = [...agentGroupByName.keys()];
    const subRef = (raw: string, pool: Set<string>): string | null => {
      const clean = raw.trim().replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0].split("#")[0];
      const displayed = displayAliases.get(clean) ?? clean;
      return pool.has(displayed) ? displayed : null;
    };
    const primitiveKinds = new Set(["tool", "skill", "runbook", "task"]);
    const primitiveKindOf = (node: GraphNode): string | null =>
      node.tags?.includes("task-taxonomy") ? "task"
        : primitiveKinds.has(node.kind) ? node.kind : null;
    const childRefsOf = (node: GraphNode): string[] => node.children ?? [];
    const hierarchyParents = (members: GraphNode[]): Map<string, string> => {
      const pool = new Set(members.map((node) => node.id));
      const byId = new Map(members.map((node) => [node.id, node]));
      const parentOf = new Map<string, string>();
      for (const parent of members) {
        for (const raw of childRefsOf(parent)) {
          const child = subRef(raw, pool);
          if (!child || child === parent.id || parentOf.has(child) ||
              primitiveKindOf(byId.get(child) as GraphNode) !== primitiveKindOf(parent)) continue;
          let cursor = parent.id;
          let cyclic = false;
          while (parentOf.has(cursor)) {
            cursor = parentOf.get(cursor) as string;
            if (cursor === child) { cyclic = true; break; }
          }
          if (!cyclic) parentOf.set(child, parent.id);
        }
      }
      return parentOf;
    };
    const primitiveFolderByKind: Record<string, string> = {
      tool: "Tools", skill: "Skills", runbook: "Runbooks", task: "Tasks",
    };
    const primitiveNotes = all.filter((n) => Boolean(primitiveKindOf(n))
      && !(n.kind === "skill" && !n.synthetic));
    // Shared Tool+Skill pairs and Tasks belong to the curated Library satellite.
    // Runbooks are synthesized per agent; all four primitive kinds project on
    // an agent only when that identity carries them.
    const executiveMembers = graphArticleIds(executiveGroup, displayAliases);
    const executivePrimitives = primitiveNotes.filter((node) => executiveMembers.has(node.id));
    const executiveParents = hierarchyParents(executivePrimitives);
    const executiveContainers = new Set(executiveParents.values());
    const agentIdentities = all.filter((node) => node.kind === "agent"
      && node.id.startsWith("Agents/") && node.id !== "Agents/Executive/Executive");
    // Other Brains remain navigation shortcuts, never membership expansion or
    // cross-link evidence (isArticleEndpoint excludes Agent nodes).
    const notes = [
      ...all.filter((node) => executiveMembers.has(node.id) && !primitiveKindOf(node)
        && !node.navigation_ref && node.id !== "Agents/Executive/Executive"),
      ...agentIdentities,
      ...executivePrimitives,
    ];
    const branchOf = (id: string): string | null => (id.includes("/") ? id.split("/", 1)[0] : null);
    const primitiveFolders = ["Tools", "Skills", "Runbooks", "Tasks"];
    const folders = [...new Set(notes
      .filter((node) => !agentIdentities.includes(node) && !node.id.startsWith("Agents/Executive/"))
      .map((n) => branchOf(n.id)).filter(Boolean))] as string[];
    const branches = folders
      .filter((folder) => folder !== "Library" && folder !== "@library"
        && !primitiveFolders.includes(folder)
        && !executiveSubjects.some((subject) => subject.id === `@branch/${folder}`))
      .sort();
    const folderPaths = [...new Set(notes.flatMap((node) => {
      if (agentIdentities.includes(node) || primitiveKindOf(node)) return [];
      const parts = node.id.split("/").slice(0, -1);
      if (parts.length < 2 || parts[0] === "Agents") return [];
      return parts.slice(1).map((_part, index) => parts.slice(0, index + 2).join("/"));
    }))].filter((path) => !executiveSubjects.some((subject) => subject.id === `@branch/${path}`)).sort();

    const degree = new Map<string, number>();
    const executiveArticleIds = new Set(all.filter(isArticleEndpoint)
      .map((node) => displayAliases.get(node.id) ?? node.id)
      .filter((ref) => executiveMembers.has(ref)));
    const crossLinks = visibleArticleLinks(linkPairs, executiveArticleIds, "Agents/Executive/Executive",
      new Set(executiveGroup?.article_refs ?? []));
    for (const l of crossLinks) {
      degree.set(l.source, (degree.get(l.source) ?? 0) + 1);
      degree.set(l.target, (degree.get(l.target) ?? 0) + 1);
    }

    const executiveParentOf = (node: GraphNode): string => {
      const container = executiveParents.get(node.id);
      if (container) return container;
      const primitiveKind = primitiveKindOf(node);
      if (primitiveKind) return `@branch/${primitiveFolderByKind[primitiveKind]}`;
      if (node.kind === "agent") return "@agent/Subagents";
      if (node.parent_id) return node.parent_id;
      if (node.id.startsWith("Agents/Executive/Architecture/")) return "@agent/Architecture";
      if (node.id.startsWith("Agents/Executive/Subagents/")) return "@agent/Subagents";
      if (node.id.startsWith("Agents/Executive/Observations/Temporary Observations/")) {
        return "@agent/Temporary Observations";
      }
      if (node.id.startsWith("Agents/Executive/Observations/")) return "@agent/Observations";
      const directory = node.id.split("/").slice(0, -1).join("/");
      if (directory.includes("/")) return `@branch/${directory}`;
      const branch = branchOf(node.id);
      return branch ? `@branch/${branch}` : ROOT_ID;
    };

    // Hierarchy input: the root Agent Brain Article directly owns its agent
    // subjects and world-knowledge branches.
    const layoutNodes = [
      { id: ROOT_ID, degree: branches.length + executiveSubjects.filter((subject) => !subject.parent_id).length,
        kind: "concept" as never, label: executiveName, role: "root" as never, parentId: null, order: 0 },
      ...branches.map((b, i) => ({
        id: `@branch/${b}`, degree: notes.filter((n) => branchOf(n.id) === b).length,
        kind: "concept" as never, label: b, role: "section" as never, parentId: ROOT_ID, order: i,
      })),
      ...executiveSubjects.map((subject, index) => ({
        id: subject.id,
        degree: subject.id === "@agent/Subagents"
          ? agentIdentities.length
          : executivePrimitives.filter((node) =>
            subject.id === `@branch/${primitiveFolderByKind[primitiveKindOf(node) ?? ""]}`).length,
        kind: "concept" as never,
        label: subject.title,
        role: "section" as never,
        parentId: subject.parent_id ?? ROOT_ID,
        order: index,
      })),
      ...folderPaths.map((path, index) => ({
        id: `@branch/${path}`,
        degree: notes.filter((node) => node.id.startsWith(`${path}/`)).length,
        kind: "concept" as never,
        label: path.split("/").pop() ?? path,
        role: "section" as never,
        parentId: `@branch/${path.split("/").slice(0, -1).join("/")}`,
        order: index,
      })),
      ...notes.map((n, i) => {
        const isContainer = executiveContainers.has(n.id);
        return {
          id: n.id, degree: degree.get(n.id) ?? 0, kind: "note" as never,
          label: n.title,
          role: (isContainer ? "section" : "claim") as never,
          parentId: executiveParentOf(n),
          order: i,
        };
      }),
    ];
    const taxonomyEdges = layoutNodes
      .filter((n) => n.parentId)
      .map((n, i) => ({ id: `t${i}`, source: n.parentId as string, target: n.id, type: "related_to" as never }));
    const crossEdges = withoutTaxonomyLinks(crossLinks, layoutNodes).map((l, i) => ({
      id: `x${i}`, source: l.source, target: l.target, type: "related_to" as never,
    }));

    const layout = layoutKnowledgeGraph({
      anchor: hub,
      viewport: {
        width: viewport.width,
        height: viewport.height,
        bounds: { left: 0, right: viewport.width, top: 0, bottom: viewport.height },
      },
      nodes: layoutNodes,
      edges: [...taxonomyEdges, ...crossEdges],
      ringScales: { peers: tuning.ring2dPeers, branches: tuning.ring2dBranches, articles: tuning.ring2dArticles },
      circularStage: true,
    });
    const pos = new Map(layout.nodes.map((n) => [n.id, n]));
    const meta = new Map(notes.map((n) => [n.id, n]));
    titles.current = new Map([
      [ROOT_ID, executiveName],
      ...branches.map((b) => [`@branch/${b}`, b] as [string, string]),
      ...executiveSubjects.map((subject) => [subject.id, subject.title] as [string, string]),
      ...folderPaths.map((path) => [`@branch/${path}`, path.split("/").pop() ?? path] as [string, string]),
      ...notes.map((n) => [n.id, n.title] as [string, string]),
    ]);

    const firstLevelBranchOf = (id: string): string | null => {
      if (id === ROOT_ID) return null;
      let cursor = pos.get(id);
      while (cursor?.parentId && cursor.parentId !== ROOT_ID) cursor = pos.get(cursor.parentId);
      if (cursor?.id.startsWith("@branch/")) return cursor.id.slice(8);
      if (cursor?.id.startsWith("@agent/")) return cursor.id.slice(7);
      return branchOf(cursor?.id ?? id);
    };
    const paletteOf = (id: string) => paletteForBranch(firstLevelBranchOf(id));

    // Every node inherits the palette owned by its direct Brain child.
    const renderNodes: Knowledge3dRenderNode[] = layout.nodes.map((p) => {
      const role = p.role as never as ("root" | "section" | "claim" | undefined);
      const palette = paletteOf(p.id);
      const subject = role === "root" || role === "section";
      const noteMeta = meta.get(p.id);
      return {
        id: p.id, x: p.x, y: p.y, depth: p.depth, role, parentId: p.parentId,
        radius: knowledgeNodeRadius(role, degree.get(p.id) ?? 0, false, p.depth),
        subject,
        core: nodeCoreColor(palette, role, noteMeta?.status),
        dark: palette.dark,
        ring: subject || autoCurated.has(p.id) ? palette.ring : "rgba(0,0,0,0)",
        glow: subject ? palette.glow : "rgba(0,0,0,0)",
        ringScale: knowledgeSubjectRingScale(p.depth),
        ringWidth: knowledgeSubjectRingWidth(role, p.depth),
        glowScale: subject ? knowledgeSubjectGlowScale(role, p.depth) : 1,
        alpha: knowledgeNodeBaseAlpha(role, p.depth, "hot"),
        autoCurated: autoCurated.has(p.id),
      };
    });
    const renderEdges: Knowledge3dRenderEdge[] = [
      // Taxonomy beams carry the full-saturation branch hue (original law).
      ...taxonomyEdges.map((e) => ({
        source: e.source, target: e.target, taxonomy: true,
        color: paletteOf(e.target).core,
      })),
      // Cross-links keep the dim 2D stroke and the REVERSED far-end gradient.
      ...crossEdges.map((e) => ({
        source: e.source, target: e.target, taxonomy: false,
        color: knowledgeAmbientEdgeStroke(false, false, paletteOf(e.source)),
        colorEnd: paletteOf(e.target).core,
      })),
    ];
    const reviewScopes = new Map<string, {
      articleIds: Set<string>; agentRef?: string; scopeRefs: Set<string>; links: GraphLink[];
      edgeColorEnd: (id: string) => string;
    }>([["main", { articleIds: executiveArticleIds, agentRef: "Agents/Executive/Executive",
      scopeRefs: new Set(executiveGroup?.article_refs ?? []), links: crossLinks,
      edgeColorEnd: (id) => paletteOf(id).core }]]);
    // ---- satellites: one ball per agent, seeded by its own mini hierarchy ----
    const agentSatellites = agentNames.map((name) => {
      const navigationGroup = agentGroupByName.get(name) as GraphNavigationGroup;
      const identityRef = navigationGroup.root_ref;
      const satelliteSubjects = navigationGroup.subjects;
      const subjectArticleRefs = new Set(satelliteSubjects.flatMap((subject) =>
        subject.article_ref ? [subject.article_ref] : []));
      const satelliteSubjectByKey = new Map(satelliteSubjects.map((subject) => [
        subject.id.slice(subject.id.lastIndexOf("/") + 1), subject,
      ]));
      const satelliteSubjectId = (key: string): string =>
        satelliteSubjectByKey.get(key)?.id ?? identityRef;
      const satelliteMembers = graphArticleIds(navigationGroup, displayAliases);
      const localMembers = all.filter((node) => satelliteMembers.has(node.id)
        && !subjectArticleRefs.has(node.id) && node.id !== identityRef
        && !(node.kind === "skill" && !node.synthetic));
      const otherAgentMembers = [
        ...all.filter((node) => node.kind === "agent" && node.id !== identityRef),
      ];
      // These Brain shortcuts preserve Other Agents navigation, not its scope.
      const members = [...localMembers, ...otherAgentMembers.filter((node) => !localMembers.includes(node))];
      const primitiveMembers = members.filter((member) => Boolean(primitiveKindOf(member)));
      const primitiveParents = hierarchyParents(primitiveMembers);
      const primitiveContainers = new Set(primitiveParents.values());
      const satelliteArticleIds = new Set(all.filter(isArticleEndpoint)
        .map((node) => displayAliases.get(node.id) ?? node.id)
        .filter((ref) => satelliteMembers.has(ref)));
      const satelliteParentOf = (node: GraphNode): string => {
        const primitiveParent = primitiveParents.get(node.id);
        if (primitiveParent) return primitiveParent;
        const primitiveKind = primitiveKindOf(node);
        if (primitiveKind) return satelliteSubjectId(primitiveFolderByKind[primitiveKind].toLowerCase());
        if (otherAgentMembers.includes(node)) return satelliteSubjectId("other-agents");
        const folder = node.id.split("/").slice(0, -1).join("/");
        const subject = satelliteSubjects.find((item) => item.path === folder);
        if (subject) return subject.id;
        if (name === "Darwin" && node.id.startsWith("Sources/")) {
          return satelliteSubjectId("sources");
        }
        if (node.id.startsWith(`Agents/${name}/Observations/Temporary Observations/`)) {
          return satelliteSubjectId("temporary-observations");
        }
        return satelliteSubjectId("observations");
      };
      const satLayoutNodes = [
        { id: identityRef, degree: members.length, kind: "concept" as never, label: navigationGroup.title, role: "root" as never, parentId: null as string | null, order: 0 },
        ...satelliteSubjects.map((subject, index) => ({
          id: subject.id,
          degree: primitiveMembers.filter((member) => {
            const kind = primitiveKindOf(member);
            return Boolean(kind) && subject.id === satelliteSubjectId(
              primitiveFolderByKind[kind as string].toLowerCase(),
            );
          }).length,
          kind: "concept" as never,
          label: subject.title,
          role: "section" as never,
          parentId: subject.parent_id ?? identityRef,
          order: index,
        })),
        ...members.map((n, i) => ({
          id: n.id, degree: 0, kind: "note" as never,
          label: n.title,
          role: (primitiveContainers.has(n.id) ? "section" : "claim") as never,
          parentId: satelliteParentOf(n),
          order: i,
        })),
      ];
      const satLayout = layoutKnowledgeGraph({
        nodes: satLayoutNodes,
        edges: satLayoutNodes.filter((n) => n.parentId)
          .map((n, i) => ({ id: `s${i}`, source: n.parentId as string, target: n.id, type: "related_to" as never })),
      });
      const satPos = new Map(satLayout.nodes.map((n) => [n.id, n]));
      const pal = paletteForAgent(name);
      const memberSet = new Set(satLayoutNodes.map((n) => n.id));
      const satNodes: Knowledge3dRenderNode[] = satLayoutNodes.map((ln) => {
        const pp = satPos.get(ln.id);
        const role = ln.role as never as ("root" | "section" | "claim");
        const subject = role === "root" || role === "section";
        const noteMeta = all.find((n) => n.id === ln.id);
        return {
          id: ln.id, x: pp?.x ?? 0.5, y: pp?.y ?? 0.5, depth: pp?.depth,
          role, parentId: pp?.parentId,
          radius: knowledgeNodeRadius(role, 1, false, pp?.depth),
          subject,
          core: nodeCoreColor(pal, subject ? role : undefined, noteMeta?.status),
          dark: pal.dark,
          ring: subject || autoCurated.has(ln.id) ? pal.ring : "rgba(0,0,0,0)",
          glow: subject ? pal.glow : "rgba(0,0,0,0)",
          ringScale: knowledgeSubjectRingScale(pp?.depth),
          ringWidth: knowledgeSubjectRingWidth(subject ? role : undefined, pp?.depth),
          glowScale: subject ? knowledgeSubjectGlowScale(role, pp?.depth) : 1,
          alpha: knowledgeNodeBaseAlpha(subject ? role : undefined, pp?.depth, "hot"),
          autoCurated: autoCurated.has(ln.id),
        };
      });
      const satelliteLinks = visibleArticleLinks(linkPairs, satelliteArticleIds, identityRef,
        new Set(navigationGroup.article_refs ?? []));
      reviewScopes.set(name, { articleIds: satelliteArticleIds, agentRef: identityRef,
        scopeRefs: new Set(navigationGroup.article_refs ?? []), links: satelliteLinks,
        edgeColorEnd: () => pal.core });
      const satEdges: Knowledge3dRenderEdge[] = [
        ...satLayoutNodes.filter((n) => n.parentId)
          .map((n) => ({ source: n.parentId as string, target: n.id, taxonomy: true, color: pal.core })),
        ...withoutTaxonomyLinks(satelliteLinks, satLayoutNodes)
          .map((l) => ({ source: l.source, target: l.target, taxonomy: false,
                         color: knowledgeAmbientEdgeStroke(false, false, pal), colorEnd: pal.core })),
      ];
      for (const ref of memberSet) {
        const n = all.find((x) => x.id === ref);
        titles.current.set(`agent:${name}/${ref}`,
          n ? n.title
            : (ref === identityRef ? navigationGroup.title
              : satelliteSubjects.find((subject) => subject.id === ref)?.title ?? ref));
      }
      return {
        agentId: name,
        nodes: satNodes,
        edges: satEdges,
        tuning: satelliteTunings[name] ?? loadGraphTuning(name),
      };
    });
    // The Library is the shared green satellite. Tool nodes represent the
    // one-to-one Tool+Skill pairs beside Tasks; synthesized Runbooks remain on
    // their owning agents.
    const libraryGroup = graph.navigation.groups.find((group) => group.id === "library");
    const libraryMembers = graphArticleIds(libraryGroup, displayAliases);
    const absorbedLibraryRefs = new Set((libraryGroup?.subjects ?? []).flatMap((subject) =>
      subject.article_ref ? [subject.article_ref] : []));
    const libraryNotes = all.filter((node) => libraryMembers.has(displayAliases.get(node.id) ?? node.id)
      && !absorbedLibraryRefs.has(node.id)
      && node.kind !== "skill");
    const libraryRoot = libraryGroup?.root_ref ?? "@library";
    const libraryTitle = libraryGroup?.title ?? "Library";
    const librarySubjects = libraryGroup?.subjects ?? [];
    const librarySubjectByKind = new Map<string, string>([
      ["tool", librarySubjects.find((subject) => subject.id === "@library/Tools")?.id ?? libraryRoot],
      ["task", librarySubjects.find((subject) => subject.id === "@library/Tasks")?.id ?? libraryRoot],
      ["runbook", librarySubjects.find((subject) => subject.id === "@library/Runbooks")?.id ?? libraryRoot],
      ["agent", librarySubjects.find((subject) => subject.id === "@library/Agents")?.id ?? libraryRoot],
    ]);
    const libraryParents = hierarchyParents(libraryNotes);
    const libraryContainers = new Set(libraryParents.values());
    const libraryArticleIds = new Set(all.filter(isArticleEndpoint)
      .map((node) => displayAliases.get(node.id) ?? node.id).filter((id) => libraryMembers.has(id)));
    const libraryLayoutNodes = [
      { id: libraryRoot, degree: libraryNotes.length, kind: "concept" as never, label: libraryTitle, role: "root" as never, parentId: null as string | null, order: 0 },
      ...librarySubjects.map((subject, index) => ({
        id: subject.id,
        degree: libraryNotes.filter((node) =>
          librarySubjectByKind.get(primitiveKindOf(node) ?? "") === subject.id).length,
        kind: "concept" as never,
        label: subject.title,
        role: "section" as never,
        parentId: subject.parent_id ?? libraryRoot,
        order: index,
      })),
      ...libraryNotes.map((node, index) => ({
        id: node.id,
        degree: 0,
        kind: "note" as never,
        label: node.title,
        role: (libraryContainers.has(node.id) ? "section" : "claim") as never,
        parentId: libraryParents.get(node.id) ??
          librarySubjects.find((subject) => subject.path === node.id.split("/").slice(0, -1).join("/"))?.id ??
          librarySubjectByKind.get(primitiveKindOf(node) ?? node.kind) ?? libraryRoot,
        order: index,
      })),
    ];
    const libraryLayout = layoutKnowledgeGraph({
      nodes: libraryLayoutNodes,
      edges: libraryLayoutNodes.filter((node) => node.parentId).map((node, index) => ({
        id: `l${index}`, source: node.parentId as string, target: node.id, type: "related_to" as never,
      })),
    });
    const libraryPositions = new Map(libraryLayout.nodes.map((node) => [node.id, node]));
    const libraryPalette = paletteForAgent("library");
    const librarySet = new Set(libraryLayoutNodes.map((node) => node.id));
    const libraryRenderNodes: Knowledge3dRenderNode[] = libraryLayoutNodes.map((node) => {
      const point = libraryPositions.get(node.id);
      const role = node.role as never as ("root" | "section" | "claim");
      const subject = role === "root" || role === "section";
      const noteMeta = libraryNotes.find((note) => note.id === node.id);
      return {
        id: node.id, x: point?.x ?? 0.5, y: point?.y ?? 0.5, depth: point?.depth,
        role, parentId: point?.parentId,
        radius: knowledgeNodeRadius(role, 1, false, point?.depth),
        subject,
        core: nodeCoreColor(libraryPalette, subject ? role : undefined, noteMeta?.status),
        dark: libraryPalette.dark,
        ring: subject || autoCurated.has(node.id) ? libraryPalette.ring : "rgba(0,0,0,0)",
        glow: subject ? libraryPalette.glow : "rgba(0,0,0,0)",
        ringScale: knowledgeSubjectRingScale(point?.depth),
        ringWidth: knowledgeSubjectRingWidth(subject ? role : undefined, point?.depth),
        glowScale: subject ? knowledgeSubjectGlowScale(role, point?.depth) : 1,
        alpha: knowledgeNodeBaseAlpha(subject ? role : undefined, point?.depth, "hot"),
        autoCurated: autoCurated.has(node.id),
      };
    });
    const libraryLinks = visibleArticleLinks(linkPairs, libraryArticleIds);
    reviewScopes.set("library", { articleIds: libraryArticleIds, scopeRefs: libraryArticleIds,
      links: libraryLinks, edgeColorEnd: () => libraryPalette.core });
    const libraryRenderEdges: Knowledge3dRenderEdge[] = [
      ...libraryLayoutNodes.filter((node) => node.parentId).map((node) => ({
        source: node.parentId as string, target: node.id, taxonomy: true, color: libraryPalette.core,
      })),
      ...withoutTaxonomyLinks(libraryLinks, libraryLayoutNodes).map((link) => ({
        source: link.source, target: link.target, taxonomy: false,
        color: knowledgeAmbientEdgeStroke(false, false, libraryPalette), colorEnd: libraryPalette.core,
      })),
    ];
    for (const ref of librarySet) {
      const note = libraryNotes.find((node) => node.id === ref);
      const subject = librarySubjects.find((candidate) => candidate.id === ref);
      titles.current.set(`agent:library/${ref}`, note
        ? note.title
        : (ref === libraryRoot ? libraryTitle : subject?.title ?? ref));
    }
    const librarySatellite = {
      agentId: "library",
      nodes: libraryRenderNodes,
      edges: libraryRenderEdges,
      tuning: satelliteTunings.library ?? loadGraphTuning("library"),
    };
    const satellites = [...agentSatellites, librarySatellite];
    const labelMetadata = new Map<string, Knowledge3dLabelMeta>();
    for (const node of renderNodes) {
      const branch = firstLevelBranchOf(node.id) ?? "brain";
      const palette = paletteOf(node.id);
      labelMetadata.set(node.id, {
        label: titles.current.get(node.id) ?? node.id,
        role: node.role === "root" || node.role === "section" ? node.role : "claim",
        depth: node.depth ?? 0,
        branch: branch.toLowerCase(),
        radius: node.radius,
        accent: palette.core,
        accentSoft: palette.ring,
      });
    }
    for (const satellite of satellites) {
      const palette = paletteForAgent(satellite.agentId);
      for (const node of satellite.nodes) {
        const id = knowledgeAgentNodeId(satellite.agentId, node.id);
        labelMetadata.set(id, {
          label: titles.current.get(id) ?? node.id,
          role: node.role === "root" || node.role === "section" ? node.role : "claim",
          depth: node.depth ?? 0,
          branch: satellite.agentId === "library" ? "knowledge" : "agent",
          radius: node.radius,
          accent: palette.core,
          accentSoft: palette.ring,
        });
      }
    }
    return { nodes: renderNodes, edges: renderEdges, satellites, labelMetadata, reviewScopes, articleLinks: linkPairs };
  }, [graph, displayAliases, hub, satelliteTunings, viewport, tuning]);

  // Only the Scene receives the visual spring preview. Thinking paths, Reader
  // selection and accepted graph state continue to use the accepted model.
  const presentation = useMemo(() => {
    const links = [...model.articleLinks, ...projectedArticleLinks(linkProposals.entries, displayAliases)];
    const project = <T extends GraphCloud>(cloud: T, graphId: string): T => {
      const scope = model.reviewScopes.get(graphId);
      if (!scope) return cloud;
      const union = visibleArticleLinks(links, scope.articleIds, scope.agentRef, scope.scopeRefs);
      return previewLinkReviewCloud(cloud, scope.links, union, graphId === MAIN_GRAPH_ID, scope.edgeColorEnd);
    };
    const main = project(model, MAIN_GRAPH_ID);
    const satellites = model.satellites.map((cloud) => project(cloud, cloud.agentId));
    const labelMetadata = new Map(model.labelMetadata);
    for (const node of main.nodes) {
      const label = labelMetadata.get(node.id);
      if (label) labelMetadata.set(node.id, { ...label, radius: node.radius });
    }
    return { nodes: main.nodes, edges: main.edges, satellites, labelMetadata };
  }, [model, linkProposals, displayAliases]);

  useEffect(() => onGraphThinkingTest((graphId) => {
    testTimers.current.forEach((timer) => window.clearTimeout(timer));
    testTimers.current = [];
    if (satelliteTestTimer.current !== null) {
      window.clearTimeout(satelliteTestTimer.current);
      satelliteTestTimer.current = null;
    }
    setActivity(null);
    setSatelliteTest(null);
    const cloud = graphId === MAIN_GRAPH_ID
      ? model
      : model.satellites.find((satellite) => satellite.agentId === graphId);
    if (!cloud) return;
    const leaves = cloud.nodes.filter((node) => node.role === "claim");
    const pool = leaves.length > 0 ? leaves : cloud.nodes.filter((node) => node.role !== "root");
    if (pool.length === 0) return;
    const target = pool[Math.floor(Math.random() * pool.length)];
    const route = buildThinkingRoute(cloud, [target.id]);
    if (!route) return;
    activityKey.current += 1;
    const key = activityKey.current;
    if (graphId !== MAIN_GRAPH_ID) {
      // Satellite tests use the cloud's own non-held sweep timeline and do not
      // wake the Executive retrieval path.
      setSatelliteTest({ agentId: graphId, route, key });
      satelliteTestTimer.current = window.setTimeout(() => {
        setSatelliteTest((current) => current?.key === key ? null : current);
        satelliteTestTimer.current = null;
      }, 14_000);
      return;
    }
    // Obsidience starts the thinking state immediately, admits the real path at
    // 750 ms, flips to speaking at 3.2 s, and then gives the resolved path its
    // six-second readable linger after the 5.8 s synthetic turn ends.
    setActivity({ refs: [], phase: "thinking", key, graphId, query: "Thinking test", startedAt: Date.now() });
    testTimers.current.push(window.setTimeout(() => {
      setActivity((current) => current?.key === key
        ? { ...current, refs: [target.id], phase: "thinking" }
        : current);
    }, 750));
    testTimers.current.push(window.setTimeout(() => {
      setActivity((current) => current?.key === key ? { ...current, phase: "speaking" } : current);
    }, 3_200));
    testTimers.current.push(window.setTimeout(() => {
      setActivity((current) => current?.key === key ? null : current);
      testTimers.current = [];
    }, 11_800));
  }), [model]);

  const renderedActivityRefs = useMemo(() => {
    const executiveRef = graph.navigation.groups.find((group) => group.id === "executive")?.root_ref;
    return (activity?.refs ?? []).map((ref) =>
      ref === executiveRef && (!activity?.graphId || activity.graphId === MAIN_GRAPH_ID)
        ? ROOT_ID : displayAliases.get(ref) ?? ref);
  }, [activity?.refs, activity?.graphId, displayAliases, graph.navigation]);
  const mainRoute = useMemo(() => {
    if (!activity || (activity.graphId && activity.graphId !== MAIN_GRAPH_ID)) return null;
    return buildThinkingRoute(model, renderedActivityRefs);
  }, [activity, model, renderedActivityRefs]);
  const effectiveSweepSpeed = useMemo(() => {
    if (
      tuning.automaticSweepSpeed < 0.5
      || !mainRoute
      || !activity?.retrievalMs
      || activity.retrievalMs <= 0
    ) return tuning.sweepSpeed;
    const pathSpec = mainRoute.pathSpec;
    const routeProgress = pathSpec.maxProgress + knowledge3dSweepTail(pathSpec);
    // Deliberately no elapsed-time clamp: the measured fast-context duration
    // is the animation rate. The manual slider owns speed only when automatic
    // mode is unchecked.
    return routeProgress / (activity.retrievalMs / 1_000);
  }, [activity?.retrievalMs, mainRoute, tuning.automaticSweepSpeed, tuning.sweepSpeed]);
  const effectiveTuning = useMemo(
    () => effectiveSweepSpeed === tuning.sweepSpeed
      ? tuning
      : { ...tuning, sweepSpeed: effectiveSweepSpeed },
    [effectiveSweepSpeed, tuning],
  );
  const [focusProgress, setFocusProgress] = useState(0);
  const focusProgressRef = useRef(0);
  useEffect(() => {
    if (!activity || !mainRoute) {
      focusProgressRef.current = 0;
      setFocusProgress(0);
      return;
    }
    if (!visible) return;
    const startedAt = performance.now();
    const base = focusProgressRef.current;
    const pathSpec = mainRoute.pathSpec;
    const tick = (now: number) => {
      const value = knowledgeSweepProgress3d(
        activity.phase,
        now - startedAt,
        base,
        effectiveSweepSpeed,
        pathSpec.maxProgress,
        knowledge3dSweepTail(pathSpec),
      );
      focusProgressRef.current = value;
      setFocusProgress((previous) =>
        Math.abs(previous - value) > 0.004 || value >= pathSpec.maxProgress
          ? value
          : previous);
    };
    tick(startedAt);
    let frame = window.requestAnimationFrame(function animate(now) {
      tick(now);
      frame = window.requestAnimationFrame(animate);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activity?.key, activity?.phase, effectiveSweepSpeed, mainRoute, visible]);
  const gatedMainNodeIds = useMemo(() => {
    if (!mainRoute) return new Set<string>();
    const pathSpec = mainRoute.pathSpec;
    const gateProgress = focusProgress - pathSpec.firstNodeProgress + 1e-6;
    const allNodeIds = new Set([...mainRoute.nodeIds, ...pathSpec.nodeArrival.keys()]);
    if (gateProgress >= pathSpec.maxProgress) return allNodeIds;
    return new Set([...allNodeIds].filter(
      (id) => (pathSpec.nodeArrival.get(id) ?? 1) <= gateProgress));
  }, [focusProgress, mainRoute]);
  const satelliteRoutes = useMemo(() => {
    if (satelliteTest) return [{
      agentId: satelliteTest.agentId,
      spec: satelliteTest.route.pathSpec,
      nodeIds: satelliteTest.route.nodeIds,
      key: satelliteTest.key,
      hold: false,
    }];
    if (!activity?.graphId || activity.graphId === MAIN_GRAPH_ID) return [];
    const satellite = model.satellites.find((entry) => entry.agentId === activity.graphId);
    if (!satellite) return [];
    const route = buildThinkingRoute(satellite, renderedActivityRefs);
    const automaticSpeed = (
      route
      && satellite.tuning.automaticSweepSpeed >= 0.5
      && activity.retrievalMs
      && activity.retrievalMs > 0
    ) ? (
      route.pathSpec.maxProgress + knowledge3dSweepTail(route.pathSpec)
    ) / (activity.retrievalMs / 1_000) : undefined;
    return route ? [{
      agentId: satellite.agentId,
      spec: route.pathSpec,
      nodeIds: route.nodeIds,
      key: activity.key,
      hold: true,
      speed: automaticSpeed,
    }] : [];
  }, [activity, model.satellites, satelliteTest, renderedActivityRefs]);

  const selected = selectedId ? parseKnowledgeAgentNodeId(selectedId) : null;
  const cameraFocus = selected ? {
    agentId: selected.agentId,
    nodeId: selected.nodeId,
  } : null;
  const selectNode = (id: string, read: boolean) => {
    const parsed = parseKnowledgeAgentNodeId(id);
    setSelectedId(id);
    setNodeMenu(null);
    selectGraph(parsed.agentId ?? MAIN_GRAPH_ID);
    if (read) openReader(graph.nodes.find((node) => node.id === parsed.nodeId)?.article_ref ?? parsed.nodeId,
      parsed.agentId ?? MAIN_GRAPH_ID);
  };
  const clearSelection = () => {
    setSelectedId(null);
    setNodeMenu(null);
    selectGraph(MAIN_GRAPH_ID);
  };
  const highlightedId = lockMode ? null : hoveredId ?? selectedId;
  const menuParsed = nodeMenu ? parseKnowledgeAgentNodeId(nodeMenu.id) : null;
  const menuNode = menuParsed
    ? graph.nodes.find((node) => node.id === menuParsed.nodeId) ?? null
    : null;
  const labelIds = useMemo(() => {
    const ordered: string[] = [];
    const add = (id: string | null | undefined) => {
      if (id && !ordered.includes(id)) ordered.push(id);
    };
    add(hoveredId);
    add(selectedId);
    if (activity) {
      for (const ref of renderedActivityRefs) {
        if (!activity.graphId || activity.graphId === MAIN_GRAPH_ID) add(ref);
        if (activity.graphId && activity.graphId !== MAIN_GRAPH_ID) add(knowledgeAgentNodeId(activity.graphId, ref));
      }
      for (const id of gatedMainNodeIds) add(id);
      for (const route of satelliteRoutes) {
        for (const id of route.nodeIds) add(knowledgeAgentNodeId(route.agentId, id));
      }
    }
    return lockMode ? [] : ordered;
  }, [activity, gatedMainNodeIds, hoveredId, lockMode, renderedActivityRefs, satelliteRoutes, selectedId]);

  const relationEffects = useMemo(() => projectLinkReviewEffects(
    linkProposals.entries, linkApprovals, graph.links, displayAliases,
    [{ agentId: "main", nodes: presentation.nodes, edges: presentation.edges }, ...presentation.satellites], performance.now(),
    proposalStarts.current,
  ), [linkProposals, linkApprovals, graph.links, displayAliases, presentation]);
  const pendingLinkCount = new Set(relationEffects.filter((effect) => effect.phase === "pending").map((effect) => effect.id)).size;
  const approvedLinkCount = new Set(relationEffects.filter((effect) => effect.phase === "approved").map((effect) => effect.id)).size;

  return (
    <div className="absolute inset-0">
      <Knowledge3dScene
          key={sceneKey}
          nodes={presentation.nodes}
          edges={presentation.edges}
          hub={hub}
          focusNodeIds={mainRoute?.nodeIds ?? new Set<string>()}
          pathSpec={mainRoute?.pathSpec ?? null}
          focusActive={Boolean(activity)}
          focusPhase={activity ? activity.phase : null}
          speechEnvelope={visible && !lockMode ? speechEnvelope : undefined}
          visible={visible}
          reducedMotion={false}
          adapterPreference="system"
          animationProfile="maximum"
          hoveredNodeId={highlightedId}
          labelIds={labelIds}
          activeLabelNodeIds={lockMode ? new Set<string>() : gatedMainNodeIds}
          labelMetadata={presentation.labelMetadata}
          tuning={effectiveTuning}
          satellites={presentation.satellites}
          relationEffects={relationEffects}
          satelliteSweeps={satelliteRoutes}
          cameraFocus={lockMode ? null : cameraFocus}
          onBackgroundClick={lockMode ? undefined : clearSelection}
          onHover={lockMode ? undefined : setHoveredId}
          onNodeAction={(kind, id, at) => {
            if (lockMode) return;
            if (kind === "click") selectNode(id, true);
            else setNodeMenu({ id, x: at.x, y: at.y });
          }}
          onContextLost={() => setSceneKey((k) => k + 1)}
      />
      {!lockMode && visible && (pendingLinkCount > 0 || approvedLinkCount > 0 || linkProposals.truncated) ? (
        <div role="status" aria-live="polite" data-testid="link-review-status"
          className="pointer-events-none absolute bottom-5 left-5 z-20 rounded-md border border-slate-500/25 bg-[#030a10]/85 px-3 py-2 font-mono text-[11px] shadow-lg">
          {pendingLinkCount > 0 ? <p className="text-amber-300"><span aria-hidden="true">┄ </span>{pendingLinkCount} {pendingLinkCount === 1 ? "link" : "links"} awaiting review · glowing preview</p> : null}
          {approvedLinkCount > 0 ? <p className="text-cyan-200"><span aria-hidden="true">✦ </span>{approvedLinkCount} {approvedLinkCount === 1 ? "link approved" : "links approved"}</p> : null}
          {linkProposals.truncated ? <p className="mt-1 text-slate-400">Review links incomplete · see Reviews</p> : null}
        </div>
      ) : null}
      {!lockMode && visible && (traceInspectionSince !== null || (activity && activity.startedAt !== traceDismissedSince)) ? (
        <ActionTracePopup since={traceInspectionSince ?? activity!.startedAt}
          keptOpen={traceInspectionSince !== null}
          onKeepOpen={(keep) => setTraceInspectionSince(keep ? (traceInspectionSince ?? activity?.startedAt ?? null) : null)}
          onClose={() => {
            setTraceInspectionSince(null);
            setTraceDismissedSince(activity?.startedAt ?? null);
          }} />
      ) : null}
      {!lockMode && nodeMenu ? (
        <NodeActionMenu
          menu={nodeMenu}
          title={titles.current.get(nodeMenu.id) ?? menuParsed?.nodeId ?? nodeMenu.id}
          canEdit={menuNode?.kind === "task" && !menuNode.synthetic}
          onSelect={() => selectNode(nodeMenu.id, false)}
          onRead={() => selectNode(nodeMenu.id, true)}
          onClose={() => setNodeMenu(null)}
          onClear={clearSelection}
        />
      ) : null}
    </div>
  );
}
