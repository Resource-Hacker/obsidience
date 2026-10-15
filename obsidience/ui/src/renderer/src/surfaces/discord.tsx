/** Discord-only camera presentation: the existing Knowledge cloud and real
 * run-correlated activity, without Shell controls, trace or conversation UI. */
import { useEffect, useMemo, useState } from "react";
import type { GraphNavigationGroup, GraphNode, GraphLink } from "@/lib/api";
import { Knowledge3dScene, type Knowledge3dLabelMeta } from "@/graph/knowledge/knowledge-3d-scene";
import { DEFAULT_KNOWLEDGE_3D_TUNING } from "@/graph/knowledge/knowledge-3d";
import { agentSatellite } from "@/graph/knowledge-stage/satellites";
import { buildThinkingRoute } from "@/graph/knowledge-stage/thinking-route";
import { currentOperations, operationAccent, type GraphOperation } from "@/graph/knowledge-stage/graph-activity";
import "@/styles/provider-graph.css";

type PublicGraph = { revision?: string; available: boolean; nodes: GraphNode[]; links: GraphLink[]; group: GraphNavigationGroup | null };
type Run = { refs: string[] };
const EMPTY: PublicGraph = { available: false, nodes: [], links: [], group: null };
const TUNING = { ...DEFAULT_KNOWLEDGE_3D_TUNING, sweepSpeed: 1 / 1.6 };

export function DiscordGraphSurface() {
  const [graph, setGraph] = useState<PublicGraph>(EMPTY);
  const [runs, setRuns] = useState<Map<string, Run>>(new Map());
  const [operations, setOperations] = useState<GraphOperation[]>([]);
  const [connected, setConnected] = useState(false);
  const [sceneKey, setSceneKey] = useState(0);

  useEffect(() => {
    // Capture readiness attests only that this dedicated surface mounted.
    // Agent admission and live graph availability remain separate states.
    document.documentElement.dataset.discordGraph = "ready";
    return () => { delete document.documentElement.dataset.discordGraph; };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.discordGraphData = graph.available ? "available" : "unavailable";
    return () => { delete document.documentElement.dataset.discordGraphData; };
  }, [graph.available]);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    const clear = () => { setConnected(false); setRuns(new Map()); setOperations([]); setGraph(EMPTY); };
    const connect = () => {
      if (disposed) return;
      const url = new URL("/api/discord/presentation/activity", window.location.href);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(url);
      socket.onmessage = (event) => {
        if (disposed || typeof event.data !== "string" || event.data.length > 1024 * 1024) return;
        try {
          const value = JSON.parse(event.data);
          if (value.type === "graph") {
            const next = value.graph as PublicGraph;
            if (!next || !Array.isArray(next.nodes) || next.nodes.length > 512
              || !Array.isArray(next.links) || next.links.length > 1024) return;
            setGraph(current => current.revision && current.revision === next.revision ? current : next);
            setRuns(new Map()); setOperations([]); setConnected(true);
          } else if (value.type === "activity" && value.graph_id === "discord"
            && typeof value.run_id === "string" && Array.isArray(value.refs)) {
            setRuns(current => {
              const next = new Map(current);
              if (value.phase === "query_completed" || value.phase === "cleared") next.delete(value.run_id);
              else if (value.phase === "query_started" || value.phase === "path") {
                next.set(value.run_id, { refs: [...new Set<string>([...(next.get(value.run_id)?.refs ?? []),
                  ...value.refs.filter((ref: unknown): ref is string => typeof ref === "string")])].slice(0, 128) });
              }
              return next;
            });
          } else if (value.type === "operation" && value.operation?.graph_id === "discord") {
            setOperations(current => currentOperations([...current, value.operation]).slice(-64));
          }
        } catch { /* Invalid presentation data cannot fall back to broader APIs. */ }
      };
      socket.onclose = () => { if (!disposed) { clear(); reconnect = setTimeout(connect, 2000); } };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => { disposed = true; clearTimeout(reconnect); socket?.close(); };
  }, []);

  const model = useMemo(() => {
    const titles = new Map<string, string>();
    if (!graph.available || !graph.group) return { nodes: [], edges: [], titles };
    const cloud = agentSatellite({ all: graph.nodes, displayAliases: new Map(), linkPairs: graph.links,
      autoCurated: new Set(), reviewScopes: new Map(), titles }, "Discord", graph.group);
    return { ...cloud, titles };
  }, [graph]);
  const liveOperations = useMemo(() => operations.filter(operation => runs.has(operation.run_id)), [operations, runs]);
  const refs = useMemo(() => [...new Set([...runs.values()].flatMap(run => run.refs)
    .concat(liveOperations.flatMap(operation => operation.refs)))], [runs, liveOperations]);
  const route = useMemo(() => buildThinkingRoute(model, refs, [...runs.values()].map(run => run.refs)), [model, refs, runs]);
  const labels = useMemo(() => {
    const result = new Map<string, Knowledge3dLabelMeta>();
    for (const node of model.nodes) result.set(node.id, {
      label: model.titles.get(`agent:Discord/${node.id}`) ?? "Article",
      role: node.role ?? "claim", depth: node.depth ?? 0, branch: "discord",
      radius: node.radius, accent: node.core,
    });
    return result;
  }, [model]);
  const accents = useMemo(() => {
    const result = new Map<string, { color: string; mode: number }>();
    for (const operation of liveOperations) {
      const accent = operationAccent(operation);
      if (accent) for (const ref of operation.refs) result.set(ref, accent);
    }
    return result;
  }, [liveOperations]);
  const active = runs.size > 0;
  return <div className="fixed inset-0 overflow-hidden bg-black"><main aria-label="Discord Agent knowledge presentation"
    data-obsidience-theme="obsidience" className="absolute overflow-hidden bg-[#030304] text-cyan-50"
    style={{ left: "50%", top: "50%", transform: "translate(-50%, -50%)",
      width: "min(100vw, 177.777778vh)", height: "min(100vh, 56.25vw)" }}>
    <Knowledge3dScene key={sceneKey} primaryGraphId="Discord" nodes={model.nodes} edges={model.edges} hub={{ x: 0.5, y: 0.5 }}
      focusNodeIds={route?.nodeIds ?? new Set()} passedNodeIds={route?.passedIds}
      pathSpec={route?.pathSpec ?? null} focusActive={active} focusPhase={active ? "thinking" : null}
      focusKey={[...runs.keys()].sort().join(":")} activityAccents={accents}
      visible={true} reducedMotion={false} adapterPreference="system" animationProfile="maximum"
      hoveredNodeId={null} labelIds={[]} showActivityLabels={true} labelMetadata={labels}
      tuning={TUNING} sharePresentation={false} onContextLost={() => setSceneKey(key => key + 1)} />
    <div className="pointer-events-none absolute left-8 top-6 font-mono uppercase tracking-[0.3em] text-cyan-100/80">
      <div className="text-sm">{graph.group?.title ?? "Obsidience Discord Bot"}</div>
      <div role="status" className="mt-2 text-[10px] tracking-[0.2em] text-cyan-100/45">
        {!connected ? "Presentation unavailable" : !graph.available ? "Agent unavailable" : active ? "Thinking" : "Idle"}
      </div>
    </div>
    {liveOperations.length > 0 && <div aria-label="Actual Tool and read activity"
      className="pointer-events-none absolute bottom-6 right-8 font-mono text-xs text-cyan-100/70">
      {liveOperations.filter(operation => operation.kind !== "context").slice(-4).map(operation =>
        <div key={operation.id} className="mt-1" style={{ color: operationAccent(operation)?.color }}>
          {operation.label} · {operation.status === "running" ? "Active" : operation.status}
        </div>)}
    </div>}
  </main></div>;
}
