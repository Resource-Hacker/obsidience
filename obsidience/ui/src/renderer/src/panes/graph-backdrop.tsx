/** The Executive graph: the Obsidience 3D engine fed by the live vault using the
 *  hierarchy layout, paint pipeline, and owner's tuning.
 *  Structure: root "Executive" -> knowledge branches -> notes, plus literal
 *  agent satellites and the separate curated Library satellite. The Library
 *  never enters the Executive article tree. Wikilinks render as cross-link
 *  tendrils distinct from hierarchy edges. */

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  Knowledge3dScene,
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
import { DEFAULT_KNOWLEDGE_HUB_ANCHOR } from "@/components/themes/obsidience/knowledge-geometry";
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
  type GraphNavigationGroup,
  type GraphNode,
  type KnowledgeActivity,
} from "@/lib/api";
import {
  MAIN_GRAPH_ID,
  loadGraphTuning,
  onGraphThinkingTest,
  onGraphTuning,
  selectGraph,
} from "@/lib/graph-tuning";

const ROOT_ID = "@vault";
const FOCUS_LINGER_MS = 6_000;

interface ActivityWireEntry {
  phase?: KnowledgeActivity["phase"];
  refs?: string[];
  query?: string;
  graph_id?: string;
  at?: number;
  retrieval_ms?: number;
}

interface ActivityWireMessage extends ActivityWireEntry {
  type?: "activity" | "snapshot";
  entries?: ActivityWireEntry[];
}

function activityFromWire(entry: ActivityWireEntry): KnowledgeActivity | null {
  if (!entry.phase) return null;
  return {
    phase: entry.phase,
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
function latestActivityTransaction(entries: ActivityWireEntry[]): KnowledgeActivity[] {
  const activity = entries.map(activityFromWire).filter((entry): entry is KnowledgeActivity => entry !== null);
  let startIndex = -1;
  for (let index = activity.length - 1; index >= 0; index -= 1) {
    if (activity[index].phase === "query_started") {
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
    if ((entry.graphId ?? MAIN_GRAPH_ID) !== graphId || (entry.query ?? "") !== query) continue;
    if (entry.phase === "path") path = entry;
    else if (entry.phase === "speaking") speaking = entry;
    else if (entry.phase === "query_completed" || entry.phase === "cleared") terminal = entry;
  }
  // A start-only snapshot needs no replay: the server subscribes before it
  // snapshots, so its canonical path will arrive as the next live frame.
  if (path === null) return [];
  if (terminal?.phase === "cleared") return [];
  if (terminal?.at !== undefined && Date.now() - terminal.at >= FOCUS_LINGER_MS) return [];
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
  links: Array<{ source: string; target: string }>;
  auto_curated: string[];
  navigation: GraphNavigation;
}

/** The API has no ephemeral graph fields. Canonicalize only the unordered
 * top-level collections; authored child arrays stay ordered and therefore
 * remain meaningful hierarchy changes. */
function graphSnapshotFingerprint(snapshot: VaultGraphSnapshot): string {
  return JSON.stringify({
    nodes: [...snapshot.nodes].sort((left, right) => left.id.localeCompare(right.id)),
    links: [...snapshot.links].sort((left, right) =>
      left.source.localeCompare(right.source) || left.target.localeCompare(right.target)),
    auto_curated: [...snapshot.auto_curated].sort(),
    navigation: snapshot.navigation,
  });
}

function cascadedAutoCurated(
  seeds: ReadonlySet<string>,
  nodes: ReadonlyArray<{ id: string; parentId?: string | null }>,
): Set<string> {
  const result = new Set([...seeds].filter((id) => nodes.some((node) => node.id === id)));
  let changed = true;
  while (changed) {
    changed = false;
    for (const node of nodes) {
      if (node.parentId && result.has(node.parentId) && !result.has(node.id)) {
        result.add(node.id);
        changed = true;
      }
    }
  }
  return result;
}

/** Cross-link tendrils are relationships between leaf articles only. Index
 * notes still supply readable hierarchy hubs, but their navigational links
 * must never be painted as article-to-article evidence. */
function isArticleEndpoint(node: GraphNode, hierarchyContainers: ReadonlySet<string>): boolean {
  const basename = node.id.split("/").pop()?.toLowerCase();
  const hasChildren = (node.children?.length ?? 0) > 0;
  const tags = node.tags ?? [];
  return node.kind !== "agent"
    && node.id.toLowerCase() !== "home"
    && basename !== "index"
    && basename !== "readme"
    && !tags.includes("index-hub")
    && !hierarchyContainers.has(node.id)
    && !hasChildren;
}

interface ProjectedLabelMeta {
  label: string;
  role: "root" | "section" | "claim";
  depth: number;
  branch: string;
  radius: number;
  accent: string;
  accentSoft: string;
}

function projectedLabelStyle(meta: ProjectedLabelMeta): CSSProperties {
  return {
    "--obsidience-knowledge-accent": meta.accent,
    "--obsidience-knowledge-accent-soft": meta.accentSoft,
  } as CSSProperties;
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
  const nodeIds = new Set<string>();
  const activeEdgeIds = new Set<string>();
  for (const target of targets) {
    let cursor: string | null | undefined = target;
    const seen = new Set<string>();
    while (cursor && byId.has(cursor) && !seen.has(cursor)) {
      seen.add(cursor);
      nodeIds.add(cursor);
      const edge = taxonomyEdgeByChild.get(cursor);
      if (edge) activeEdgeIds.add(edge.id);
      cursor = byId.get(cursor)?.parentId;
    }
  }
  const root = cloud.nodes.find((node) => node.role === "root");
  if (!root) return null;
  nodeIds.add(root.id);
  // Obsidience's test continues through the reached path's real relationships;
  // this is the characteristic branching tail that makes the animation show
  // graph retrieval rather than a single decorative root-to-leaf line.
  for (const edge of edges) {
    if (edge.taxonomy || (!nodeIds.has(edge.source) && !nodeIds.has(edge.target))) continue;
    activeEdgeIds.add(edge.id);
    nodeIds.add(edge.source);
    nodeIds.add(edge.target);
  }
  const activeEdges = edges.filter((edge) => activeEdgeIds.has(edge.id));
  if (activeEdges.length === 0) return null;
  const positions = new Map(cloud.nodes.map((node) => [node.id, { x: node.x, y: node.y }]));
  const plan = computeKnowledgeSweepPlan(
    root.id,
    [...nodeIds],
    activeEdges.map((edge) => edge.id),
    edges,
    positions,
    new Set(targets),
  );
  return { nodeIds, pathSpec: knowledge3dPathSpec(plan, edges) };
}

interface NodeMenuState { id: string; x: number; y: number }
interface ActiveThinking {
  refs: string[];
  phase: "thinking" | "speaking";
  key: number;
  graphId?: string;
  query?: string;
  retrievalMs?: number;
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

function labelLines(label: string, maximumLineLength = 24): string[] {
  const normalized = label.trim().replace(/\s+/gu, " ");
  if (normalized.length <= maximumLineLength || !normalized.includes(" ")) return [normalized];
  const words = normalized.split(" ");
  let split = 1;
  let best = Number.POSITIVE_INFINITY;
  for (let index = 1; index < words.length; index += 1) {
    const longest = Math.max(words.slice(0, index).join(" ").length, words.slice(index).join(" ").length);
    if (longest < best) { best = longest; split = index; }
  }
  return [words.slice(0, split).join(" "), words.slice(split).join(" ")];
}

/** Obsidience's ambient label contract: the resting graph stays geometric;
 *  hover/selection and the transient thinking path get projected word tags. */
function ProjectedGraphLabels({ ids, activeIds, projected, metadata, width, height }: {
  ids: readonly string[];
  activeIds: ReadonlySet<string>;
  projected: ReadonlyMap<string, { x: number; y: number }>;
  metadata: ReadonlyMap<string, ProjectedLabelMeta>;
  width: number;
  height: number;
}) {
  const activeNodes = [...activeIds].flatMap((id) => {
    const point01 = projected.get(id);
    const meta = metadata.get(id);
    if (!point01 || !meta || meta.role === "root") return [];
    return [{ id, meta, point: { x: point01.x * width, y: point01.y * height } }];
  });
  const occupied: Array<{ left: number; right: number; top: number; bottom: number }> = [];
  const labels = ids.slice(0, 18).flatMap((id) => {
    const point01 = projected.get(id);
    const meta = metadata.get(id);
    if (!point01 || !meta || point01.x < -0.05 || point01.x > 1.05 || point01.y < -0.05 || point01.y > 1.05) return [];
    const point = { x: point01.x * width, y: point01.y * height };
    const lines = labelLines(meta.label, meta.role === "root" ? 28 : 24);
    // SVG's actual monospace advance also includes role-specific letter
    // spacing. These conservative widths and the extra horizontal inset keep
    // the final glyph from touching or clipping through the capsule edge.
    const characterWidth = meta.role === "root" ? 10.7 : meta.role === "section" ? 7.35 : 7;
    const textWidth = Math.max(...lines.map((line) => line.length)) * characterWidth;
    const boxWidth = Math.max(48, textWidth + 24);
    const boxHeight = lines.length * 13 + 10;
    const outward = point.x >= width / 2 ? 1 : -1;
    const offset = meta.role === "root" ? 36 : meta.role === "section" ? 30 : 18;
    let centerX = meta.role === "root" ? point.x : point.x + outward * (offset + boxWidth / 2);
    let centerY = meta.role === "root" ? point.y - offset - boxHeight / 2 : point.y - 6;
    centerX = Math.max(boxWidth / 2 + 8, Math.min(width - boxWidth / 2 - 8, centerX));
    centerY = Math.max(boxHeight / 2 + 8, Math.min(height - boxHeight / 2 - 8, centerY));
    let bounds = { left: centerX - boxWidth / 2, right: centerX + boxWidth / 2, top: centerY - boxHeight / 2, bottom: centerY + boxHeight / 2 };
    for (let lane = 0; lane < 10 && occupied.some((other) => !(bounds.right + 4 < other.left || bounds.left - 4 > other.right || bounds.bottom + 4 < other.top || bounds.top - 4 > other.bottom)); lane += 1) {
      centerY = Math.max(boxHeight / 2 + 8, Math.min(height - boxHeight / 2 - 8, centerY + (lane % 2 === 0 ? 1 : -1) * (Math.floor(lane / 2) + 1) * 28));
      bounds = { left: centerX - boxWidth / 2, right: centerX + boxWidth / 2, top: centerY - boxHeight / 2, bottom: centerY + boxHeight / 2 };
    }
    occupied.push(bounds);
    const endX = Math.max(bounds.left, Math.min(bounds.right, point.x));
    const endY = Math.max(bounds.top, Math.min(bounds.bottom, point.y));
    const deltaX = endX - point.x;
    const deltaY = endY - point.y;
    const distance = Math.max(1, Math.hypot(deltaX, deltaY));
    const startRadius = meta.role === "root" ? 22 : meta.role === "section" ? 16 : 9;
    return [{ id, meta, point, lines, bounds, centerX, centerY, endX, endY,
      startX: point.x + deltaX / distance * Math.min(distance, startRadius),
      startY: point.y + deltaY / distance * Math.min(distance, startRadius) }];
  });
  return (
    <svg className="pointer-events-none absolute inset-0 z-10 h-full w-full" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <g>
        {activeNodes.map((entry, index) => {
          const radius = entry.meta.radius + (entry.meta.role === "claim" ? 4 : 3);
          return (
            <g key={`active:${entry.id}`} className="obsidience-knowledge-active-node"
              data-knowledge-branch={entry.meta.branch} data-knowledge-depth={entry.meta.depth}
              style={projectedLabelStyle(entry.meta)}>
              <circle cx={entry.point.x} cy={entry.point.y} r={radius + 7}
                className="obsidience-knowledge-node-wave"
                style={{ animationDelay: `${-(index % 5) * 0.72}s` }} />
              <circle cx={entry.point.x} cy={entry.point.y} r={radius}
                className="obsidience-knowledge-node-focus" />
            </g>
          );
        })}
      </g>
      {labels.map((entry) => entry.meta.role === "root" ? null : (
        <line key={`leader:${entry.id}`} x1={entry.startX} y1={entry.startY} x2={entry.endX} y2={entry.endY}
          className="obsidience-knowledge-label-leader obsidience-knowledge-label-leader--active"
          data-knowledge-branch={entry.meta.branch} style={projectedLabelStyle(entry.meta)} />
      ))}
      {labels.map((entry, index) => (
        <g key={entry.id} className={`obsidience-knowledge-tag obsidience-knowledge-tag--active obsidience-knowledge-tag--${entry.meta.role}`}
          data-knowledge-branch={entry.meta.branch} data-knowledge-depth={entry.meta.depth}
          style={{ ...projectedLabelStyle(entry.meta), animationDelay: `${Math.min(index, 16) * 18}ms` }}>
          <rect x={entry.bounds.left} y={entry.bounds.top} width={entry.bounds.right - entry.bounds.left}
            height={entry.bounds.bottom - entry.bounds.top} rx={entry.meta.depth === 1 ? 3 : 2} className="obsidience-knowledge-tag-shell" />
          <line x1={entry.bounds.left + 3} y1={entry.bounds.top + 4} x2={entry.bounds.left + 3}
            y2={entry.bounds.bottom - 4} className="obsidience-knowledge-tag-accent" />
          <text x={entry.centerX} y={entry.centerY - (entry.lines.length - 1) * 6 + 4} textAnchor="middle"
            className={`obsidience-knowledge-label obsidience-knowledge-label--active obsidience-knowledge-label--${entry.meta.role}`}>
            {entry.lines.map((line, lineIndex) => <tspan key={`${entry.id}:${lineIndex}`} x={entry.centerX} dy={lineIndex === 0 ? 0 : 13}>{line}</tspan>)}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function GraphBackdrop() {
  const [graph, setGraph] = useState<VaultGraphSnapshot>({
    nodes: [], links: [], auto_curated: [], navigation: { groups: [] },
  });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [nodeMenu, setNodeMenu] = useState<NodeMenuState | null>(null);
  const [activity, setActivity] = useState<ActiveThinking | null>(null);
  const [sceneKey, setSceneKey] = useState(0);
  const [projected, setProjected] = useState<Map<string, { x: number; y: number }>>(new Map());
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight });
  const titles = useRef(new Map<string, string>());
  const graphFingerprint = useRef<string | null>(null);
  const activityKey = useRef(0);
  const lingerTimer = useRef<number | null>(null);
  const testTimers = useRef<number[]>([]);
  const satelliteTestTimer = useRef<number | null>(null);
  const [satelliteTest, setSatelliteTest] = useState<SatelliteThinkingTest | null>(null);
  const [tuning, setTuning] = useState<Knowledge3dTuning>(() => loadGraphTuning(MAIN_GRAPH_ID));
  const [satelliteTunings, setSatelliteTunings] = useState<Record<string, Knowledge3dTuning>>({});

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
    const connect = () => {
      if (stopped) return;
      socket = new WebSocket(`${WS_BASE}/ws/activity`);
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data as string) as ActivityWireMessage;
          if (message.type === "activity") {
            const activity = activityFromWire(message);
            if (activity) announceKnowledgeActivity(activity);
          } else if (message.type === "snapshot" && Array.isArray(message.entries)) {
            latestActivityTransaction(message.entries).forEach(announceKnowledgeActivity);
          }
        } catch { /* malformed activity frames are ignored */ }
      };
      socket.onclose = () => {
        socket = null;
        if (!stopped) retry = window.setTimeout(connect, 1_000);
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry !== null) window.clearTimeout(retry);
      socket?.close();
    };
  }, []);

  useEffect(() => onKnowledgeActivity((next: KnowledgeActivity) => {
    if (lingerTimer.current !== null) window.clearTimeout(lingerTimer.current);
    if (next.phase === "cleared") {
      setActivity(null);
      return;
    }
    if (next.phase === "query_started") {
      activityKey.current += 1;
      setActivity({
        refs: [], phase: "thinking", key: activityKey.current, query: next.query,
        retrievalMs: next.retrievalMs, graphId: next.graphId,
      });
      return;
    }
    if (next.phase === "path") {
      activityKey.current += 1;
      setActivity({
        refs: next.refs, phase: "thinking", key: activityKey.current, query: next.query,
        retrievalMs: next.retrievalMs, graphId: next.graphId,
      });
      return;
    }
    if (next.phase === "speaking") {
      setActivity((current) => ({
        refs: next.refs.length > 0 ? next.refs : (current?.refs ?? []),
        phase: "speaking",
        key: current?.key ?? ++activityKey.current,
        query: next.query ?? current?.query,
        retrievalMs: next.retrievalMs ?? current?.retrievalMs,
        graphId: next.graphId ?? current?.graphId,
      }));
      return;
    }
    setActivity((current) => current ? { ...current, phase: "speaking" } : null);
    const elapsed = next.at === undefined ? 0 : Math.max(0, Date.now() - next.at);
    const remaining = Math.max(0, FOCUS_LINGER_MS - elapsed);
    if (remaining === 0) {
      setActivity(null);
      return;
    }
    lingerTimer.current = window.setTimeout(() => setActivity(null), remaining);
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
    const pull = () => api.graph().then((next) => {
      if (!live) return;
      const snapshot: VaultGraphSnapshot = {
        nodes: next.nodes,
        links: next.links,
        auto_curated: next.auto_curated ?? [],
        navigation: next.navigation,
      };
      const fingerprint = graphSnapshotFingerprint(snapshot);
      // Preserve array/object identity across no-op polls. The Obsidience scene
      // keys cloud reuse on those identities; replacing an unchanged snapshot
      // reheats every force simulation and visibly pops the entire graph.
      if (fingerprint === graphFingerprint.current) return;
      graphFingerprint.current = fingerprint;
      setGraph(snapshot);
    }).catch(() => undefined);
    pull();
    const t = setInterval(pull, 15_000);
    window.addEventListener("obsidience:graph-refresh", pull);
    return () => {
      live = false;
      clearInterval(t);
      window.removeEventListener("obsidience:graph-refresh", pull);
    };
  }, []);

  const model = useMemo(() => {
    const all = graph.nodes;
    const autoCuratedSeeds = new Set(graph.auto_curated);
    const executiveGroup = graph.navigation.groups.find((group) => group.id === "executive");
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
    const assigneeOf = (n: GraphNode): string | null => {
      const m = /Agents\/([^\]|/]+)/.exec(n.assignee ?? "");
      return m ? m[1] : null;
    };
    const subRef = (raw: string, pool: Set<string>): string | null => {
      const clean = raw.trim().replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0].split("#")[0];
      if (pool.has(clean)) return clean;
      const base = clean.split("/").pop()!.toLowerCase();
      for (const id of pool) if (id.split("/").pop()!.toLowerCase() === base) return id;
      return null;
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
    const allIds = new Set(all.map((node) => node.id));
    const checkoutIdsOf = (identity?: GraphNode): Set<string> => new Set(
      Object.values(identity?.checkouts ?? {}).flatMap((values) => values ?? [])
        .map((raw) => subRef(raw, allIds)).filter((ref): ref is string => Boolean(ref)),
    );
    const libraryKinds = new Set(["tool", "task"]);
    const primitiveFolderByKind: Record<string, string> = {
      tool: "Tools", skill: "Skills", runbook: "Runbooks", task: "Tasks",
    };
    const primitiveNotes = all.filter((n) => Boolean(primitiveKindOf(n))
      && !(n.kind === "skill" && !n.synthetic));
    const libraryNotes = primitiveNotes.filter((node) =>
      libraryKinds.has(primitiveKindOf(node) ?? ""));
    const hierarchyClosure = (roots: Set<string>): Set<string> => {
      const pool = new Set(primitiveNotes.map((node) => node.id));
      const byId = new Map(primitiveNotes.map((node) => [node.id, node]));
      const closure = new Set([...roots].filter((ref) => pool.has(ref)));
      const queue = [...closure];
      while (queue.length) {
        const parent = byId.get(queue.shift() as string);
        if (!parent) continue;
        for (const raw of childRefsOf(parent)) {
          const child = subRef(raw, pool);
          if (!child || closure.has(child) ||
              primitiveKindOf(byId.get(child) as GraphNode) !== primitiveKindOf(parent)) continue;
          closure.add(child);
          queue.push(child);
        }
      }
      const parentOf = hierarchyParents(primitiveNotes);
      for (const ref of [...closure]) {
        let cursor = ref;
        while (parentOf.has(cursor)) {
          cursor = parentOf.get(cursor) as string;
          if (closure.has(cursor)) break;
          closure.add(cursor);
        }
      }
      return closure;
    };
    // Shared Tool+Skill pairs and Tasks belong to the curated Library satellite.
    // Runbooks are synthesized per agent; all four primitive kinds project on
    // an agent only when that identity carries them.
    const executiveCheckouts = hierarchyClosure(
      checkoutIdsOf(all.find((node) => node.id === "Agents/Executive/Executive")),
    );
    const executivePrimitives = primitiveNotes.filter((node) => executiveCheckouts.has(node.id));
    const executiveParents = hierarchyParents(executivePrimitives);
    const executiveContainers = new Set(executiveParents.values());
    const agentIdentities = all.filter((node) => node.kind === "agent"
      && node.id.startsWith("Agents/") && node.id !== "Agents/Executive/Executive");
    const notes = [
      ...all.filter((n) => (!n.id.startsWith("Agents/") || n.id.startsWith("Agents/Executive/"))
        && !n.id.startsWith("Sources/")
        && n.id !== "Library" && !n.id.startsWith("Library/") && !n.id.startsWith("@library/")
        && !primitiveKindOf(n) && n.id !== "Agents/Executive/Executive"),
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
        && !primitiveFolders.includes(folder))
      .sort();
    const folderPaths = [...new Set(notes.flatMap((node) => {
      if (agentIdentities.includes(node) || primitiveKindOf(node)) return [];
      const parts = node.id.split("/").slice(0, -1);
      if (parts.length < 2 || parts[0] === "Agents") return [];
      return parts.slice(1).map((_part, index) => parts.slice(0, index + 2).join("/"));
    }))].sort();

    const degree = new Map<string, number>();
    const executiveArticleIds = new Set(notes
      .filter((node) => isArticleEndpoint(node, executiveContainers))
      .map((node) => node.id));
    const crossLinks = graph.links.filter((link) =>
      executiveArticleIds.has(link.source) && executiveArticleIds.has(link.target));
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
    const mainAutoCurated = cascadedAutoCurated(autoCuratedSeeds, layoutNodes);
    const taxonomyEdges = layoutNodes
      .filter((n) => n.parentId)
      .map((n, i) => ({ id: `t${i}`, source: n.parentId as string, target: n.id, type: "related_to" as never }));
    const crossEdges = crossLinks.filter((link) => executiveParents.get(link.target) !== link.source).map((l, i) => ({
      id: `x${i}`, source: l.source, target: l.target, type: "related_to" as never,
    }));

    const layout = layoutKnowledgeGraph({
      anchor: DEFAULT_KNOWLEDGE_HUB_ANCHOR,
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
        ring: subject ? palette.ring : "rgba(0,0,0,0)",
        glow: subject ? palette.glow : "rgba(0,0,0,0)",
        ringScale: knowledgeSubjectRingScale(p.depth),
        ringWidth: knowledgeSubjectRingWidth(role, p.depth),
        glowScale: subject ? knowledgeSubjectGlowScale(role, p.depth) : 1,
        alpha: knowledgeNodeBaseAlpha(role, p.depth, "hot"),
        autoCurated: mainAutoCurated.has(p.id),
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
    // ---- satellites: one ball per agent, seeded by its own mini hierarchy ----
    const linkPairs = graph.links;
    const agentSatellites = agentNames.map((name) => {
      const navigationGroup = agentGroupByName.get(name) as GraphNavigationGroup;
      const identityRef = navigationGroup.root_ref;
      const satelliteSubjects = navigationGroup.subjects;
      const satelliteSubjectByKey = new Map(satelliteSubjects.map((subject) => [
        subject.id.slice(subject.id.lastIndexOf("/") + 1), subject,
      ]));
      const satelliteSubjectId = (key: string): string =>
        satelliteSubjectByKey.get(key)?.id ?? identityRef;
      const assigned = new Set(all.filter((node) => node.kind === "task" && assigneeOf(node) === name)
        .map((node) => node.id));
      const checkedOut = hierarchyClosure(new Set([
        ...checkoutIdsOf(all.find((node) => node.id === identityRef)),
        ...assigned,
      ]));
      const localMembers = all.filter((n) =>
        (n.id.startsWith(`Agents/${name}/`) && n.id !== identityRef) ||
        checkedOut.has(n.id) ||
        (name === "Darwin" && n.id.startsWith("Sources/")
          && !["readme", "index"].includes(n.id.split("/").pop()?.toLowerCase() ?? "")));
      const otherAgentMembers = [
        ...all.filter((node) => node.kind === "agent" && node.id !== identityRef),
      ];
      const members = [...localMembers, ...otherAgentMembers.filter((node) => !localMembers.includes(node))];
      const primitiveMembers = members.filter((member) => Boolean(primitiveKindOf(member)));
      const primitiveParents = hierarchyParents(primitiveMembers);
      const primitiveContainers = new Set(primitiveParents.values());
      const satelliteArticleIds = new Set(members
        .filter((node) => isArticleEndpoint(node, primitiveContainers))
        .map((node) => node.id));
      const satelliteParentOf = (node: GraphNode): string => {
        const primitiveParent = primitiveParents.get(node.id);
        if (primitiveParent) return primitiveParent;
        const primitiveKind = primitiveKindOf(node);
        if (primitiveKind) return satelliteSubjectId(primitiveFolderByKind[primitiveKind].toLowerCase());
        if (otherAgentMembers.includes(node)) return satelliteSubjectId("other-agents");
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
      const satelliteAutoCurated = cascadedAutoCurated(autoCuratedSeeds, satLayoutNodes);
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
          ring: subject ? pal.ring : "rgba(0,0,0,0)",
          glow: subject ? pal.glow : "rgba(0,0,0,0)",
          ringScale: knowledgeSubjectRingScale(pp?.depth),
          ringWidth: knowledgeSubjectRingWidth(subject ? role : undefined, pp?.depth),
          glowScale: subject ? knowledgeSubjectGlowScale(role, pp?.depth) : 1,
          alpha: knowledgeNodeBaseAlpha(subject ? role : undefined, pp?.depth, "hot"),
          autoCurated: satelliteAutoCurated.has(ln.id),
        };
      });
      const satEdges: Knowledge3dRenderEdge[] = [
        ...satLayoutNodes.filter((n) => n.parentId)
          .map((n) => ({ source: n.parentId as string, target: n.id, taxonomy: true, color: pal.core })),
        ...linkPairs.filter((link) =>
          satelliteArticleIds.has(link.source) && satelliteArticleIds.has(link.target))
          .filter((l) => primitiveParents.get(l.target) !== l.source)
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
    const libraryRoot = libraryGroup?.root_ref ?? "@library";
    const libraryTitle = libraryGroup?.title ?? "Library";
    const librarySubjects = libraryGroup?.subjects ?? [];
    const librarySubjectByKind = new Map<string, string>([
      ["tool", librarySubjects.find((subject) => subject.id === "@library/Tools")?.id ?? libraryRoot],
      ["task", librarySubjects.find((subject) => subject.id === "@library/Tasks")?.id ?? libraryRoot],
    ]);
    const libraryParents = hierarchyParents(libraryNotes);
    const libraryContainers = new Set(libraryParents.values());
    const libraryArticleIds = new Set(libraryNotes
      .filter((node) => isArticleEndpoint(node, libraryContainers))
      .map((node) => node.id));
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
          librarySubjectByKind.get(primitiveKindOf(node) ?? "") ?? libraryRoot,
        order: index,
      })),
    ];
    const libraryAutoCurated = cascadedAutoCurated(autoCuratedSeeds, libraryLayoutNodes);
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
        ring: subject ? libraryPalette.ring : "rgba(0,0,0,0)",
        glow: subject ? libraryPalette.glow : "rgba(0,0,0,0)",
        ringScale: knowledgeSubjectRingScale(point?.depth),
        ringWidth: knowledgeSubjectRingWidth(subject ? role : undefined, point?.depth),
        glowScale: subject ? knowledgeSubjectGlowScale(role, point?.depth) : 1,
        alpha: knowledgeNodeBaseAlpha(subject ? role : undefined, point?.depth, "hot"),
        autoCurated: libraryAutoCurated.has(node.id),
      };
    });
    const libraryRenderEdges: Knowledge3dRenderEdge[] = [
      ...libraryLayoutNodes.filter((node) => node.parentId).map((node) => ({
        source: node.parentId as string, target: node.id, taxonomy: true, color: libraryPalette.core,
      })),
      ...linkPairs.filter((link) =>
        libraryArticleIds.has(link.source) && libraryArticleIds.has(link.target))
        .filter((link) => libraryParents.get(link.target) !== link.source).map((link) => ({
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
    const labelMetadata = new Map<string, ProjectedLabelMeta>();
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
    return { nodes: renderNodes, edges: renderEdges, satellites, labelMetadata };
  }, [graph, satelliteTunings, viewport, tuning]);

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
      // Obsidience satellite tests use the cloud's own non-held sweep timeline;
      // they do not wake the Executive path or its whole-map breathing drift.
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
    setActivity({ refs: [], phase: "thinking", key, graphId, query: "Thinking test" });
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

  const mainRoute = useMemo(() => {
    if (!activity || (activity.graphId && activity.graphId !== MAIN_GRAPH_ID)) return null;
    return buildThinkingRoute(model, activity.refs);
  }, [activity, model]);
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
  }, [activity?.key, activity?.phase, effectiveSweepSpeed, mainRoute]);
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
    const route = buildThinkingRoute(satellite, activity.refs);
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
  }, [activity, model.satellites, satelliteTest]);

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
    if (read) openReader(parsed.nodeId);
  };
  const clearSelection = () => {
    setSelectedId(null);
    setNodeMenu(null);
    selectGraph(MAIN_GRAPH_ID);
  };
  const highlightedId = hoveredId ?? selectedId;
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
      for (const ref of activity.refs) {
        if (!activity.graphId || activity.graphId === MAIN_GRAPH_ID) add(ref);
        if (activity.graphId && activity.graphId !== MAIN_GRAPH_ID) add(knowledgeAgentNodeId(activity.graphId, ref));
      }
      for (const id of gatedMainNodeIds) add(id);
      for (const route of satelliteRoutes) {
        for (const id of route.nodeIds) add(knowledgeAgentNodeId(route.agentId, id));
      }
    }
    return ordered;
  }, [activity, gatedMainNodeIds, hoveredId, satelliteRoutes, selectedId]);

  return (
    <div className="absolute inset-0" data-knowledge-focus={activity ? "active" : "default"} data-knowledge-visible="true">
      <div className="obsidience-knowledge-map absolute inset-0" style={{
        "--obsidience-knowledge-hub-x": `${DEFAULT_KNOWLEDGE_HUB_ANCHOR.x * 100}%`,
        "--obsidience-knowledge-hub-y": `${DEFAULT_KNOWLEDGE_HUB_ANCHOR.y * 100}%`,
      } as CSSProperties}>
        <Knowledge3dScene
          key={sceneKey}
          nodes={model.nodes}
          edges={model.edges}
          hub={DEFAULT_KNOWLEDGE_HUB_ANCHOR}
          focusNodeIds={mainRoute?.nodeIds ?? new Set<string>()}
          pathSpec={mainRoute?.pathSpec ?? null}
          focusActive={Boolean(activity)}
          focusPhase={activity ? activity.phase : null}
          visible
          reducedMotion={false}
          adapterPreference="system"
          animationProfile="maximum"
          hoveredNodeId={highlightedId}
          tuning={effectiveTuning}
          satellites={model.satellites}
          satelliteSweeps={satelliteRoutes}
          cameraFocus={cameraFocus}
          onBackgroundClick={clearSelection}
          onHover={setHoveredId}
          onNodeAction={(kind, id, at) => {
            if (kind === "click") selectNode(id, true);
            else setNodeMenu({ id, x: at.x, y: at.y });
          }}
          onProjected={setProjected}
          onContextLost={() => setSceneKey((k) => k + 1)}
        />
        <ProjectedGraphLabels ids={labelIds} activeIds={gatedMainNodeIds}
          projected={projected} metadata={model.labelMetadata}
          width={viewport.width} height={viewport.height} />
      </div>
      {activity?.refs.length ? (
        <div className="pointer-events-none absolute left-5 top-16 max-w-[34rem] rounded border border-violet-300/20 bg-[#030a10]/75 px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.16em] text-violet-200/75 backdrop-blur">
          {activity.phase === "thinking" ? "consulting" : "resolved"} · {activity.refs.length} graph article{activity.refs.length === 1 ? "" : "s"}
          {activity.query ? <span className="ml-2 normal-case tracking-normal text-cyan-100/55">{activity.query}</span> : null}
        </div>
      ) : null}
      {nodeMenu ? (
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
