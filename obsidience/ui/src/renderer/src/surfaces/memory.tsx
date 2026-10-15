import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api, type GraphOperation, type MemoryBank, type MemoryDelta, type ProviderGraph, type ProviderNode } from "@/lib/api";
import { subscribeActivity } from "@/lib/activity-client";
import { onShellOledPolicy, onShellProviderGraph, onShellStageVisibility, type ShellOledPolicy } from "@/lib/shell-client";
import { useSurfaceVisibility } from "@/lib/surface-visibility";
import { ProviderGraphScene } from "@/graph/memory/provider-graph-scene";
import { MemoryStagePresentation } from "@/graph/memory/memory-stage-presentation";
import { MEMORY_TYPES, type GraphControl } from "@/graph/stream";
import { knowledgeRoleForAgent, paintKnowledgeRoleIcon } from "@/graph/knowledge/knowledge-role-icons";
import "@/styles/provider-graph.css";

// A visible memory view replaces its incrementally patched graph at most hourly.
const MEMORY_RECONCILE_MS = 3600_000;
const edgeKey = (e: ProviderGraph["edges"][number]) => `${e.source}\0${e.target}\0${e.kind}\0${e.weight}\0${e.color}`;
/** Apply the Harness's changed records and edge multiset to the shown graph. */
function applyMemoryDelta(current: ProviderGraph, delta: MemoryDelta): ProviderGraph {
  if (!delta.nodes.length && !delta.removed.length && !delta.edges.length && !delta.removed_edges.length) return current;
  const changed = new Map(delta.nodes.map(n => [n.id, n])), removed = new Set(delta.removed);
  const nodes = current.nodes.filter(n => !removed.has(n.id)).map(n => {
    const next = changed.get(n.id);
    if (next) changed.delete(n.id);
    return next || n;
  });
  const drops = new Map<string, number>(), sources = new Set<string>();
  for (const e of delta.removed_edges) { const key = edgeKey(e); drops.set(key, (drops.get(key) || 0) + 1); sources.add(e.source); }
  const edges = current.edges.filter(e => {
    if (!sources.has(e.source)) return true;
    const key = edgeKey(e), count = drops.get(key);
    if (!count) return true;
    drops.set(key, count - 1); return false;
  });
  // New records lead, matching the provider's newest-first order.
  return {...current, nodes: [...changed.values(), ...nodes], edges: edges.concat(delta.edges),
    total: delta.total, limited: delta.limited, updated_at: delta.updated_at, revision: delta.revision};
}

/** The Samsung stage's Memory third: one row per Agent memory bank. */
export function MemoryStageWall() {
  const [banks, setBanks] = useState<MemoryBank[]>([]), [error, setError] = useState("");
  const [selectedBank, setSelectedBank] = useState("");
  const [presentation, setPresentation] = useState<MemoryStagePresentation | null>(null);
  const [oled, setOled] = useState<ShellOledPolicy>({ enabled: false, shiftPx: 32, travelSeconds: 3600 });
  const [shellVisible, setShellVisible] = useState(false);
  // Also false while the stage reports windows covering this view's region.
  const pageVisible = useSurfaceVisibility();
  useEffect(() => onShellOledPolicy(setOled), []);
  useEffect(() => onShellStageVisibility("samsung", setShellVisible), []);
  useEffect(() => {
    const owner = new MemoryStagePresentation(); setPresentation(owner);
    return () => owner.dispose();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    api.memoryBanks(controller.signal, selectedBank || undefined)
      .then(async result => {
        if (selectedBank && result.banks[0]?.scene === "executive") result = await api.memoryBanks(controller.signal);
        if (!controller.signal.aborted) {
          setBanks(result.banks); setError(result.banks.length ? "" : "No Agent memory banks are available yet.");
        }
      })
      .catch(() => { if (!controller.signal.aborted) setError("Agent memory banks are unavailable."); });
    return () => controller.abort();
  }, [selectedBank]);
  useEffect(() => onShellProviderGraph("memory", settings => {
    if (settings.bank) { presentation?.select(settings.bank); setSelectedBank(settings.bank); }
  }), [presentation]);
  return <main className="memory-stage-wall" aria-label="Agent memory scene"
    data-motion={shellVisible && pageVisible} data-oled={oled.enabled}
    style={{ "--oled-shift": `${oled.shiftPx}px`, "--oled-travel": `${oled.travelSeconds}s` } as CSSProperties}>
    {presentation && banks.map((bank, index) => <section className="memory-stage-row" key={bank.id} aria-label={`${bank.name} memory`}>
      <MemoryAgentIcon bank={bank} index={index}/>
      <MemoryStage bank={bank.id} banks={banks} memoryPresentation={presentation}/>
    </section>)}
    {error && <div className="pg-empty" role="status"><strong>Memory unavailable</strong><p>{error}</p></div>}
  </main>;
}

function MemoryAgentIcon({bank, index}: {bank: MemoryBank; index: number}) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const canvas = paintKnowledgeRoleIcon(knowledgeRoleForAgent(bank.agent_ref), 256);
    host.current?.appendChild(canvas);
    return () => canvas.remove();
  }, [bank.agent_ref]);
  return <div className="memory-agent-icon" ref={host} role="img" aria-label={bank.name} title={bank.name}
    style={{ "--icon-phase": `${-index * 17}s` } as CSSProperties}/>;
}

/** One bank's memory graph: loading, deltas, follow, activity and its share of the pane publisher. */
function MemoryStage({bank, banks, memoryPresentation}: {
  bank: string; banks: MemoryBank[]; memoryPresentation: MemoryStagePresentation;
}) {
  const host = useRef<HTMLDivElement>(null), scene = useRef<ProviderGraphScene | null>(null);
  const presentationFactory = useMemo(() => memoryPresentation.register(bank), [bank, memoryPresentation]);
  const [data, setData] = useState<ProviderGraph | null>(null), [loading, setLoading] = useState(false);
  const [error, setError] = useState(""), [revision, setRevision] = useState(0);
  const [memoryType, setMemoryType] = useState("all");
  const [selected, setSelected] = useState<ProviderNode | null>(null);
  const [timeRange, setTimeRange] = useState("");
  const [hover, setHover] = useState<{ node: ProviderNode; x: number; y: number } | null>(null);
  const [operations, setOperations] = useState<GraphOperation[]>([]), [connected, setConnected] = useState(false);
  const [follow, setFollow] = useState(true), [expanded, setExpanded] = useState<string[]>([]);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const visible = useSurfaceVisibility();
  const [consumers, setConsumers] = useState(0);
  const commandRef = useRef<(command: GraphControl) => void>(() => {});
  const followRef = useRef(follow), scope = useRef("");
  const lastFollow = useRef(""), refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Last complete or patched memory graph, its Harness revision and full-load time.
  const memoryCursor = useRef<{graph: ProviderGraph; full: number} | null>(null);
  const pickRef = useRef<(n: ProviderNode | null) => void>(() => {});
  followRef.current = follow;
  scope.current = data?.graph_id || "memory:" + bank;
  // An explicit refresh reloads the complete memory graph.
  const refresh = () => { memoryCursor.current = null; setRevision(r => r + 1); };

  useEffect(() => onShellProviderGraph("memory", settings => {
    if (settings.bank ? settings.bank !== bank : !memoryPresentation.isSelected(bank)) return;
    if (typeof settings.follow === "boolean") setFollow(settings.follow);
    if (settings.memoryType && (settings.memoryType === "all" || Object.hasOwn(MEMORY_TYPES, settings.memoryType))) setMemoryType(settings.memoryType);
    if (settings.refresh) refresh();
    if (settings.fit) {
      setSelected(null); setTimeRange(""); setExpanded([]); lastFollow.current = "";
      scene.current?.fit();
    }
  }), [bank, memoryPresentation]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    // Refreshes continue from the shown revision; the Harness sends the
    // complete graph on a cursor gap, a reset bank, or hourly reconciliation.
    const cursor = memoryCursor.current;
    const since = cursor?.graph.revision && cursor.graph.graph_id === "memory:" + bank
      && Date.now() - cursor.full < MEMORY_RECONCILE_MS ? cursor : null;
    api.memoryGraph(bank, since?.graph.revision, controller.signal).then(result => {
      if ("delta" in result) {
        if (since && result.since === since.graph.revision) {
          const graph = applyMemoryDelta(since.graph, result);
          memoryCursor.current = {graph, full: since.full};
          if (graph !== since.graph) setData(graph);
        } else { memoryCursor.current = null; setRevision(r => r + 1); }
        setLoading(false); return;
      }
      memoryCursor.current = {graph: result, full: Date.now()};
      setData(result);
      setLoading(false);
    }).catch(e => { if (!controller.signal.aborted) { setError(e.message); setLoading(false); } });
    return () => controller.abort();
  }, [bank, revision]);

  useEffect(() => {
    if (!host.current) return;
    try {
      scene.current = new ProviderGraphScene(host.current, n => pickRef.current(n),
        (node, x, y) => setHover(current => current?.node.id === node?.id ? current : node ? {node, x, y} : null),
        command => commandRef.current(command), setConsumers,
        {presentation: presentationFactory, timeGuides: false});
    } catch { setError("The 3D renderer could not start. Search and record details remain available."); }
    return () => { scene.current?.dispose(); scene.current = null; };
  }, [presentationFactory]);
  const rendering = visible || consumers > 0;
  const wasRendering = useRef(rendering);
  useEffect(() => scene.current?.setVisible(rendering), [rendering]);
  useEffect(() => {
    // A shown memory view catches up on writes it missed while covered.
    if (rendering && !wasRendering.current && memoryCursor.current) setRevision(r => r + 1);
    wasRendering.current = rendering;
  }, [rendering]);
  useEffect(() => {
    if (!rendering || !data) return;
    // An overdue view reconciles on its catch-up fetch when shown again.
    const due = (memoryCursor.current?.full || 0) + MEMORY_RECONCILE_MS - Date.now();
    if (due <= 0) return;
    const timer = setTimeout(() => setRevision(r => r + 1), due);
    return () => clearTimeout(timer);
  }, [rendering, data]);

  const coalesceRefresh = useCallback(() => {
    if (!refreshTimer.current) refreshTimer.current = setTimeout(() => {
      refreshTimer.current = null; setRevision(r => r + 1);
    }, 600);
  }, []);
  useEffect(() => {
    if (!rendering) return;
    function accept(op: GraphOperation, live: boolean) {
      if (!op || !Array.isArray(op.refs)) return;
      if (op.graph_id !== scope.current) return;
      setOperations(current => [op, ...current.filter(item => item.id !== op.id)].slice(0, 12));
      // Reconnect reconciles saved snapshots, but never replays camera activity.
      if (op.refresh && live) coalesceRefresh();
      if (live && followRef.current && op.refs.length && op.status !== "running") {
        // Background intake grows the timeline. Zooming to each new batch
        // hides the older days and makes a full history look like one cluster.
        if (["retain", "consolidate", "retire"].includes(op.kind)) {
          setExpanded([]); lastFollow.current = "timeline";
        } else {
          setExpanded(op.refs); lastFollow.current = op.id;
        }
      }
    }
    const stop = subscribeActivity({
      open: () => setConnected(true),
      message: frame => {
        if (frame.type === "snapshot") {
          for (const op of frame.operations || []) accept(op as GraphOperation, false);
        } else if (frame.type === "operation") accept(frame.operation as GraphOperation, true);
      },
      close: () => setConnected(false),
    });
    return () => { stop(); setConnected(false); };
  }, [rendering, bank, data?.graph_id, coalesceRefresh]);
  useEffect(() => () => { if (refreshTimer.current) clearTimeout(refreshTimer.current); }, []);

  // Memory records have no file or symbol aliases: a ref is the record's id.
  const activeIds = useMemo(() => {
    const wanted = new Set(expanded);
    return new Set((data?.nodes || []).filter(n => wanted.has(n.id)).map(n => n.id));
  }, [data, expanded]);
  const visibleIds = useMemo(() => {
    if (!data) return new Set<string>();
    return new Set(data.nodes.filter(n => n.id === selected?.id || activeIds.has(n.id)
      || memoryType === "all" || n.kind === memoryType).map(n => n.id));
  }, [data, memoryType, activeIds, selected?.id]);
  const visibleEdges = useMemo(() => data?.edges.filter(e => e.source !== e.target && visibleIds.has(e.source) && visibleIds.has(e.target)).length || 0, [data, visibleIds]);
  useEffect(() => {
    if (data) {
      scene.current?.setData(data, visibleIds);
      if (follow && lastFollow.current === "timeline" && !selected && !timeRange) scene.current?.fit();
    }
  }, [data, visibleIds, follow, selected, timeRange]);
  useEffect(() => {
    scene.current?.activity(operations);
  }, [operations, visibleIds]);
  useEffect(() => {
    scene.current?.select(selected?.id || "", timeRange);
  }, [selected, visibleIds, timeRange]);
  useEffect(() => {
    if (lastFollow.current && expanded.length && (follow || lastFollow.current === "selection")) {
      scene.current?.focus(expanded); lastFollow.current = "";
    }
  }, [expanded, visibleIds, follow]);

  pickRef.current = node => {
    setSelected(node); setTimeRange(""); setDetail(null);
    if (!node) { setExpanded([]); lastFollow.current = ""; }
  };
  const select = (node: ProviderNode) => { pickRef.current(node); setExpanded([node.id]); lastFollow.current = "selection"; };
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    api.memoryRecord(bank, selected.id.split("/").at(-1)!, controller.signal)
      .then(setDetail).catch(() => {});
    return () => controller.abort();
  }, [selected?.id, bank]);

  const neighbors = useMemo(() => {
    if (!selected || !data) return [];
    const byId = new Map(data.nodes.map(n => [n.id, n]));
    const seen = new Set<string>();
    return data.edges.filter(e => e.source === selected.id || e.target === selected.id).flatMap(e => {
      const id = e.source === selected.id ? e.target : e.source;
      if (id === selected.id || seen.has(id) || !byId.has(id)) return [];
      seen.add(id); return [{ node: byId.get(id)!, kind: e.kind }];
    }).slice(0, 24);
  }, [data, selected]);
  commandRef.current = command => {
    if (command.action === "select") { const node = data?.nodes.find(n => n.id === command.id); if (node) select(node); }
    else if (command.action === "clear") {
      setSelected(null); setTimeRange(""); setExpanded([]); lastFollow.current = "";
    }
    else if (command.action === "fit") {
      setSelected(null); setTimeRange(""); setExpanded([]); lastFollow.current = "";
      scene.current?.fit();
    }
    else if (command.action === "search" && typeof command.value === "string") scene.current?.search(command.value);
    else if (command.action === "timeRange" && typeof command.value === "string"
      && /^\d{4}-\d{2}-\d{2}\/\d{4}-\d{2}-\d{2}$/.test(command.value)) {
      const [from, to] = command.value.split("/");
      if (Number.isFinite(Date.parse(from)) && Number.isFinite(Date.parse(to)) && from <= to) {
        setSelected(null); setExpanded([]); lastFollow.current = ""; setTimeRange(command.value);
      }
    }
    else if (command.action === "refresh") refresh();
    else if (command.action === "memoryType" && (command.value === "all" || Object.hasOwn(MEMORY_TYPES, String(command.value)))) setMemoryType(String(command.value));
    else if (command.action === "follow" && typeof command.value === "boolean") setFollow(command.value);
  };
  useEffect(() => {
    scene.current?.presentation.publishCatalog({nodes: data?.nodes || [], count: data?.nodes.length || 0, links: data?.edges.length || 0,
      banks, limited: data?.limited});
  }, [data, banks]);
  useEffect(() => {
    scene.current?.presentation.publishState({bank, memoryType, follow, loading, error, connected, timeRange,
      count: visibleIds.size, links: visibleEdges,
      selected: selected && {...selected, ...data?.nodes.find(node => node.id === selected.id),
        text: typeof detail?.text === "string" ? detail.text : selected.text}, neighbors, hover: hover?.node || null, latest: operations[0]});
  }, [bank, memoryType, follow, loading, error, connected, selected, neighbors, hover?.node, operations, detail, visibleIds.size, visibleEdges, timeRange, data]);
  return <main className="provider-graph memory-graph provider-stage" aria-label="Memory graph stage">
    <div className="pg-workspace"><div className="pg-canvas" ref={host}/></div>
    {error && <div className="pg-empty" role="status"><strong>Memory unavailable</strong><p>{error}</p></div>}
  </main>;
}
