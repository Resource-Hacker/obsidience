import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type GraphOperation, type ProviderGraph, type ProviderNode } from "@/lib/api";
import { subscribeActivity } from "@/lib/activity-client";
import { onShellProviderGraph } from "@/lib/shell-client";
import { useSurfaceVisibility } from "@/lib/surface-visibility";
import type { GraphControl, GraphPublisher } from "@/graph/stream";
import { CODE_STRUCTURE, codeLayoutAncestry, codeFileGraph } from "@/graph/code/code-spherical-layout";
import { CodeKnowledgeScene } from "@/graph/code/code-knowledge-scene";
import "@/styles/provider-graph.css";

/** Provider nodes named by refs: their ids, `qn:` qualified names and `file:` paths. */
function aliases(data: ProviderGraph, refs: string[]): Set<string> {
  const wanted = new Set(refs), found = new Set<string>();
  for (const n of data.nodes) if (wanted.has(n.id) || (n.qualified_name && wanted.has("qn:" + n.qualified_name))
    || (n.kind === "File" && n.file && wanted.has("file:" + n.file))) found.add(n.id);
  return found;
}

/** The Samsung stage's Code third: the saved-code index, its file lens, follow,
 *  operations and the pane publisher, drawn by the Knowledge renderer. */
export function CodeStage() {
  const [data, setData] = useState<ProviderGraph | null>(null), [loading, setLoading] = useState(false);
  const [error, setError] = useState(""), [revision, setRevision] = useState(0);
  const [allSymbols, setAllSymbols] = useState(false);
  const [codeFileId, setCodeFileId] = useState(""), [followingFile, setFollowingFile] = useState("");
  const [indexState, setIndexState] = useState<ProviderGraph["index"]>();
  const [selected, setSelected] = useState<ProviderNode | null>(null);
  const [hover, setHover] = useState<ProviderNode | null>(null);
  const [operations, setOperations] = useState<GraphOperation[]>([]), [connected, setConnected] = useState(false);
  const [follow, setFollow] = useState(true), [expanded, setExpanded] = useState<string[]>([]);
  const visible = useSurfaceVisibility();
  const [consumers, setConsumers] = useState(0);
  // The Knowledge renderer owns this page's publisher.
  const [publisher, setPublisher] = useState<GraphPublisher | null>(null);
  const commandRef = useRef<(command: GraphControl) => void>(() => {});
  const followRef = useRef(follow), scope = useRef("");
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pickRef = useRef<(n: ProviderNode | null) => void>(() => {});
  followRef.current = follow;
  scope.current = data?.graph_id || "";
  // A Code view whose load failed has no graph identity to match operations
  // against. It loads again on the next sign that its provider path is alive.
  const stranded = useRef(false);
  stranded.current = !data && !loading && !!error;
  const back = () => {
    setCodeFileId(""); setFollowingFile(""); setSelected(null); setExpanded([]);
  };
  const refresh = () => {
    setIndexState({state: "updating"});
    api.refreshCodeGraph().then(setIndexState)
      .catch(error => setIndexState({state: "stale", error: error.message}));
  };

  useEffect(() => onShellProviderGraph("code", settings => {
    if (typeof settings.follow === "boolean") { setFollowingFile(""); setFollow(settings.follow); }
    if (typeof settings.allSymbols === "boolean") setAllSymbols(settings.allSymbols);
    if (settings.refresh) refresh();
    if (settings.fit) commandRef.current({action: "fit"});
  }), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    api.codeGraph(controller.signal).then(result => {
      setIndexState(result.index);
      setData(current => current && ["updating", "stale"].includes(result.index?.state || "") ? current : result);
      setLoading(false);
    }).catch(e => { if (!controller.signal.aborted) { setError(e.message); setLoading(false); } });
    return () => controller.abort();
  }, [revision]);

  const rendering = visible || consumers > 0;
  const wasRendering = useRef(rendering);
  useEffect(() => {
    // A shown view catches up on saved edits it missed while covered.
    if (rendering && !wasRendering.current) setRevision(r => r + 1);
    wasRendering.current = rendering;
  }, [rendering]);

  const coalesceRefresh = useCallback(() => {
    if (!refreshTimer.current) refreshTimer.current = setTimeout(() => {
      refreshTimer.current = null; setRevision(r => r + 1);
    }, 600);
  }, []);
  useEffect(() => {
    if (!rendering) return;
    function accept(op: GraphOperation, live: boolean) {
      if (!op || !Array.isArray(op.refs)) return;
      if (stranded.current && op.graph_id?.startsWith("code:")) { coalesceRefresh(); return; }
      if (op.graph_id !== scope.current) return;
      setOperations(current => [op, ...current.filter(item => item.id !== op.id)].slice(0, 12));
      if (live && op.kind === "edit") setIndexState({state: "updating"});
      // Reconnect reconciles the saved snapshot.
      if (op.refresh) coalesceRefresh();
      if (live && followRef.current && op.refs.length && op.status !== "running") {
        setExpanded(op.refs);
        if (op.kind === "edit") setFollowingFile(op.refs.find(ref => ref.startsWith("file:"))?.slice(5) || "");
      }
    }
    const stop = subscribeActivity({
      // The Harness is reachable (again): one more load, never a poll.
      open: () => { setConnected(true); if (stranded.current) coalesceRefresh(); },
      message: frame => {
        if (frame.type === "snapshot") {
          for (const op of frame.operations || []) accept(op as GraphOperation, false);
        } else if (frame.type === "operation") accept(frame.operation as GraphOperation, true);
      },
      close: () => setConnected(false),
    });
    return () => { stop(); setConnected(false); };
  }, [rendering, data?.graph_id, coalesceRefresh]);
  useEffect(() => () => { if (refreshTimer.current) clearTimeout(refreshTimer.current); }, []);

  useEffect(() => {
    if (!data) return;
    if (follow && followingFile) {
      const file = data.nodes.find(node => node.kind === "File" && node.file === followingFile);
      if (file) setCodeFileId(file.id);
    }
    if (codeFileId && !data.nodes.some(node => node.id === codeFileId)) back();
    setSelected(current => current ? data.nodes.find(node => node.id === current.id) || null : null);
  }, [data, follow, followingFile, codeFileId]);
  const viewData = useMemo(() => data && codeFileId ? codeFileGraph(data, codeFileId) || data : data, [data, codeFileId]);

  const activeIds = useMemo(() => data ? aliases(data, expanded) : new Set<string>(), [data, expanded]);
  const codeParents = useMemo(() => data ? codeLayoutAncestry(data).parents : new Map<string, string>(), [data]);
  const visibleIds = useMemo(() => {
    if (!viewData) return new Set<string>();
    const ids = new Set(viewData.nodes.filter(n => n.id === selected?.id || activeIds.has(n.id)
      || !!viewData.code_root || allSymbols || CODE_STRUCTURE.has(n.kind)).map(n => n.id));
    // Expanded symbols retain their exact containing path, without lighting it.
    if (!viewData.code_root) for (const id of ids) {
      let parent = codeParents.get(id);
      while (parent && !ids.has(parent)) { ids.add(parent); parent = codeParents.get(parent); }
    }
    return ids;
  }, [viewData, allSymbols, activeIds, selected?.id, codeParents]);
  const visibleEdges = useMemo(() => viewData?.edges.filter(e => e.source !== e.target && visibleIds.has(e.source) && visibleIds.has(e.target)).length || 0, [viewData, visibleIds]);

  pickRef.current = node => {
    if (node?.kind === "Module" && node.name === node.file)
      node = data?.nodes.find(file => file.kind === "File" && file.file === node?.file) || node;
    setSelected(node);
    if (node) {
      setFollowingFile("");
      if (node.kind === "File" || !codeFileId) {
        const file = data?.nodes.find(file => file.kind === "File" && file.file === node.file);
        if (file) setCodeFileId(file.id);
      }
    }
  };
  const select = (node: ProviderNode) => { pickRef.current(node); setExpanded([node.id]); };

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
    else if (command.action === "enterFile") {
      const node = data?.nodes.find(node => node.id === command.id);
      const file = node && data?.nodes.find(file => file.kind === "File" && file.file === node.file);
      if (file) { setFollowingFile(""); setCodeFileId(file.id); setExpanded([]); }
    }
    else if (command.action === "back") back();
    else if (command.action === "clear") setSelected(null);
    // Fit inside a file sphere returns to the project.
    else if (command.action === "fit") { if (codeFileId) back(); }
    else if (command.action === "refresh") refresh();
    else if (command.action === "follow" && typeof command.value === "boolean") { setFollowingFile(""); setFollow(command.value); }
    else if (command.action === "allSymbols" && typeof command.value === "boolean") setAllSymbols(command.value);
  };
  useEffect(() => {
    publisher?.publishCatalog({nodes: data?.nodes || [], count: data?.nodes.length || 0, links: data?.edges.length || 0,
      limited: data?.limited});
  }, [data, publisher]);
  useEffect(() => {
    publisher?.publishState({allSymbols, follow, loading, error, connected,
      codeFile: viewData?.code_file, codeIndex: indexState,
      externalShown: viewData?.nodes.filter(node => node.external).length, externalTotal: viewData?.external_count,
      count: visibleIds.size, links: visibleEdges,
      selected: selected && {...selected, ...viewData?.nodes.find(node => node.id === selected.id), text: selected.text},
      neighbors, hover, latest: operations[0]});
  }, [allSymbols, follow, loading, error, connected, selected, neighbors, hover, operations, visibleIds.size, visibleEdges, viewData, indexState, publisher]);
  return <main className="provider-graph code-graph provider-stage" aria-label="Code graph stage">
    <div className="pg-workspace">
      <CodeKnowledgeScene data={viewData} visibleIds={visibleIds} operations={operations} selectedId={selected?.id || ""}
        visible={rendering} onPick={node => pickRef.current(node)} onBack={back}
        onHover={node => setHover(current => current?.id === node?.id ? current : node)}
        onCommand={command => commandRef.current(command)} onPublisher={setPublisher} onConsumers={setConsumers}/>
    </div>
    {error && <div className="pg-empty" role="status"><strong>Code unavailable</strong><p>{error}</p></div>}
  </main>;
}
