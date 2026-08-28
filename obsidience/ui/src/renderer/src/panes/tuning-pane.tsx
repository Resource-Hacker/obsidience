/** Graph Tuning, adapted from Obsidience's per-graph WeakAuras-style pane. */

import { useEffect, useMemo, useState } from "react";
import {
  KNOWLEDGE_3D_TUNING_FIELDS,
  clampKnowledge3dTuning,
  groupKnowledgeTuningFields,
  type Knowledge3dTuning,
} from "@/components/themes/obsidience/knowledge-3d";
import { api } from "@/lib/api";
import {
  LIBRARY_GRAPH_ID,
  MAIN_GRAPH_ID,
  announceGraphTuning,
  defaultGraphTuning,
  loadGraphTuning,
  onGraphSelected,
  requestGraphThinkingTest,
  saveGraphTuning,
} from "@/lib/graph-tuning";
import { StyleSelect } from "@/panes/style-portraits";

// v2 seeds every graph from the exact recovered Obsidience role profile.  The
// retired v1 store contained the temporary shared Obsidience placeholder.
const PROFILE_KEY = "obsidience.graph-tuning-profiles.v2";
const DEFAULT_PROFILE = "Default";
const LIBRARY_NODE_STYLE_KEYS = new Set<keyof Knowledge3dTuning>([
  "subjectStyle",
  "subnodeStyle",
  "articleStyle",
]);

interface GraphOption { id: string; label: string; order: number }
interface GraphProfiles { active: string; profiles: Record<string, Knowledge3dTuning> }
type ProfileStore = Record<string, GraphProfiles>;

function loadProfiles(): ProfileStore {
  try {
    const parsed = JSON.parse(localStorage.getItem(PROFILE_KEY) ?? "{}") as ProfileStore;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function persistProfiles(store: ProfileStore): void {
  try { localStorage.setItem(PROFILE_KEY, JSON.stringify(store)); } catch { /* best effort */ }
}

function profilesFor(store: ProfileStore, graphId: string): GraphProfiles {
  const current = store[graphId];
  if (current?.profiles[current.active]) return current;
  return { active: DEFAULT_PROFILE, profiles: { [DEFAULT_PROFILE]: loadGraphTuning(graphId) } };
}

function sameTuning(left: Knowledge3dTuning, right: Knowledge3dTuning): boolean {
  return KNOWLEDGE_3D_TUNING_FIELDS.every((field) => left[field.key] === right[field.key]);
}

export function TuningPaneBody() {
  const [options, setOptions] = useState<GraphOption[]>([
    { id: MAIN_GRAPH_ID, label: "JARVIS (Executive)", order: 0 },
    { id: LIBRARY_GRAPH_ID, label: "Library", order: 5 },
  ]);
  const [graphId, setGraphId] = useState(MAIN_GRAPH_ID);
  const [store, setStore] = useState<ProfileStore>(loadProfiles);
  const [working, setWorking] = useState<Record<string, Knowledge3dTuning>>({});
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  const [newProfile, setNewProfile] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => onGraphSelected(setGraphId), []);
  useEffect(() => {
    api.graph().then((graph) => {
      const role: Record<string, { label: string; order: number }> = {
        Heimdall: { label: "Heimdall (Guardian)", order: 1 },
        Alexandria: { label: "Alexandria (Curator)", order: 2 },
        Darwin: { label: "Darwin (Researcher)", order: 3 },
      };
      const agents = new Map<string, GraphOption>();
      for (const node of graph.nodes.filter((entry) => entry.kind === "agent")) {
        const parts = node.id.split("/");
        if (parts[0] !== "Agents" || !parts[1]) continue;
        const name = parts[1];
        agents.set(name, {
          id: name,
          label: role[name]?.label ?? name,
          order: role[name]?.order ?? 4,
        });
      }
      setOptions([
        {
          id: MAIN_GRAPH_ID,
          label: `${graph.nodes.find((node) => node.id === "Agents/Executive/Executive")?.title ?? "JARVIS"} (Executive)`,
          order: 0,
        },
        ...agents.values(),
        { id: LIBRARY_GRAPH_ID, label: "Library", order: 5 },
      ].sort((left, right) => left.order - right.order || left.label.localeCompare(right.label)));
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    setConfirmReset(false);
    setNewProfile(null);
  }, [graphId]);

  const graphProfiles = profilesFor(store, graphId);
  const saved = graphProfiles.profiles[graphProfiles.active];
  const active = working[graphId] ?? saved;
  const dirty = !sameTuning(active, saved);
  const sections = useMemo(() => groupKnowledgeTuningFields(
    KNOWLEDGE_3D_TUNING_FIELDS
      .filter((field) => graphId !== MAIN_GRAPH_ID || !field.satelliteOnly)
      .map((field) => graphId !== LIBRARY_GRAPH_ID && LIBRARY_NODE_STYLE_KEYS.has(field.key)
        ? { ...field, max: 3, options: field.options?.slice(0, 4) }
        : field),
  ), [graphId]);
  const section = sections.find((entry) => entry.group === activeGroup) ?? sections[0];

  const preview = (record: Knowledge3dTuning) => {
    setWorking((current) => ({ ...current, [graphId]: record }));
    announceGraphTuning({ graphId, tuning: record });
  };
  const update = (key: keyof Knowledge3dTuning, value: number) => {
    setConfirmReset(false);
    preview(clampKnowledge3dTuning({ ...active, [key]: value }));
  };
  const applyProfile = (name: string, record: Knowledge3dTuning) => {
    const next = {
      ...store,
      [graphId]: {
        active: name,
        profiles: { ...graphProfiles.profiles, [name]: record },
      },
    };
    setStore(next);
    persistProfiles(next);
    setWorking((current) => {
      const copy = { ...current };
      delete copy[graphId];
      return copy;
    });
    saveGraphTuning(graphId, record);
    announceGraphTuning({ graphId, tuning: record });
  };
  const save = () => applyProfile(graphProfiles.active, active);
  const discard = () => {
    setWorking((current) => {
      const copy = { ...current };
      delete copy[graphId];
      return copy;
    });
    announceGraphTuning({ graphId, tuning: saved });
  };

  return (
    <div className="flex h-full flex-col gap-3 overflow-hidden p-3">
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <label className="flex min-w-0 flex-1 items-center gap-2">
          <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-300/60">Graph</span>
          <select value={graphId} onChange={(event) => setGraphId(event.target.value)}
            className="min-w-[9rem] flex-1 rounded border border-cyan-300/25 bg-[#061019] px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-cyan-100">
            {options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-300/60">Profile</span>
          <select value={graphProfiles.active} onChange={(event) => {
            if (event.target.value === "__new__") setNewProfile("");
            else applyProfile(event.target.value, graphProfiles.profiles[event.target.value]);
          }} className="w-32 rounded border border-cyan-300/25 bg-[#061019] px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-cyan-100">
            {Object.keys(graphProfiles.profiles).map((name) => <option key={name} value={name}>{name}</option>)}
            <option value="__new__">New profile…</option>
          </select>
        </label>
      </div>

      {newProfile !== null ? (
        <form className="flex shrink-0 gap-1" onSubmit={(event) => {
          event.preventDefault();
          const name = newProfile.trim().slice(0, 24);
          if (name && name !== "__new__") applyProfile(name, active);
          setNewProfile(null);
        }}>
          <input autoFocus value={newProfile} onChange={(event) => setNewProfile(event.target.value)}
            placeholder="Profile name"
            className="min-w-0 flex-1 rounded border border-cyan-300/30 bg-[#061019] px-2 py-1 font-mono text-[10px] text-cyan-100" />
          <button className="rounded border border-cyan-300/25 px-2 font-mono text-[9px] uppercase text-cyan-100">Add</button>
        </form>
      ) : null}

      <div className="flex min-h-0 flex-1 gap-3">
        <nav className="w-36 shrink-0 overflow-y-auto rounded border border-cyan-300/10 bg-slate-950/30 p-1">
          {sections.map((entry) => (
            <button key={entry.group} type="button" onClick={() => setActiveGroup(entry.group)}
              className={`block w-full rounded px-2 py-1.5 text-left font-mono text-[9px] uppercase tracking-[0.18em] ${entry.group === section?.group ? "bg-cyan-300/15 text-cyan-100" : "text-cyan-300/60 hover:bg-cyan-300/8"}`}>
              {entry.group}
            </button>
          ))}
        </nav>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
          {section?.fields.map((field) => field.options ? (
            <label key={field.key} className="block">
              <span title={field.description} className="font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-300/60">{field.label}</span>
              <StyleSelect field={field} value={active[field.key]} onChange={(next) => update(field.key, next)} />
            </label>
          ) : field.toggle ? (
            <label key={field.key} title={field.description} className="flex items-center justify-between gap-3">
              <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-300/60">{field.label}</span>
              <input type="checkbox" checked={active[field.key] >= 0.5}
                onChange={(event) => update(field.key, event.target.checked ? 1 : 0)}
                className="h-3.5 w-3.5 accent-cyan-300" />
            </label>
          ) : (
            <label key={field.key} className={`block ${
              field.key === "sweepSpeed" && active.automaticSweepSpeed >= 0.5
                ? "opacity-40" : ""
            }`}>
              <span title={field.description} className="flex justify-between font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-300/60">
                {field.label}<span className="text-cyan-100/80">{active[field.key]}</span>
              </span>
              <input type="range" min={field.min} max={field.max} step={field.step} value={active[field.key]}
                disabled={field.key === "sweepSpeed" && active.automaticSweepSpeed >= 0.5}
                onChange={(event) => update(field.key, Number(event.target.value))}
                title={field.description} className="mt-1 h-1 w-full cursor-pointer accent-cyan-300 disabled:cursor-not-allowed" />
            </label>
          ))}
        </div>
      </div>

      <div className="grid shrink-0 grid-cols-4 gap-2 border-t border-cyan-300/10 pt-2">
        <button type="button" onClick={save} disabled={!dirty}
          className="rounded border border-emerald-300/35 px-2 py-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-emerald-200 disabled:border-cyan-300/15 disabled:text-cyan-300/30">
          {dirty ? "Save*" : "Saved"}
        </button>
        <button type="button" onClick={discard} disabled={!dirty}
          className="rounded border border-cyan-300/25 px-2 py-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-cyan-100 disabled:opacity-30">Discard</button>
        <button type="button" onClick={() => {
          if (!confirmReset) { setConfirmReset(true); return; }
          setConfirmReset(false);
          preview(defaultGraphTuning(graphId));
        }} className={`rounded border px-2 py-1.5 font-mono text-[9px] uppercase tracking-[0.12em] ${confirmReset ? "border-rose-300/50 text-rose-200" : "border-cyan-300/25 text-cyan-100"}`}>
          {confirmReset ? "Confirm" : "Reset"}
        </button>
        <button type="button" onClick={() => requestGraphThinkingTest(graphId)}
          className="rounded border border-violet-300/40 px-2 py-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-violet-200 hover:bg-violet-300/10">Test thinking</button>
      </div>
    </div>
  );
}
