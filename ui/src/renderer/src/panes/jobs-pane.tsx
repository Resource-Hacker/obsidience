/** Jobs pane — where tasks are ASSIGNED: create, schedule, run, and watch
 *  task instances under the interpreter. ("Job" is operational vocabulary
 *  for a task instance, not a fifth primitive.) */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Play, Plus, RefreshCw, X } from "lucide-react";
import { API_BASE, api, openReader, type ReasoningEffort, type TaskRow } from "@/lib/api";
import {
  knowledgeRoleForAgent,
  paintKnowledgeRoleIcon,
} from "@/components/themes/jarvis/knowledge-role-icons";

interface AgentOption { ref: string; title: string }

function cleanLink(value: string): string {
  return value.trim().replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0];
}

function agentName(value: string): string {
  return cleanLink(value).split("/").pop() ?? "";
}

function AgentGlyph({ name, size = 14 }: { name: string; size?: number }) {
  const holder = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const element = holder.current;
    if (!element) return;
    const canvas = paintKnowledgeRoleIcon(knowledgeRoleForAgent(name), Math.max(48, size * 3));
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    element.replaceChildren(canvas);
  }, [name, size]);
  return <span ref={holder} className="block shrink-0" style={{ width: size, height: size }} />;
}

function AssigneeSelect({
  task,
  agents,
  onChange,
}: {
  task: TaskRow;
  agents: AgentOption[];
  onChange: (ref: string, agent: AgentOption) => void;
}) {
  const [open, setOpen] = useState(false);
  const selectedName = agentName(task.assignee);
  const selected = agents.find((agent) =>
    cleanLink(task.assignee) === agent.ref || selectedName.toLowerCase() === agent.title.toLowerCase());
  const label = selected?.title ?? (selectedName || "Assign");
  return (
    <div className="relative justify-self-center" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false);
    }}>
      <button type="button" onClick={() => setOpen((current) => !current)}
        aria-haspopup="listbox" aria-expanded={open} aria-label={`Assign ${task.title}`}
        title={`Assign ${task.title}`}
        className="flex w-[98px] items-center gap-1 rounded border border-cyan-300/20 bg-[#020a12] px-1 py-0.5 text-left font-mono text-[8px] text-cyan-100/75 outline-none hover:border-cyan-300/40">
        {selectedName ? <AgentGlyph name={selectedName} /> : <span className="h-[14px] w-[14px]" />}
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <ChevronDown size={9} className="shrink-0 text-cyan-300/45" />
      </button>
      {open ? (
        <div role="listbox"
          className="absolute left-0 top-full z-30 mt-1 w-[124px] overflow-hidden rounded border border-cyan-300/25 bg-[#020a12] py-0.5 shadow-[0_8px_24px_rgba(0,0,0,0.65)]">
          {agents.map((agent) => (
            <button key={agent.ref} type="button" role="option"
              aria-selected={agent.ref === selected?.ref}
              onClick={() => { onChange(task.ref, agent); setOpen(false); }}
              className="flex w-full items-center gap-1.5 px-1.5 py-1 text-left font-mono text-[9px] text-cyan-100/75 hover:bg-cyan-300/10 hover:text-cyan-50">
              <AgentGlyph name={agent.title} size={16} />
              <span className="truncate">{agent.title}</span>
            </button>
          ))}
          {agents.length === 0 ? <span className="block px-2 py-1 font-mono text-[8px] text-cyan-200/35">No agents</span> : null}
        </div>
      ) : null}
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  pending: "text-cyan-200 border-cyan-300/40",
  running: "text-emerald-200 border-emerald-300/50 animate-pulse",
  review: "text-amber-200 border-amber-300/50",
  completed: "text-emerald-300/70 border-emerald-300/25",
  failed: "text-rose-300 border-rose-300/50",
  blocked: "text-rose-200 border-rose-300/40",
  draft: "text-cyan-200/50 border-cyan-300/20",
};

export function JobsPaneBody() {
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const initializedHierarchy = useRef(false);
  const [busyRef, setBusyRef] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [runbooks, setRunbooks] = useState<string[]>([]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [form, setForm] = useState<{
    title: string; runbook: string; schedule: string; body: string; reasoningEffort: ReasoningEffort;
  }>({ title: "", runbook: "", schedule: "", body: "", reasoningEffort: "medium" });
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.tasks().then(setTasks).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    api.graph().then((graph) => setAgents(graph.nodes
      .filter((node) => node.kind === "agent")
      .map((node) => ({ ref: node.id, title: node.title }))
      .sort((left, right) => left.title.localeCompare(right.title)))).catch(() => undefined);
    const t = setInterval(refresh, 8_000);
    return () => clearInterval(t);
  }, [refresh]);

  const hierarchy = useMemo(() => {
    const byRef = new Map(tasks.map((task) => [task.ref, task]));
    const byName = new Map(tasks.map((task) => [task.ref.split("/").pop(), task]));
    const children = new Map<string, TaskRow[]>();
    const childRefs = new Set<string>();
    const resolve = (ref: string) => {
      const clean = ref.replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0];
      return byRef.get(clean) ?? byName.get(clean.split("/").pop());
    };

    for (const task of tasks) {
      const rows = (task.subtask_refs ?? []).flatMap((ref) => {
        const child = resolve(ref);
        return child ? [child] : [];
      });
      children.set(task.ref, rows);
      rows.forEach((child) => childRefs.add(child.ref));
    }

    const roots = tasks.filter((task) => !childRefs.has(task.ref));
    return { children, roots: roots.length ? roots : tasks };
  }, [tasks]);

  useEffect(() => {
    if (initializedHierarchy.current || hierarchy.roots.length === 0) return;
    initializedHierarchy.current = true;
    setExpanded(new Set(hierarchy.roots.filter((task) => task.subtasks > 0).map((task) => task.ref)));
  }, [hierarchy]);

  const visibleRows = useMemo(() => {
    const rows: Array<{ task: TaskRow; depth: number }> = [];
    const seen = new Set<string>();
    const add = (task: TaskRow, depth: number) => {
      if (seen.has(task.ref)) return;
      seen.add(task.ref);
      rows.push({ task, depth });
      if (!expanded.has(task.ref)) return;
      for (const child of hierarchy.children.get(task.ref) ?? []) add(child, depth + 1);
    };
    hierarchy.roots.forEach((task) => add(task, 0));
    return rows;
  }, [expanded, hierarchy]);

  function toggleExpanded(ref: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(ref)) next.delete(ref); else next.add(ref);
      return next;
    });
  }

  useEffect(() => {
    if (!creating) return;
    api.graph().then((g) =>
      setRunbooks(g.nodes.filter((n) => n.kind === "runbook").map((n) => n.id)),
    ).catch(() => undefined);
  }, [creating]);

  async function setReasoning(ref: string, reasoningEffort: ReasoningEffort) {
    setTasks((current) => current.map((task) =>
      task.ref === ref ? { ...task, reasoning_effort: reasoningEffort } : task));
    try { await api.setTaskReasoning(ref, reasoningEffort); } catch { refresh(); }
  }

  async function setAssignee(ref: string, agent: AgentOption) {
    const assignee = `[[${agent.ref}]]`;
    setTasks((current) => current.map((task) =>
      task.ref === ref ? { ...task, assignee } : task));
    try { await api.setTaskAssignee(ref, agent.ref); } catch { refresh(); }
  }

  async function runNow(task: TaskRow) {
    setBusyRef(task.ref);
    try { await api.runTask(task.ref, task.reasoning_effort); } catch { /* surfaced via status poll */ }
    setBusyRef(null);
    refresh();
  }

  async function assign() {
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/tasks`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title: form.title,
          runbook: form.runbook ? `[[${form.runbook}]]` : undefined,
          schedule: form.schedule || undefined,
          body: form.body,
          reasoning_effort: form.reasoningEffort,
          start: !form.schedule,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setCreating(false);
      setForm({ title: "", runbook: "", schedule: "", body: "", reasoningEffort: "medium" });
      refresh();
    } catch (e) {
      setError(String(e).slice(0, 200));
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-cyan-300/10 px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-cyan-300/50">
          {hierarchy.roots.length} roots · {tasks.length} tasks
        </span>
        <div className="flex items-center gap-2">
          <button onClick={() => setExpanded(new Set(tasks.filter((task) => task.subtasks > 0).map((task) => task.ref)))}
            title="Expand all task groups" className="font-mono text-[11px] text-cyan-300/50 hover:text-cyan-100">▾</button>
          <button onClick={() => setExpanded(new Set())}
            title="Collapse all task groups" className="font-mono text-[11px] text-cyan-300/50 hover:text-cyan-100">▸</button>
          <button onClick={() => setCreating((c) => !c)} title="Assign a new task"
            className="text-cyan-300/60 hover:text-cyan-100">
            {creating ? <X size={13} /> : <Plus size={13} />}
          </button>
          <button onClick={refresh} className="text-cyan-300/50 hover:text-cyan-100"><RefreshCw size={12} /></button>
        </div>
      </div>

      {creating ? (
        <div className="shrink-0 space-y-1.5 border-b border-cyan-300/15 bg-[#03101a]/60 p-2">
          <input value={form.title} placeholder="task title"
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className="w-full rounded border border-cyan-300/20 bg-[#020a12] px-2 py-1 font-mono text-[11px] text-cyan-50 outline-none focus:border-cyan-300/50" />
          <div className="flex gap-1.5">
            <select value={form.runbook}
              onChange={(e) => setForm({ ...form, runbook: e.target.value })}
              className="min-w-0 flex-1 rounded border border-cyan-300/20 bg-[#020a12] px-1 py-1 font-mono text-[10px] text-cyan-100">
              <option value="">runbook…</option>
              {runbooks.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <input value={form.schedule} placeholder="cron (optional)"
              onChange={(e) => setForm({ ...form, schedule: e.target.value })}
              className="w-32 rounded border border-cyan-300/20 bg-[#020a12] px-2 py-1 font-mono text-[10px] text-cyan-50 outline-none" />
            <select value={form.reasoningEffort}
              onChange={(e) => setForm({ ...form, reasoningEffort: e.target.value as ReasoningEffort })}
              title="Reasoning effort for this task"
              className="w-24 rounded border border-cyan-300/20 bg-[#020a12] px-1 py-1 font-mono text-[9px] uppercase text-cyan-100">
              <option value="none">None</option><option value="low">Low</option>
              <option value="medium">Medium</option><option value="high">High</option>
            </select>
          </div>
          <textarea value={form.body} placeholder="what needs to be accomplished"
            onChange={(e) => setForm({ ...form, body: e.target.value })} rows={2}
            className="w-full resize-none rounded border border-cyan-300/20 bg-[#020a12] px-2 py-1 font-mono text-[11px] text-cyan-50 outline-none" />
          {error ? <p className="font-mono text-[10px] text-rose-300">{error}</p> : null}
          <button onClick={assign} disabled={!form.title || !form.runbook}
            className="rounded border border-cyan-300/40 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-cyan-100 hover:bg-cyan-300/10 disabled:opacity-40">
            Assign{form.schedule ? " (scheduled)" : " + run"}
          </button>
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {tasks.length > 0 ? (
          <div className="sticky top-0 z-10 grid grid-cols-[minmax(0,1fr)_60px_116px_72px_28px] border-b border-cyan-300/15 bg-[#03101a]/95 px-2 py-1 font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/40">
            <span>Task</span>
            <span className="justify-self-center">State</span>
            <span className="justify-self-center">Agent</span>
            <span className="justify-self-center">Reason</span>
            <span />
          </div>
        ) : null}
        {visibleRows.map(({ task, depth }) => {
          const children = hierarchy.children.get(task.ref) ?? [];
          const hasChildren = children.length > 0;
          const isExpanded = expanded.has(task.ref);
          return (
            <div key={task.ref}
              className="grid grid-cols-[minmax(0,1fr)_60px_116px_72px_28px] items-center border-b border-cyan-300/8 px-2 py-1.5 hover:bg-cyan-300/[0.035]">
              <div className="flex min-w-0 items-start" style={{ paddingLeft: depth * 17 }}>
                <button onClick={() => hasChildren && toggleExpanded(task.ref)} disabled={!hasChildren}
                  title={hasChildren ? `${isExpanded ? "Collapse" : "Expand"} ${task.title}` : undefined}
                  className="mr-1 mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-cyan-300/55 hover:text-cyan-100 disabled:text-cyan-300/15">
                  {hasChildren ? (isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : <span className="text-[8px]">·</span>}
                </button>
                <div className="min-w-0">
                  <button onClick={() => openReader(task.ref)}
                    className={`block w-full truncate text-left font-mono hover:text-cyan-300 ${
                      hasChildren ? "text-[11px] font-semibold uppercase tracking-[0.1em] text-cyan-50" : "text-[11px] text-cyan-100"}`}>
                    {task.title}
                  </button>
                  <div className="flex min-w-0 gap-2 font-mono text-[8px] text-cyan-300/35">
                    {hasChildren ? <span>{children.length} subtasks</span> : null}
                    {task.schedule ? <span className="truncate">⏰ {task.schedule}</span> : null}
                    {task.blocked_reason ? <span className="truncate text-rose-300/70" title={task.blocked_reason}>{task.blocked_reason}</span> : null}
                  </div>
                </div>
              </div>
              {hasChildren ? <span /> : (
                <span className={`w-fit justify-self-center rounded border px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wider ${STATUS_STYLE[task.status] ?? STATUS_STYLE.draft}`}>
                  {task.status}
                </span>
              )}
              {hasChildren ? <span /> : (
                <AssigneeSelect task={task} agents={agents} onChange={setAssignee} />
              )}
              {hasChildren ? <span /> : (
                <select value={task.reasoning_effort}
                  onChange={(e) => setReasoning(task.ref, e.target.value as ReasoningEffort)}
                  title={`Reasoning effort for ${task.title}`}
                  aria-label={`Reasoning effort for ${task.title}`}
                  className="w-[66px] justify-self-center rounded border border-cyan-300/20 bg-[#020a12] px-1 py-0.5 font-mono text-[8px] uppercase text-cyan-200/70 outline-none hover:border-cyan-300/40">
                  <option value="none">None</option><option value="low">Low</option>
                  <option value="medium">Medium</option><option value="high">High</option>
                </select>
              )}
              {hasChildren ? <span /> : (
                <button onClick={() => runNow(task)}
                  disabled={busyRef === task.ref || task.status === "running"} title={`Run now with ${task.reasoning_effort} reasoning`}
                  className="justify-self-center rounded border border-cyan-300/25 p-1 text-cyan-300/60 hover:bg-cyan-300/10 disabled:opacity-30">
                  <Play size={10} />
                </button>
              )}
            </div>
          );
        })}
        {tasks.length === 0 ? (
          <p className="p-4 font-mono text-[11px] text-cyan-200/40">No task notes in the vault yet — assign one with +.</p>
        ) : null}
      </div>
    </div>
  );
}
