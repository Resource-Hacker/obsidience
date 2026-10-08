import { useEffect, useMemo, useRef, useState } from "react";
import { Brain, Braces, Network, Search, Scan, RefreshCw, Radio, X, ArrowUpRight, ArrowLeft, Layers, ChevronDown } from "lucide-react";
import { presentShellGraph, presentShellReader, presentShellSource, onShellStageVisibility, onShellGraphView, selectShellGraphView, type GraphView, type GraphSource } from "@/lib/shell-client";
import { GraphSubscriber, MEMORY_TYPES, type GraphCatalog, type GraphControl, type GraphViewState } from "./graph-stream";
import type { ProviderNode } from "./provider-graph-scene";
import "./provider-graph.css";

const IDENTITIES = {
  memory: {title: "Memory", subtitle: "OPERATIONAL MEMORY", source: "HINDSIGHT", Icon: Brain},
  knowledge: {title: "Knowledge", subtitle: "ACCEPTED WIKI", source: "KNOWLEDGE LIBRARY", Icon: Network},
  code: {title: "Code", subtitle: "IMPLEMENTATION ATLAS", source: "CODEBASE MEMORY", Icon: Braces},
};
const KNOWLEDGE_GRAPHS = [{id: "main", name: "Executive"}, {id: "library", name: "Library"},
  {id: "Darwin", name: "Darwin"}, {id: "Alexandria", name: "Alexandria"}, {id: "Heimdall", name: "Heimdall"}];

/** One native pane, with exactly one subscribed graph view at a time. */
export function GraphPaneSurface() {
  const [view, setView] = useState<GraphView>("knowledge");
  const [knowledgeGraphId, setKnowledgeGraphId] = useState("main");
  useEffect(() => onShellGraphView(setView), []);
  return <GraphViewer key={view} view={view} onViewChange={selectShellGraphView}
    initialGraphId={knowledgeGraphId} onGraphIdChange={setKnowledgeGraphId}/>;
}

/** Common viewer chrome around the stage's video, with no graph renderer. */
export function GraphViewer({view, onViewChange = presentShellGraph, initialGraphId = "main", onGraphIdChange}: {
  view: GraphView; onViewChange?: (view: GraphView) => void;
  initialGraphId?: string; onGraphIdChange?: (id: string) => void;
}) {
  const {title, subtitle, source, Icon} = IDENTITIES[view];
  const video = useRef<HTMLVideoElement>(null), subscriber = useRef<GraphSubscriber | null>(null);
  const [catalog, setCatalog] = useState<GraphCatalog>({nodes: [], count: 0, links: 0});
  const [state, setState] = useState<GraphViewState>({}), [linked, setLinked] = useState(false), [ready, setReady] = useState(false);
  const [error, setError] = useState(""), [query, setQuery] = useState(""), [visible, setVisible] = useState(!document.hidden);
  const [cursor, setCursor] = useState({x: 0, y: 0}), [retry, setRetry] = useState(0);
  const [graphId, setGraphId] = useState(initialGraphId);
  const [fromDate, setFromDate] = useState(""), [toDate, setToDate] = useState("");
  const graphSource: GraphSource = view !== "knowledge" ? view : graphId === "library" ? "library"
    : graphId === "main" ? "knowledge" : `knowledge:${graphId}` as GraphSource;
  const gesture = useRef({down: false, moved: false, x: 0, y: 0, firstX: 0, firstY: 0});
  const hoverAt = useRef(0);
  const [surfaceId, setSurfaceId] = useState("samsung"), [surfaceVisible, setSurfaceVisible] = useState(true);
  useEffect(() => onShellStageVisibility(surfaceId, setSurfaceVisible), [surfaceId]);
  const send = (command: GraphControl) => subscriber.current?.send(view === "knowledge" ? {...command, graphId} : command);
  useEffect(() => {
    let paneVisible = document.documentElement.dataset.paneVisible !== "false";
    setSurfaceId(document.documentElement.dataset.paneSurface || "samsung");
    setVisible(paneVisible && !document.hidden);
    const changed = () => setVisible(paneVisible && !document.hidden);
    const pane = (event: Event) => { paneVisible = (event as CustomEvent<boolean>).detail === true; changed(); };
    const surface = (event: Event) => { const id = (event as CustomEvent<string>).detail; if (["samsung", "usb-c", "dp-4"].includes(id)) setSurfaceId(id); };
    document.addEventListener("visibilitychange", changed); window.addEventListener("obsidience-pane-visibility", pane);
    window.addEventListener("obsidience-pane-surface", surface);
    return () => { document.removeEventListener("visibilitychange", changed); window.removeEventListener("obsidience-pane-visibility", pane); window.removeEventListener("obsidience-pane-surface", surface); };
  }, []);
  useEffect(() => {
    if (!visible || !surfaceVisible || !video.current) return;
    setReady(false); setError(""); setState({}); setCatalog({nodes: [], count: 0, links: 0});
    const element = video.current;
    const loaded = () => setReady(element.videoWidth > 0);
    element.addEventListener("loadeddata", loaded); element.addEventListener("resize", loaded);
    subscriber.current = new GraphSubscriber(graphSource, element, message => {
      if (message.type === "catalog") setCatalog(message.value);
      else setState(message.value);
    }, (connected, failure) => { setLinked(connected); if (!connected) setReady(false); else setError(""); if (failure) setError(failure); });
    return () => { element.removeEventListener("loadeddata", loaded); element.removeEventListener("resize", loaded); subscriber.current?.dispose(); subscriber.current = null; };
  }, [graphSource, visible, surfaceVisible, retry]);
  const viewNodes = useMemo(() => view === "knowledge" ? catalog.nodes.filter(node => node.graph_id === graphId) : catalog.nodes, [catalog.nodes, view, graphId]);
  const matches = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    return q ? viewNodes.filter(n => [n.name, n.file, n.qualified_name, n.text, ...(n.tags || [])].some(value => value?.toLocaleLowerCase().includes(q))) : [];
  }, [viewNodes, query]);
  useEffect(() => {
    if (view !== "memory" || !linked) return;
    const timer = setTimeout(() => subscriber.current?.send({action: "search", value: query.slice(0, 256)}), 120);
    return () => clearTimeout(timer);
  }, [view, linked, query, state.bank]);
  useEffect(() => {
    const [from = "", to = ""] = (state.timeRange || "").split("/");
    setFromDate(from); setToDate(to);
  }, [state.timeRange, state.bank]);
  const rangeCount = useMemo(() => {
    if (!fromDate || !toDate || fromDate > toDate) return 0;
    const from = new Date(fromDate + "T00:00:00").getTime(), to = new Date(toDate + "T23:59:59.999").getTime();
    return viewNodes.filter(n => { const date = Date.parse(n.date || ""); return date >= from && date <= to; }).length;
  }, [viewNodes, fromDate, toDate]);
  const selected = view !== "knowledge" || state.selected?.graph_id === graphId ? state.selected : null;
  const hover = view !== "knowledge" || state.hover?.graph_id === graphId ? state.hover : null;
  const bank = catalog.banks?.find(bank => bank.id === state.bank);
  const graphCounts = view === "knowledge" ? catalog.graphs?.find(graph => graph.id === graphId)
    : {count: state.count ?? catalog.count, links: state.links ?? catalog.links};
  const open = (node: ProviderNode) => {
    if (view === "code" && node.file) presentShellSource(node.file);
    else presentShellReader(node.ref || node.id, node.graph_id || bank?.agent_ref.split("/")[1]?.toLowerCase() || "library");
  };
  function point(event: {clientX: number; clientY: number}) {
    const element = video.current; if (!element || !element.videoWidth) return null;
    const rect = element.getBoundingClientRect(), scale = Math.min(rect.width / element.videoWidth, rect.height / element.videoHeight);
    const width = element.videoWidth * scale, height = element.videoHeight * scale;
    const left = rect.left + (rect.width - width) / 2, top = rect.top + (rect.height - height) / 2;
    return {x: (event.clientX - left) / width, y: (event.clientY - top) / height, width, height};
  }
  const select = (node: ProviderNode) => { send({action: "select", id: node.id}); setQuery(""); };

  return <main className={`provider-graph ${view}-graph`} aria-label={`${title} graph viewer`} data-graph-viewer={view}>
    <header className="pg-header">
      <div className="pg-identity"><Icon size={24}/><div><h1>{title}</h1><span>{subtitle}</span></div></div>
      <nav aria-label="Graph views">{(["knowledge", "memory", "code"] as GraphView[]).map(other => {
        const Entry = IDENTITIES[other]; return <button key={other} className={view === other ? "current" : ""} aria-pressed={view === other} aria-label={`Show ${Entry.title} graph`} title={`Show ${Entry.title} graph`} onClick={() => onViewChange(other)}><Entry.Icon size={15}/><span>{Entry.title}</span></button>;
      })}</nav>
    </header>
    {view === "memory" && <div className="pg-agentbar"><label>Agent graph
      <span className="pg-agent-select">
        <select aria-label="Agent memory graph" disabled={!linked || !catalog.banks?.length} value={state.bank || ""}
          onChange={event => { setQuery(""); send({action: "bank", value: event.target.value}); }}>
          {!state.bank && <option value="" disabled>{catalog.banks?.length ? "Select an agent…" : "Loading agents…"}</option>}
          {catalog.banks?.map(bank => <option key={bank.id} value={bank.id}>{bank.name}</option>)}
        </select>
        <ChevronDown size={16} aria-hidden="true"/>
      </span>
    </label></div>}
    <div className="pg-toolbar">
      <label className="pg-search"><Search size={15}/><input aria-label={`Search ${title.toLowerCase()}`} maxLength={view === "memory" ? 256 : undefined} placeholder={view === "code" ? "Find a file, symbol or route…" : view === "memory" ? "Find a memory…" : "Find an Article or branch…"} value={query} onChange={event => setQuery(event.target.value)}/>{query && <button aria-label="Clear search" onClick={() => setQuery("")}><X size={14}/></button>}</label>
      {view === "knowledge" && <select aria-label="Knowledge graph" value={graphId} onChange={e => {
        setGraphId(e.target.value); onGraphIdChange?.(e.target.value); setQuery("");
      }}>{KNOWLEDGE_GRAPHS.map(graph => <option key={graph.id} value={graph.id}>{graph.name}</option>)}</select>}
      {view !== "knowledge" && <button className={state.follow ? "enabled" : ""} aria-pressed={!!state.follow} title="Follow exact results from live activity" onClick={() => send({action: "follow", value: !state.follow})}><Radio size={15}/><span>Follow</span></button>}
      <button title={state.codeFile ? "Return to project" : "Fit graph"} aria-label={state.codeFile ? "Return to project" : "Fit graph"} disabled={!linked} onClick={() => send({action: "fit"})}><Scan size={16}/></button>
      <button title={view === "code" ? "Refresh saved code index" : "Refresh graph"} aria-label="Refresh graph" disabled={state.loading || state.codeIndex?.state === "updating" || !linked} onClick={() => send({action: "refresh"})}><RefreshCw size={15} className={state.loading || state.codeIndex?.state === "updating" ? "pg-loading" : ""}/></button>
    </div>
    {view === "code" && <div className="pg-codebar">
      {state.codeFile ? <><button disabled={!linked} onClick={() => send({action: "back"})}><ArrowLeft size={14}/>Project</button><span className="pg-code-path" title={state.codeFile}>{state.codeFile}</span></>
        : <span>Project sphere</span>}
      <small role="status" title={state.codeIndex?.error || (state.codeIndex?.updated_at ? `Indexed ${new Date(state.codeIndex.updated_at).toLocaleTimeString()}` : "Native saved-code snapshot")}>
        {state.codeIndex?.state === "updating" ? "Indexing saved changes…" : state.codeIndex?.state === "stale" ? "Index stale · Refresh to retry" : "Saved code"}
      </small>
    </div>}
    {view === "memory" && <form className="pg-timebar" aria-label="Expand a time range" onSubmit={event => {
      event.preventDefault(); if (rangeCount && linked) send({action: "timeRange", value: `${fromDate}/${toDate}`});
    }}>
      <label>From<input type="date" aria-label="First date to expand" value={fromDate} onChange={event => setFromDate(event.target.value)}/></label>
      <label>To<input type="date" aria-label="Last date to expand" min={fromDate || undefined} value={toDate} onChange={event => setToDate(event.target.value)}/></label>
      <button type="submit" disabled={!linked || !rangeCount}>Expand{rangeCount ? ` ${rangeCount.toLocaleString()}` : " range"}</button>
      {(state.timeRange || selected) && <button type="button" onClick={() => send({action: "fit"})}>Overview</button>}
      <small>Activity spacing · turns ≠ days</small>
    </form>}
    <div className="pg-workspace">
      <div className="pg-video-frame">
      <video ref={video} className="pg-video" autoPlay muted playsInline aria-label={`${title} stage mirror`}
        style={{visibility: view === "memory" && state.count === 0 ? "hidden" : undefined}}
        onPointerDown={event => {
          if (event.button !== 0) return;
          gesture.current = {down: true, moved: false, x: event.clientX, y: event.clientY, firstX: event.clientX, firstY: event.clientY};
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={event => {
          const p = point(event); if (!p) return;
          const g = gesture.current;
          if (g.down) {
            if (Math.hypot(event.clientX - g.firstX, event.clientY - g.firstY) >= 5) g.moved = true;
            if (g.moved) send({action: "orbit", dx: Math.max(-4, Math.min(4, (event.clientX - g.x) / p.width)), dy: Math.max(-4, Math.min(4, (event.clientY - g.y) / p.height))});
            g.x = event.clientX; g.y = event.clientY;
          } else if (performance.now() - hoverAt.current > 50) {
            hoverAt.current = performance.now();
            if (p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1) {
              setCursor({x: event.nativeEvent.offsetX, y: event.nativeEvent.offsetY}); send({action: "hover", x: p.x, y: p.y});
            } else send({action: "leave"});
          }
        }}
        onPointerUp={event => {
          const g = gesture.current, p = point(event);
          if (g.down && !g.moved && p && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1) send({action: "click", x: p.x, y: p.y});
          g.down = false; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
          if (!p || p.x < 0 || p.x > 1 || p.y < 0 || p.y > 1) send({action: "leave"});
        }}
        onPointerCancel={() => { gesture.current.down = false; send({action: "leave"}); }}
        onPointerLeave={() => { if (!gesture.current.down) send({action: "leave"}); }}
        onWheel={event => send({action: "zoom", dy: Math.max(-4, Math.min(4, event.deltaY / 300))})}
        onContextMenu={event => {
          event.preventDefault();
          if (view === "code" && state.codeFile) send({action: "back"});
        }}/>
      </div>
      <div className="pg-grid" aria-hidden="true"/>
      <div className="pg-scope"><span className="pg-live-dot"/>{view === "knowledge" ? `${KNOWLEDGE_GRAPHS.find(graph => graph.id === graphId)?.name} KNOWLEDGE` : source}<small>{view === "memory" ? `${bank?.name || "Agent"} · conversation timeline · unverified` : view === "code" ? state.codeFile ? `File sphere · ↗ ${state.externalShown || 0}/${state.externalTotal || 0} external symbols` : "Native index · saved changes" : "Accepted Articles & relationships"}</small></div>
      <div className="pg-filters">
        {view === "code" && !state.codeFile && <button className={state.allSymbols ? "enabled" : ""} onClick={() => send({action: "allSymbols", value: !state.allSymbols})}><Layers size={14}/>{state.allSymbols ? "All symbols" : "Files + active symbols"}</button>}
        {view === "memory" && <select aria-label="Memory type" value={state.memoryType || "all"} onChange={e => send({action: "memoryType", value: e.target.value})}><option value="all">All memories</option>{Object.entries(MEMORY_TYPES).map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}</select>}
      </div>
      {hover && !selected && !query && <div className="pg-tooltip" style={{left: Math.max(8, Math.min(cursor.x + 15, (video.current?.clientWidth || 600) - 285)), top: Math.max(65, cursor.y - 40)}}><small>{hover.kind}</small><strong>{hover.name}</strong></div>}
      {query && <aside className="pg-results" aria-label="Search results"><small>{matches.length.toLocaleString()} results in stage graph</small>{matches.slice(0, 30).map(node => <button key={node.id} onClick={() => select(node)}><i style={{background: node.color}}/><span>{node.name}<small>{node.file || node.kind}</small></span></button>)}{matches.length > 30 && <small>Refine your search to see more.</small>}</aside>}
      {selected && <aside className="pg-detail" aria-label="Selected record">
        <button className="pg-close" aria-label="Close detail" onClick={() => send({action: "clear"})}><X size={16}/></button>
        <span className="pg-kind" style={{color: selected.color}}>{selected.kind}</span>
        <h2>{view === "memory" ? "Memory record" : selected.name}</h2>
        {selected.file && <p className="pg-path">{selected.file}</p>}
        {view === "code" && !!selected.start_line && <p className="pg-date">Lines {selected.start_line}–{selected.end_line || selected.start_line}{selected.external ? " · external dependency" : ""}</p>}
        {selected.text && <p className="pg-memory-text">{selected.text}</p>}
        {view === "memory" && <><div className="pg-tags">{selected.tags?.map(tag => <span key={tag}>{tag}</span>)}</div>{selected.date && <p className="pg-date">Mentioned {new Date(selected.date).toLocaleString()}</p>}{selected.occurred_start && selected.occurred_start !== selected.date && <p className="pg-date">Occurred {new Date(selected.occurred_start).toLocaleString()}</p>}<p>{selected.proof_count || selected.support?.length || 0} supporting memories · unverified</p></>}
        <button className="pg-primary" onClick={() => open(selected)}>{view === "code" ? "Open source" : view === "memory" ? "Open record & evidence" : "Open Article"}<ArrowUpRight size={14}/></button>
        {view === "code" && selected.file && selected.file !== state.codeFile && <button className="pg-primary" onClick={() => send({action: "enterFile", id: selected.id})}>Explore file sphere<Braces size={14}/></button>}
        {!!state.neighbors?.length && <div className="pg-neighbors"><h3>Connected records</h3>{state.neighbors.map(({node, kind}) => <button key={node.id} onClick={() => select(node)}><small>{kind}</small><span>{node.name}</span></button>)}</div>}
      </aside>}
      {(error || state.error) && <div className="pg-empty" role="status"><strong>{catalog.nodes.length ? "Snapshot retained" : `${title} unavailable`}</strong><p>{error || state.error}</p><button onClick={() => error ? setRetry(r => r + 1) : send({action: "refresh"})}>Reconnect</button></div>}
      {!ready && !error && !state.error && <div className="pg-empty" role="status"><strong>{visible ? `Connecting to ${title.toLowerCase()} stage…` : "Viewer paused"}</strong><p>{state.loading ? "Loading the provider’s graph." : "The desktop stage supplies this view."}</p></div>}
      {view === "memory" && ready && (!state.loading || catalog.nodes.length > 0) && !error && !state.error && state.count === 0 && <div className="pg-empty" role="status"><strong>No memories of this type</strong><p>Choose another memory type or Agent bank.</p></div>}
      {!selected && !query && <span className="pg-gesture">{view === "memory" ? "Select to expand · Scroll for labels · Fit for the whole spiral" : view === "code" ? state.codeFile ? "Green: added · Amber: changed · Rose: removed · Right-click to go back" : "Click a file to unfold · Follow saved edits · Drag to orbit" : "Drag to orbit · Scroll to zoom · Click to inspect"}</span>}
    </div>
    <footer className="pg-footer"><div><i className={linked && ready ? "online" : ""}/><span>{linked && ready ? "Linked to desktop stage" : visible ? "Connecting to stage" : "View paused"}</span><span className="pg-count">{(graphCounts?.count ?? viewNodes.length).toLocaleString()} nodes · {(graphCounts?.links ?? 0).toLocaleString()} links</span></div>
      <div className="pg-activity">{state.latest ? <><span className={state.latest.status === "running" ? "pg-running" : ""}>{state.latest.status === "running" ? "●" : "↳"}</span>{state.latest.label}<small>{state.latest.status}</small></> : <span>{state.connected === false ? "Provider activity reconnecting" : "Waiting for activity"}</span>}</div>
    </footer>
    {catalog.limited && <div className="pg-limit">Provider record limit reached.</div>}
  </main>;
}
