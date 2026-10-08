import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { onShellOledPolicy, onShellProviderGraph, onShellStageVisibility, type ShellOledPolicy } from "@/lib/shell-client";
import { ProviderGraphScene, type ProviderGraph, type ProviderNode, type GraphOperation } from "./provider-graph-scene";
import { GraphViewer } from "./graph-viewer";
import { MEMORY_TYPES, type GraphControl } from "./graph-stream";
import { CODE_STRUCTURE, codeLayoutAncestry, codeFileGraph } from "./code-spherical-layout";
import { knowledgeRoleForAgent, paintKnowledgeRoleIcon } from "@/components/themes/obsidience/knowledge-role-icons";
import { MemoryStagePresentation } from "./memory-stage-presentation";
import "./provider-graph.css";

const API = "http://127.0.0.1:8765";
// A visible memory view replaces its incrementally patched graph at most hourly.
const MEMORY_RECONCILE_MS = 3600_000;
type Bank = { id: string; name: string; agent_ref: string; count: number };
type MemoryDelta = Pick<ProviderGraph, "provider" | "graph_id" | "nodes" | "edges" | "total" | "limited" | "updated_at"> & {
  delta: true; since: string; revision: string; removed: string[]; removed_edges: ProviderGraph["edges"];
};
const NO_BANKS: Bank[] = [];
async function json<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(API + path, { signal });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail || `Provider returned ${r.status}`);
  }
  return r.json();
}
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
function aliases(data: ProviderGraph, refs: string[]): Set<string> {
  const wanted = new Set(refs), found = new Set<string>();
  for (const n of data.nodes) if (wanted.has(n.id) || (n.qualified_name && wanted.has("qn:" + n.qualified_name))
    || (n.kind === "File" && n.file && wanted.has("file:" + n.file))) found.add(n.id);
  return found;
}

export function ProviderGraphSurface() {
  const query = new URLSearchParams(location.search);
  return query.get("stage") === "1" ? query.get("surface") === "memory" ? <MemoryStageWall /> : <ProviderGraphStage />
    : <GraphViewer view={query.get("surface") === "code" ? "code" : "memory"} />;
}

function MemoryStageWall() {
  const [banks, setBanks] = useState<Bank[]>([]), [error, setError] = useState("");
  const [presentation, setPresentation] = useState<MemoryStagePresentation | null>(null);
  const [oled, setOled] = useState<ShellOledPolicy>({ enabled: false, shiftPx: 32, travelSeconds: 3600 });
  const [shellVisible, setShellVisible] = useState(false), [pageVisible, setPageVisible] = useState(!document.hidden);
  const [stageVisible, setStageVisible] = useState(true);
  useEffect(() => onShellOledPolicy(setOled), []);
  useEffect(() => onShellStageVisibility("samsung", setShellVisible), []);
  useEffect(() => {
    const changed = () => setPageVisible(!document.hidden);
    // The stage also reports when windows cover this view's own region.
    const stage = (event: MessageEvent) => {
      if (event.origin === location.origin && event.data?.type === "obsidience-stage-visibility")
        setStageVisible(event.data.visible === true);
    };
    document.addEventListener("visibilitychange", changed);
    window.addEventListener("message", stage);
    return () => { document.removeEventListener("visibilitychange", changed); window.removeEventListener("message", stage); };
  }, []);
  useEffect(() => {
    const owner = new MemoryStagePresentation(); setPresentation(owner);
    return () => owner.dispose();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    json<{banks: Bank[]}>("/api/graphs/memory/banks", controller.signal)
      .then(result => { setBanks(result.banks); if (!result.banks.length) setError("No Agent memory banks are available yet."); })
      .catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, []);
  useEffect(() => onShellProviderGraph("memory", settings => {
    if (settings.bank) presentation?.select(settings.bank);
  }), [presentation]);
  return <main className="memory-stage-wall" aria-label="All Agent memory graphs"
    data-motion={shellVisible && pageVisible && stageVisible} data-oled={oled.enabled}
    style={{ "--oled-shift": `${oled.shiftPx}px`, "--oled-travel": `${oled.travelSeconds}s` } as CSSProperties}>
    {presentation && banks.map((bank, index) => <section className="memory-stage-row" key={bank.id} aria-label={`${bank.name} memory`}>
      <MemoryAgentIcon bank={bank} index={index}/>
      <ProviderGraphStage fixedBank={bank.id} availableBanks={banks} memoryPresentation={presentation}/>
    </section>)}
    {error && <div className="pg-empty" role="status"><strong>Memory unavailable</strong><p>{error}</p></div>}
  </main>;
}

function MemoryAgentIcon({bank, index}: {bank: Bank; index: number}) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const canvas = paintKnowledgeRoleIcon(knowledgeRoleForAgent(bank.agent_ref), 256);
    host.current?.appendChild(canvas);
    return () => canvas.remove();
  }, [bank.agent_ref]);
  return <div className="memory-agent-icon" ref={host} role="img" aria-label={bank.name} title={bank.name}
    style={{ "--icon-phase": `${-index * 17}s` } as CSSProperties}/>;
}

function ProviderGraphStage({fixedBank, availableBanks, memoryPresentation}: {
  fixedBank?: string; availableBanks?: Bank[]; memoryPresentation?: MemoryStagePresentation;
}) {
  const code = new URLSearchParams(location.search).get("surface") === "code";
  const title = code ? "Code" : "Memory";
  const host = useRef<HTMLDivElement>(null), scene = useRef<ProviderGraphScene | null>(null);
  const [bank, setBank] = useState(fixedBank || "");
  const banks = availableBanks || NO_BANKS;
  const presentationFactory = useMemo(() => fixedBank && memoryPresentation ? memoryPresentation.register(fixedBank) : undefined,
    [fixedBank, memoryPresentation]);
  const [data, setData] = useState<ProviderGraph | null>(null), [loading, setLoading] = useState(false);
  const [error, setError] = useState(""), [revision, setRevision] = useState(0);
  const [allSymbols, setAllSymbols] = useState(false), [memoryType, setMemoryType] = useState("all");
  const [codeFileId, setCodeFileId] = useState(""), [followingFile, setFollowingFile] = useState("");
  const [indexState, setIndexState] = useState<ProviderGraph["index"]>();
  const [selected, setSelected] = useState<ProviderNode | null>(null);
  const [timeRange, setTimeRange] = useState("");
  const [hover, setHover] = useState<{ node: ProviderNode; x: number; y: number } | null>(null);
  const [operations, setOperations] = useState<GraphOperation[]>([]), [connected, setConnected] = useState(false);
  const [follow, setFollow] = useState(true), [expanded, setExpanded] = useState<string[]>([]);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null), [detailError, setDetailError] = useState("");
  const [visible, setVisible] = useState(!document.hidden);
  const [consumers, setConsumers] = useState(0);
  const commandRef = useRef<(command: GraphControl) => void>(() => {});
  const followRef = useRef(follow), scope = useRef("");
  const lastFollow = useRef(""), refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Last complete or patched memory graph, its Harness revision and full-load time.
  const memoryCursor = useRef<{graph: ProviderGraph; full: number} | null>(null);
  const pickRef = useRef<(n: ProviderNode | null) => void>(() => {});
  followRef.current = follow;
  scope.current = data?.graph_id || (code ? "" : "memory:" + bank);
  const back = () => {
    setCodeFileId(""); setFollowingFile(""); setSelected(null); setExpanded([]); lastFollow.current = "";
  };
  const refresh = () => {
    // An explicit refresh reloads the complete memory graph.
    if (!code) { memoryCursor.current = null; setRevision(r => r + 1); return; }
    setIndexState({state: "updating"});
    fetch(API + "/api/graphs/code/refresh", {method: "POST"}).then(async response => {
      if (!response.ok) throw new Error("Code index refresh could not start");
      setIndexState(await response.json());
    }).catch(error => setIndexState({state: "stale", error: error.message}));
  };

  useEffect(() => onShellProviderGraph(code ? "code" : "memory", settings => {
    if (fixedBank && (settings.bank ? settings.bank !== fixedBank : !memoryPresentation?.isSelected(fixedBank))) return;
    if (typeof settings.follow === "boolean") { setFollowingFile(""); setFollow(settings.follow); }
    if (code && typeof settings.allSymbols === "boolean") setAllSymbols(settings.allSymbols);
    if (!code && !fixedBank && settings.bank) setBank(settings.bank);
    if (!code && settings.memoryType && (settings.memoryType === "all" || Object.hasOwn(MEMORY_TYPES, settings.memoryType))) setMemoryType(settings.memoryType);
    if (settings.refresh) refresh();
    if (settings.fit) {
      if (code) { commandRef.current({action: "fit"}); return; }
      if (!code) { setSelected(null); setTimeRange(""); setExpanded([]); lastFollow.current = ""; }
      scene.current?.fit();
    }
  }), [code, fixedBank, memoryPresentation]);

  useEffect(() => {
    if (!code && !bank) return;
    const controller = new AbortController();
    setLoading(true); setError("");
    // Memory refreshes continue from the shown revision; the Harness sends
    // the complete graph on a cursor gap, a reset bank, or hourly reconciliation.
    const cursor = memoryCursor.current;
    const since = !code && cursor?.graph.revision && cursor.graph.graph_id === "memory:" + bank
      && Date.now() - cursor.full < MEMORY_RECONCILE_MS ? cursor : null;
    const path = code ? "/api/graphs/code" : "/api/graphs/memory?bank=" + encodeURIComponent(bank)
      + (since ? "&since=" + encodeURIComponent(since.graph.revision!) : "");
    json<ProviderGraph | MemoryDelta>(path, controller.signal).then(result => {
      if ("delta" in result) {
        if (since && result.since === since.graph.revision) {
          const graph = applyMemoryDelta(since.graph, result);
          memoryCursor.current = {graph, full: since.full};
          if (graph !== since.graph) setData(graph);
        } else { memoryCursor.current = null; setRevision(r => r + 1); }
        setLoading(false); return;
      }
      if (code) setIndexState(result.index);
      else memoryCursor.current = {graph: result, full: Date.now()};
      setData(current => code && current && ["updating", "stale"].includes(result.index?.state || "") ? current : result);
      setLoading(false);
    }).catch(e => { if (!controller.signal.aborted) { setError(e.message); setLoading(false); } });
    return () => controller.abort();
  }, [code, bank, revision]);

  useEffect(() => {
    setSelected(null); setTimeRange(""); setDetail(null); setExpanded([]); setOperations([]);
    setData(null); lastFollow.current = "";
  }, [bank]);

  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden && document.documentElement.dataset.paneVisible !== "false");
    const onPane = (event: Event) => {
      const value = (event as CustomEvent<boolean>).detail;
      document.documentElement.dataset.paneVisible = String(value); onVisibility();
    };
    const onStage = (event: MessageEvent) => {
      if (event.origin === location.origin && event.data?.type === "obsidience-stage-visibility") {
        document.documentElement.dataset.paneVisible = String(event.data.visible === true); onVisibility();
      }
    };
    window.addEventListener("message", onStage);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("obsidience-pane-visibility", onPane);
    onVisibility();
    return () => { window.removeEventListener("message", onStage); document.removeEventListener("visibilitychange", onVisibility); window.removeEventListener("obsidience-pane-visibility", onPane); };
  }, []);

  useEffect(() => {
    if (!host.current) return;
    try {
      scene.current = new ProviderGraphScene(host.current, code, n => pickRef.current(n),
        (node, x, y) => setHover(current => current?.node.id === node?.id ? current : node ? {node, x, y} : null),
        command => commandRef.current(command), setConsumers,
        {presentation: presentationFactory, timeGuides: !fixedBank});
    } catch { setError("The 3D renderer could not start. Search and record details remain available."); }
    return () => { scene.current?.dispose(); scene.current = null; };
  }, [code, presentationFactory, fixedBank]);
  const rendering = visible || consumers > 0;
  const wasRendering = useRef(rendering);
  useEffect(() => scene.current?.setVisible(rendering), [rendering]);
  useEffect(() => {
    // A shown memory view catches up on writes it missed while covered.
    if (rendering && !wasRendering.current && (code || memoryCursor.current)) setRevision(r => r + 1);
    wasRendering.current = rendering;
  }, [code, rendering]);
  useEffect(() => {
    if (code || !rendering || !data) return;
    // An overdue view reconciles on its catch-up fetch when shown again.
    const due = (memoryCursor.current?.full || 0) + MEMORY_RECONCILE_MS - Date.now();
    if (due <= 0) return;
    const timer = setTimeout(() => setRevision(r => r + 1), due);
    return () => clearTimeout(timer);
  }, [code, rendering, data]);

  const coalesceRefresh = useCallback(() => {
    if (!refreshTimer.current) refreshTimer.current = setTimeout(() => {
      refreshTimer.current = null; setRevision(r => r + 1);
    }, 600);
  }, []);
  useEffect(() => {
    if (!rendering) return;
    let socket: WebSocket | null = null, retry: ReturnType<typeof setTimeout> | null = null, disposed = false;
    function accept(op: GraphOperation, live: boolean) {
      if (!op || op.graph_id !== scope.current || !Array.isArray(op.refs)) return;
      setOperations(current => [op, ...current.filter(item => item.id !== op.id)].slice(0, 12));
      if (code && live && op.kind === "edit") setIndexState({state: "updating"});
      // Reconnect reconciles saved snapshots, but never replays camera activity.
      if (op.refresh && (live || code)) coalesceRefresh();
      if (live && followRef.current && op.refs.length && op.status !== "running") {
        // Background intake grows the timeline. Zooming to each new batch
        // hides the older days and makes a full history look like one cluster.
        if (!code && ["retain", "consolidate", "retire"].includes(op.kind)) {
          setExpanded([]); lastFollow.current = "timeline";
        } else {
          setExpanded(op.refs); lastFollow.current = op.id;
          if (code && op.kind === "edit") setFollowingFile(op.refs.find(ref => ref.startsWith("file:"))?.slice(5) || "");
        }
      }
    }
    function connect() {
      if (disposed) return;
      socket = new WebSocket(API.replace("http", "ws") + "/ws/activity");
      socket.onopen = () => setConnected(true);
      socket.onmessage = event => {
        let value; try { value = JSON.parse(event.data); } catch { return; }
        if (value.type === "snapshot") {
          for (const op of value.operations || []) accept(op, false);
        } else if (value.type === "operation") accept(value.operation, true);
      };
      socket.onclose = () => { setConnected(false); if (!disposed) retry = setTimeout(connect, 1500); };
      socket.onerror = () => socket?.close();
    }
    connect();
    return () => { disposed = true; if (retry) clearTimeout(retry); socket?.close(); setConnected(false); };
  }, [rendering, bank, code, data?.graph_id, coalesceRefresh]);
  useEffect(() => () => { if (refreshTimer.current) clearTimeout(refreshTimer.current); }, []);

  useEffect(() => {
    if (!code || !data) return;
    if (follow && followingFile) {
      const file = data.nodes.find(node => node.kind === "File" && node.file === followingFile);
      if (file) setCodeFileId(file.id);
    }
    if (codeFileId && !data.nodes.some(node => node.id === codeFileId)) back();
    setSelected(current => current ? data.nodes.find(node => node.id === current.id) || null : null);
  }, [data, code, follow, followingFile, codeFileId]);
  const viewData = useMemo(() => code && data && codeFileId ? codeFileGraph(data, codeFileId) || data : data, [code, data, codeFileId]);

  const activeIds = useMemo(() => data ? aliases(data, expanded) : new Set<string>(), [data, expanded]);
  const codeParents = useMemo(() => code && data ? codeLayoutAncestry(data).parents : new Map<string, string>(), [code, data]);
  const visibleIds = useMemo(() => {
    if (!viewData) return new Set<string>();
    const ids = new Set(viewData.nodes.filter(n => {
      if (n.id === selected?.id || activeIds.has(n.id)) return true;
      if (code) return !!viewData.code_root || allSymbols || CODE_STRUCTURE.has(n.kind);
      return memoryType === "all" || n.kind === memoryType;
    }).map(n => n.id));
    // Expanded symbols retain their exact containing path, without lighting it.
    if (code && !viewData.code_root) for (const id of ids) {
      let parent = codeParents.get(id);
      while (parent && !ids.has(parent)) { ids.add(parent); parent = codeParents.get(parent); }
    }
    return ids;
  }, [viewData, code, allSymbols, memoryType, activeIds, selected?.id, codeParents]);
  const visibleEdges = useMemo(() => viewData?.edges.filter(e => e.source !== e.target && visibleIds.has(e.source) && visibleIds.has(e.target)).length || 0, [viewData, visibleIds]);
  useEffect(() => {
    if (viewData) {
      scene.current?.setData(viewData, visibleIds);
      if (!code && follow && lastFollow.current === "timeline" && !selected && !timeRange) scene.current?.fit();
    }
  }, [viewData, visibleIds, code, follow, selected, timeRange]);
  useEffect(() => {
    scene.current?.activity(operations);
  }, [operations, visibleIds]);
  useEffect(() => {
    scene.current?.select(selected?.id || "", timeRange);
  }, [selected, visibleIds, timeRange]);
  useEffect(() => {
    if (code && (followingFile || codeFileId) && lastFollow.current !== "selection") return;
    if (lastFollow.current && expanded.length && (follow || lastFollow.current === "selection")) {
      scene.current?.focus(expanded); lastFollow.current = "";
    }
  }, [expanded, visibleIds, follow, code, followingFile, codeFileId]);

  pickRef.current = node => {
    if (code && node?.kind === "Module" && node.name === node.file)
      node = data?.nodes.find(file => file.kind === "File" && file.file === node?.file) || node;
    setSelected(node); setTimeRange(""); setDetail(null); setDetailError("");
    if (code && node) {
      setFollowingFile("");
      if (node.kind === "File" || !codeFileId) {
        const file = data?.nodes.find(file => file.kind === "File" && file.file === node.file);
        if (file) setCodeFileId(file.id);
      }
    }
    if (!code && !node) { setExpanded([]); lastFollow.current = ""; }
  };
  const select = (node: ProviderNode) => { pickRef.current(node); setExpanded([node.id]); lastFollow.current = "selection"; };
  useEffect(() => {
    if (!selected || code || !bank) return;
    const controller = new AbortController();
    json<Record<string, unknown>>("/api/graphs/memory/record?bank=" + encodeURIComponent(bank)
      + "&id=" + encodeURIComponent(selected.id.split("/").at(-1)!), controller.signal)
      .then(setDetail).catch(e => { if (!controller.signal.aborted) setDetailError(e.message); });
    return () => controller.abort();
  }, [selected?.id, code, bank]);

  const neighbors = useMemo(() => {
    if (!selected || !viewData) return [];
    const byId = new Map(viewData.nodes.map(n => [n.id, n]));
    const seen = new Set<string>();
    return viewData.edges.filter(e => e.source === selected.id || e.target === selected.id).flatMap(e => {
      const id = e.source === selected.id ? e.target : e.source;
      if (id === selected.id || seen.has(id) || !byId.has(id)) return [];
      seen.add(id); return [{ node: byId.get(id)!, kind: e.kind }];
    }).slice(0, 24);
  }, [viewData, selected]);
  commandRef.current = command => {
    if (command.action === "select") { const node = data?.nodes.find(n => n.id === command.id); if (node) select(node); }
    else if (code && command.action === "enterFile") {
      const node = data?.nodes.find(node => node.id === command.id);
      const file = node && data?.nodes.find(file => file.kind === "File" && file.file === node.file);
      if (file) { setFollowingFile(""); setCodeFileId(file.id); setExpanded([]); lastFollow.current = ""; }
    }
    else if (code && command.action === "back") back();
    else if (command.action === "clear") {
      setSelected(null); setTimeRange("");
      if (!code) { setExpanded([]); lastFollow.current = ""; }
    }
    else if (command.action === "fit") {
      if (code && codeFileId) { back(); return; }
      if (!code) { setSelected(null); setTimeRange(""); setExpanded([]); lastFollow.current = ""; }
      scene.current?.fit();
    }
    else if (!code && command.action === "search" && typeof command.value === "string") scene.current?.search(command.value);
    else if (!code && command.action === "timeRange" && typeof command.value === "string"
      && /^\d{4}-\d{2}-\d{2}\/\d{4}-\d{2}-\d{2}$/.test(command.value)) {
      const [from, to] = command.value.split("/");
      if (Number.isFinite(Date.parse(from)) && Number.isFinite(Date.parse(to)) && from <= to) {
        setSelected(null); setExpanded([]); lastFollow.current = ""; setTimeRange(command.value);
      }
    }
    else if (command.action === "refresh") refresh();
    else if (!fixedBank && command.action === "bank" && banks.some(b => b.id === command.value)) setBank(String(command.value));
    else if (command.action === "memoryType" && (command.value === "all" || Object.hasOwn(MEMORY_TYPES, String(command.value)))) setMemoryType(String(command.value));
    else if (command.action === "follow" && typeof command.value === "boolean") { setFollowingFile(""); setFollow(command.value); }
    else if (command.action === "allSymbols" && typeof command.value === "boolean") setAllSymbols(command.value);
  };
  useEffect(() => {
    scene.current?.presentation.publishCatalog({nodes: data?.nodes || [], count: data?.nodes.length || 0, links: data?.edges.length || 0,
      banks, limited: data?.limited});
  }, [data, banks]);
  useEffect(() => {
    scene.current?.presentation.publishState({bank, memoryType, allSymbols, follow, loading, error, connected, timeRange,
      codeFile: viewData?.code_file, codeIndex: indexState,
      externalShown: viewData?.nodes.filter(node => node.external).length, externalTotal: viewData?.external_count,
      count: visibleIds.size, links: visibleEdges,
      selected: selected && {...selected, ...viewData?.nodes.find(node => node.id === selected.id),
        text: typeof detail?.text === "string" ? detail.text : selected.text}, neighbors, hover: hover?.node || null, latest: operations[0]});
  }, [bank, memoryType, allSymbols, follow, loading, error, connected, selected, neighbors, hover?.node, operations, detail, visibleIds.size, visibleEdges, timeRange, viewData, indexState]);
  return <main className={`provider-graph ${code ? "code-graph" : "memory-graph"} provider-stage`} aria-label={`${title} graph stage`}>
    <div className="pg-workspace"><div className="pg-canvas" ref={host}/></div>
    {error && <div className="pg-empty" role="status"><strong>{title} unavailable</strong><p>{error}</p></div>}
  </main>;
}
