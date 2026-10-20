import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Braces, Brain, ExternalLink, Maximize2, Network, Pause, Play, RotateCcw, SlidersHorizontal, X } from "lucide-react";
import { KNOWLEDGE_3D_TUNING_FIELDS, clampKnowledge3dTuning, type Knowledge3dTuning } from "@/graph/knowledge/knowledge-3d";
import { CODE_GRAPH_ID, MAIN_GRAPH_ID, announceGraphTuning, loadGraphTuning } from "@/graph/tuning";
import type { GraphControl } from "@/graph/stream";
import type { ProviderNode } from "@/lib/api";
import { onPublishedState } from "./stream";
import { dataJson } from "./runtime";
import type { Tour, TourState, View } from "./tour";

const KnowledgeSurface = lazy(() => import("@/surfaces/knowledge").then(m => ({ default: m.KnowledgeDesktopSurface })));
const MemorySurface = lazy(() => import("@/surfaces/memory").then(m => ({ default: m.MemoryStageWall })));
const CodeSurface = lazy(() => import("@/surfaces/code").then(m => ({ default: m.CodeStage })));

const REPO = "https://github.com/Resource-Hacker/obsidience";
const VIEWS: { id: View; title: string; Icon: typeof Network }[] = [
  { id: "knowledge", title: "Knowledge", Icon: Network },
  { id: "memory", title: "Memory", Icon: Brain },
  { id: "code", title: "Code", Icon: Braces },
];
type Article = { title: string; type: string; path: string; excerpt: string };
type Published = { node: ProviderNode | null; hover: ProviderNode | null; command?: (command: GraphControl) => void };

function captions(tour: Tour): Record<View, { title: string; text: string }> {
  return {
    knowledge: { title: "Thinking",
      text: `The Executive answers “${tour.data.question}” A pilot light runs the route and the beam follows it to each Article in its Thinking Packet; the Action Trace shows the packet, the Hindsight recall and the Tool call.` },
    memory: { title: "Recall",
      text: `Hindsight returns the newest voice-pipeline memories for “${tour.data.recall_question}” This bank is generated from the repository's own commit history and docs.` },
    code: { title: "Code lookup",
      text: `A coding agent's search_graph for “${tour.data.code_query}” lights the matching symbols in this repository's code graph.` },
  };
}

/** The Graph settings fields the desktop pane shows for a primary graph. */
function settingsFields() {
  return KNOWLEDGE_3D_TUNING_FIELDS.filter(field => !field.satelliteOnly).map(field =>
    field.key === "subjectStyle" || field.key === "subnodeStyle" || field.key === "articleStyle"
      ? { ...field, max: (field.key === "articleStyle" ? 4 : 5) - 1, options: field.options?.slice(0, field.key === "articleStyle" ? 4 : 5) }
      : field);
}

export function DemoApp({ tour, ownerTuning, embed }: { tour: Tour; ownerTuning: Record<string, unknown>; embed: boolean }) {
  const [tourState, setTourState] = useState<TourState>(() => tour.state());
  const [view, setView] = useState<View>("knowledge");
  const [settings, setSettings] = useState(false);
  const [published, setPublished] = useState<Published>({ node: null, hover: null });
  const [articles, setArticles] = useState<Record<string, Article>>({});
  // Docked: the host page shows this embed as its small floating graph.
  const [docked, setDocked] = useState(false);
  useEffect(() => {
    const message = (event: MessageEvent) => {
      if (event.origin === location.origin && event.source === window.parent && event.data?.type === "obsidience-demo-docked")
        setDocked(event.data.docked === true);
    };
    window.addEventListener("message", message);
    return () => window.removeEventListener("message", message);
  }, []);
  const text = useMemo(() => captions(tour), [tour]);

  useEffect(() => tour.subscribe(state => {
    setTourState(state);
    if (state.playing) setView(state.view);
  }), [tour]);
  useEffect(() => { dataJson<Record<string, Article>>("articles.json").then(setArticles).catch(() => {}); }, []);
  useEffect(() => tour.onCue(name => {
    if (name !== "recall-cards") return;
    // The tour's hand on the Action Trace: unfold the recall row a reader would open.
    const row = document.querySelector('section[aria-label="Live Action Trace"] [aria-label$="memories"]')?.closest("details");
    if (row) { row.open = true; row.scrollIntoView({ block: "start" }); }
  }), [tour]);
  useEffect(() => {
    setPublished({ node: null, hover: null });
    // The owner's look, also when this browser keeps no local storage.
    const graphId = view === "code" ? CODE_GRAPH_ID : MAIN_GRAPH_ID;
    const timer = setTimeout(() => {
      if (ownerTuning[graphId]) announceGraphTuning({ graphId, tuning: loadGraphTuning(graphId) });
    }, 0);
    return () => clearTimeout(timer);
  }, [view, ownerTuning]);
  useEffect(() => onPublishedState(({ view: source, state, command }) => {
    if (source !== view || (!("selected" in state) && !("hover" in state))) return;
    setPublished(current => {
      const node = state.selected ?? null, hover = state.hover ?? null;
      return current.node?.id === node?.id && current.hover?.id === hover?.id && current.command === command
        ? current : { node, hover, command };
    });
  }), [view]);

  const choose = (next: View) => {
    if (next === view && !tourState.playing) return;
    tour.setPlaying(false);
    setView(next);
  };
  const surface = useMemo(() => <Suspense fallback={null}>
    {view === "knowledge" ? <KnowledgeSurface/> : view === "memory" ? <MemorySurface/> : <CodeSurface/>}
  </Suspense>, [view]);
  const caption = text[view];
  const touring = tourState.playing && tourState.view === view;

  return <div className={`demo-root${embed ? " demo-embed" : ""}${docked ? " demo-docked" : ""}`} data-view={view}>
    {surface}
    <header className="demo-bar">
      <a className="demo-brand" href={embed ? "./" : REPO} target={embed ? "_top" : undefined} title={embed ? "Open the full-screen demo" : "Obsidience on GitHub"}>
        OBSIDIENCE<small>live graph demo</small>
      </a>
      <nav className="demo-views" aria-label="Graph views">
        {VIEWS.map(({ id, title, Icon }) => <button key={id} type="button" aria-pressed={view === id}
          className={view === id ? "current" : ""} onClick={() => choose(id)} title={`Show the ${title} graph`}>
          <Icon size={15}/><span>{title}</span>
        </button>)}
      </nav>
      <div className="demo-actions">
        <button type="button" onClick={() => tourState.playing ? tour.setPlaying(false) : tour.play(VIEWS.findIndex(v => v.id === view))}
          title={tourState.playing ? "Pause the tour" : "Play the tour from this view"} aria-label={tourState.playing ? "Pause the tour" : "Play the tour"}>
          {tourState.playing ? <Pause size={15}/> : <Play size={15}/>}
        </button>
        <button type="button" onClick={() => tour.play(0)} title="Replay the tour from the start" aria-label="Replay the tour"><RotateCcw size={15}/></button>
        {view !== "memory" && <button type="button" className={settings ? "current" : ""} onClick={() => setSettings(open => !open)}
          title="Graph settings" aria-label="Graph settings" aria-pressed={settings}><SlidersHorizontal size={15}/></button>}
        {embed && <a className="demo-icon-link" href="./" target="_top" title="Open full screen" aria-label="Open the demo full screen"><Maximize2 size={15}/></a>}
      </div>
    </header>

    <section className="demo-caption" aria-live="polite">
      <div className="demo-caption-head">
        <span className={touring ? "live" : ""}>{touring ? caption.title : "Exploring"}</span>
        {touring && <Progress tour={tour}/>}
      </div>
      <p>{touring ? caption.text : view === "memory"
        ? "A Hindsight-style bank generated from this repository's commit history and docs: experiences, world facts and observations on one timeline."
        : view === "code" ? "This repository's code graph from codebase-memory-mcp: folders, files and symbols, with calls and imports as links."
        : "The starter Vault the repository ships: the Executive's graph with Darwin, Alexandria and Heimdall orbiting it."}</p>
      <small>Drag to orbit · {embed ? "Ctrl + scroll" : "scroll"} to zoom · click a node{!tourState.playing && <> · <button type="button" className="demo-link" onClick={() => tour.play(VIEWS.findIndex(v => v.id === view))}>resume the tour</button></>}</small>
    </section>

    {published.node ? <DetailCard view={view} node={published.node}
      article={articles[published.node.ref || published.node.id] ?? (published.node.kind === "root" ? articles["Agents/Executive/Executive"] : undefined)}
      onClose={() => published.command?.({ action: "clear" })}/>
      : published.hover && view !== "knowledge" ? <div className="demo-hover"><small>{published.hover.kind}</small>{published.hover.name}</div> : null}

    {settings && view !== "memory" && <SettingsPanel key={view} graphId={view === "code" ? CODE_GRAPH_ID : MAIN_GRAPH_ID}
      ownerTuning={ownerTuning} onClose={() => setSettings(false)}/>}
  </div>;
}

function Progress({ tour }: { tour: Tour }) {
  const [progress, setProgress] = useState(0);
  useEffect(() => tour.onProgress(setProgress), [tour]);
  return <i className="demo-progress"><b style={{ transform: `scaleX(${progress})` }}/></i>;
}

function DetailCard({ view, node, article, onClose }: { view: View; node: ProviderNode; article?: Article; onClose: () => void }) {
  const commit = view === "memory" ? /\(commit ([0-9a-f]{7})\)/.exec(node.text || node.name)?.[1] : undefined;
  const link = view === "code" && node.file ? `${REPO}/blob/main/${node.file}${node.start_line ? `#L${node.start_line}` : ""}`
    : article ? `${REPO}/blob/main/obsidience/defaults/vault/${article.path}`
    : commit ? `${REPO}/commit/${commit}` : "";
  return <aside className="demo-card" style={{ borderColor: node.color }} aria-label="Selected node">
    <button type="button" className="demo-close" onClick={onClose} aria-label="Close"><X size={14}/></button>
    <small style={{ color: node.color }}>{view === "memory" ? `${node.kind} memory` : article?.type || node.kind}</small>
    <strong>{view === "memory" ? (node.text || node.name) : article?.title || node.name}</strong>
    <hr/>
    {view === "knowledge" && <p className="demo-path">{article?.path || node.ref || node.id}</p>}
    {view === "knowledge" && article?.excerpt && <p>{article.excerpt}</p>}
    {view === "code" && <p className="demo-path">{node.file}{node.start_line ? ` · lines ${node.start_line}–${node.end_line || node.start_line}` : ""}</p>}
    {view === "memory" && node.date && <p className="demo-path">{new Date(node.date).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })} · generated from the repository history</p>}
    {link && <a href={link} target="_blank" rel="noopener noreferrer">{view === "code" ? "Source" : view === "memory" ? "Commit" : "Article"} on GitHub <ExternalLink size={12}/></a>}
  </aside>;
}

function SettingsPanel({ graphId, ownerTuning, onClose }: { graphId: string; ownerTuning: Record<string, unknown>; onClose: () => void }) {
  const fields = useMemo(settingsFields, []);
  const [tuning, setTuning] = useState<Knowledge3dTuning>(() => loadGraphTuning(graphId));
  const groups = useMemo(() => [...new Set(fields.map(field => field.group))], [fields]);
  const apply = (next: Knowledge3dTuning) => { setTuning(next); announceGraphTuning({ graphId, tuning: next }); };
  const set = (key: keyof Knowledge3dTuning, value: number) => apply(clampKnowledge3dTuning({ ...tuning, [key]: value }));
  return <aside className="demo-settings" aria-label="Graph settings">
    <header><strong>Graph settings</strong><small>{graphId === CODE_GRAPH_ID ? "Code graph" : "Executive graph"} · changes stay in this page</small>
      <button type="button" className="demo-close" onClick={onClose} aria-label="Close settings"><X size={14}/></button></header>
    <div className="demo-settings-body">
      {groups.map(group => <fieldset key={group}><legend>{group}</legend>
        {fields.filter(field => field.group === group).map(field => <label key={field.key} title={field.description}>
          <span>{field.label}</span>
          {field.toggle ? <input type="checkbox" checked={tuning[field.key] >= 0.5} onChange={event => set(field.key, event.target.checked ? 1 : 0)}/>
            : field.options ? <select value={Math.round(tuning[field.key])} onChange={event => set(field.key, Number(event.target.value))}>
              {field.options.map((option, index) => <option key={option} value={index}>{option}</option>)}</select>
            : <><input type="range" min={field.min} max={field.max} step={field.step} value={tuning[field.key]}
                onChange={event => set(field.key, Number(event.target.value))}/><output>{Number(tuning[field.key].toFixed(3))}</output></>}
        </label>)}
      </fieldset>)}
    </div>
    <footer><button type="button" onClick={() => apply(clampKnowledge3dTuning(ownerTuning[graphId] ?? loadGraphTuning(graphId)))}>Reset to the owner's look</button></footer>
  </aside>;
}
