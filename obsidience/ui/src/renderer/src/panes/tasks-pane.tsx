/** Tasks pane — operational Tasks with schedule or event triggers. The accepted
 *  task catalog lives in the Library. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Play, Plus, RefreshCw, X } from "lucide-react";
import {
  API_BASE,
  api,
  openReader,
  type CheckoutAgent,
  type ModelOption,
  type ModelPreference,
  type ReasoningEffort,
  type TaskRow,
} from "@/lib/api";
import {
  knowledgeRoleForAgent,
  paintKnowledgeRoleIcon,
} from "@/components/themes/obsidience/knowledge-role-icons";

interface AgentOption { ref: string; title: string }
interface TaskTreeNode {
  ref: string;
  title: string;
  children: string[];
  synthetic: boolean;
}

const AGENT_ROLES: ReadonlyArray<{ id: CheckoutAgent; label: string }> = [
  { id: "executive", label: "JARVIS" },
  { id: "guardian", label: "Heimdall" },
  { id: "curator", label: "Alexandria" },
  { id: "researcher", label: "Darwin" },
];

const ASSIGNED_STYLE: Record<CheckoutAgent, string> = {
  executive: "border-cyan-300/70 bg-cyan-300/15 shadow-[0_0_9px_rgba(103,232,249,0.45)]",
  guardian: "border-blue-400/70 bg-blue-400/15 shadow-[0_0_9px_rgba(96,165,250,0.45)]",
  curator: "border-amber-400/70 bg-amber-400/15 shadow-[0_0_9px_rgba(251,191,36,0.45)]",
  researcher: "border-purple-400/70 bg-purple-400/15 shadow-[0_0_9px_rgba(192,132,252,0.45)]",
};

const UNASSIGNED_STYLE: Record<CheckoutAgent, string> = {
  executive: "border-cyan-300/15",
  guardian: "border-blue-400/15",
  curator: "border-amber-400/15",
  researcher: "border-purple-400/15",
};

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

function AgentSummary({ assignees, agents }: { assignees: string[]; agents: AgentOption[] }) {
  const resolved = assignees.map((assignee) => {
    const name = agentName(assignee);
    const option = agents.find((agent) =>
      cleanLink(assignee) === agent.ref || name.toLowerCase() === agent.title.toLowerCase());
    return { ref: option?.ref ?? cleanLink(assignee), title: option?.title ?? name };
  }).filter((agent) => agent.title);
  const assignedRoles = new Set<CheckoutAgent>();
  resolved.forEach((agent) => {
    const role = knowledgeRoleForAgent(agent.ref || agent.title);
    if (role !== "library") assignedRoles.add(role);
  });
  const label = resolved.map((agent) => agent.title).join(" + ") || "Unassigned";
  return (
    <div title={label} aria-label={`Agent assignment: ${label}`}
      className="flex w-[140px] items-center justify-center gap-1">
      {AGENT_ROLES.map(({ id, label: agentLabel }) => {
        const assigned = assignedRoles.has(id);
        return (
          <span key={id} role="img"
            aria-label={`${agentLabel}: ${assigned ? "assigned" : "not assigned"}`}
            title={`${agentLabel} · ${assigned ? "assigned" : "not assigned"}`}
            className={`flex h-6 w-6 cursor-default items-center justify-center rounded border transition-all ${
              assigned
                ? ASSIGNED_STYLE[id]
                : `${UNASSIGNED_STYLE[id]} bg-[#020a0c]/70 opacity-55`
            }`}>
            <AgentGlyph name={id} size={17} />
          </span>
        );
      })}
    </div>
  );
}

export function TasksPaneBody() {
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [graphReady, setGraphReady] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const initializedHierarchy = useRef(false);
  const [busyRef, setBusyRef] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [taskNodes, setTaskNodes] = useState<TaskTreeNode[]>([]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [tasksLoaded, setTasksLoaded] = useState(false);
  const [tasksLoadError, setTasksLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<{ task: string; schedule: string; request: string }>(
    { task: "", schedule: "", request: "" },
  );
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    // Task truth is independent of optional graph/model decoration. A slow or
    // failed companion request must not turn valid scheduled/event Tasks into
    // a false empty board.
    api.tasks().then((taskRows) => {
      setTasks(taskRows);
      setTasksLoaded(true);
      setTasksLoadError(null);
    }).catch((reason: unknown) => {
      setTasksLoaded(true);
      setTasksLoadError(reason instanceof Error ? reason.message : String(reason));
    });
    api.graph().then((graph) => {
      setAgents(graph.nodes
        .filter((node) => node.kind === "agent" || node.id === "Agents/Executive/Executive")
        .map((node) => ({ ref: node.id, title: node.title }))
        .sort((left, right) => left.title.localeCompare(right.title)));
      setTaskNodes(graph.nodes
        .filter((node) => node.kind === "task" || node.tags?.includes("task-taxonomy"))
        .map((node) => ({
          ref: node.id,
          title: node.title,
          children: node.children ?? [],
          synthetic: Boolean(node.synthetic),
        })));
      setGraphReady(true);
    }).catch(() => undefined);
    api.models().then((modelCatalog) => {
      setModels(modelCatalog.models);
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3_000);
    return () => clearInterval(t);
  }, [refresh]);

  const scheduledTasks = useMemo(() => tasks.filter((task) => Boolean(task.schedule)), [tasks]);
  const eventCount = useMemo(
    () => tasks.reduce(
      (count, task) => count + (task.enabled === false ? 0 : task.triggers.length),
      0,
    ),
    [tasks],
  );
  const boardTasks = useMemo(
    () => tasks.filter((task) => Boolean(task.schedule) ||
      (task.triggers.length > 0 && task.enabled !== false) ||
      task.status === "running"),
    [tasks],
  );
  const taskCatalog = useMemo(
    () => [...tasks].sort((left, right) => left.title.localeCompare(right.title)),
    [tasks],
  );

  const hierarchy = useMemo(() => {
    const byRef = new Map(taskNodes.map((node) => [node.ref, node]));
    const operationalByRef = new Map(tasks.map((task) => [task.ref, task]));
    for (const task of tasks) {
      if (!byRef.has(task.ref)) {
        byRef.set(task.ref, {
          ref: task.ref,
          title: task.title,
          children: task.subtask_refs ?? [],
          synthetic: false,
        });
      }
    }
    const graphChildren = new Map<string, TaskTreeNode[]>();
    const graphParents = new Map<string, Set<string>>();
    for (const node of byRef.values()) {
      const rows = node.children.flatMap((ref) => {
        const child = byRef.get(ref);
        return child ? [child] : [];
      });
      graphChildren.set(node.ref, rows);
      rows.forEach((child) => {
        const refs = graphParents.get(child.ref) ?? new Set<string>();
        refs.add(node.ref);
        graphParents.set(child.ref, refs);
      });
    }
    const executionChildren = new Map<string, TaskTreeNode[]>();
    for (const task of tasks) {
      executionChildren.set(task.ref, (task.subtask_refs ?? []).flatMap((ref) => {
        const child = byRef.get(ref);
        return child ? [child] : [];
      }));
    }

    const seedRefs = new Set(boardTasks.map((task) => task.ref));
    const scopedRefs = new Set<string>();
    const ancestorRefs = new Set<string>();
    const inheritedRefs = new Set<string>();
    const operationalRefs = new Set<string>();
    const includeExecutionDescendants = (ref: string, seen = new Set<string>()) => {
      if (seen.has(ref)) return;
      seen.add(ref);
      operationalRefs.add(ref);
      for (const child of executionChildren.get(ref) ?? []) {
        scopedRefs.add(child.ref);
        inheritedRefs.add(child.ref);
        includeExecutionDescendants(child.ref, seen);
      }
    };
    const includeAncestors = (ref: string, seen = new Set<string>()) => {
      if (seen.has(ref)) return;
      seen.add(ref);
      scopedRefs.add(ref);
      for (const parent of graphParents.get(ref) ?? []) {
        ancestorRefs.add(parent);
        includeAncestors(parent, seen);
      }
    };
    const includeGraphDescendants = (ref: string, seen = new Set<string>()) => {
      if (seen.has(ref)) return;
      seen.add(ref);
      for (const child of graphChildren.get(ref) ?? []) {
        scopedRefs.add(child.ref);
        inheritedRefs.add(child.ref);
        includeGraphDescendants(child.ref, seen);
      }
    };
    for (const seed of boardTasks) {
      scopedRefs.add(seed.ref);
      includeExecutionDescendants(seed.ref);
    }
    // Authored subtasks decide which work inherits the trigger. The graph then
    // supplies their real placement and every leaf Task's own descendant
    // scope. This keeps Tasks filtered without flattening graph containers such
    // as Ingest into false terminal rows.
    for (const ref of operationalRefs) includeAncestors(ref);
    for (const ref of operationalRefs) {
      if ((executionChildren.get(ref) ?? []).length === 0) includeGraphDescendants(ref);
    }
    const scopedChildren = new Map<string, TaskTreeNode[]>();
    for (const ref of scopedRefs) {
      scopedChildren.set(ref, (graphChildren.get(ref) ?? [])
        .filter((child) => scopedRefs.has(child.ref)));
    }
    const graphContains = (root: string, target: string, seen = new Set<string>()): boolean => {
      if (root === target) return true;
      if (seen.has(root)) return false;
      seen.add(root);
      return (graphChildren.get(root) ?? []).some((child) =>
        graphContains(child.ref, target, seen));
    };
    // A malformed or not-yet-categorized real subtask must remain visible.
    // Use its authored edge only when the knowledge graph has no path for it.
    for (const [parent, rows] of executionChildren) {
      for (const child of rows) {
        if (!scopedRefs.has(parent) || !scopedRefs.has(child.ref) || graphContains(parent, child.ref)) continue;
        const current = scopedChildren.get(parent) ?? [];
        if (!current.some((candidate) => candidate.ref === child.ref)) current.push(child);
        scopedChildren.set(parent, current);
      }
    }
    const scopedParents = new Map<string, Set<string>>();
    for (const [parent, rows] of scopedChildren) {
      rows.forEach((child) => {
        const refs = scopedParents.get(child.ref) ?? new Set<string>();
        refs.add(parent);
        scopedParents.set(child.ref, refs);
      });
    }
    const scopedNodes = [...scopedRefs].flatMap((ref) => byRef.has(ref) ? [byRef.get(ref)!] : []);
    const roots = scopedNodes.filter((node) =>
      (scopedParents.get(node.ref) ?? new Set()).size === 0);
    const assigneesByRef = new Map<string, string[]>();
    const collectAssignees = (ref: string, stack = new Set<string>()): string[] => {
      const cached = assigneesByRef.get(ref);
      if (cached) return cached;
      if (stack.has(ref)) return [];
      const nextStack = new Set(stack).add(ref);
      const direct = operationalByRef.get(ref)?.assignee;
      const collected = direct ? [direct] : (scopedChildren.get(ref) ?? [])
        .flatMap((child) => collectAssignees(child.ref, nextStack));
      const unique = [...new Map(collected.map((assignee) => [cleanLink(assignee), assignee])).values()];
      assigneesByRef.set(ref, unique);
      return unique;
    };
    scopedRefs.forEach((ref) => collectAssignees(ref));
    return {
      children: scopedChildren, roots, seedRefs, ancestorRefs, operationalRefs,
      operationalByRef, assigneesByRef,
    };
  }, [boardTasks, taskNodes, tasks]);

  useEffect(() => {
    if (!graphReady || initializedHierarchy.current || hierarchy.roots.length === 0) return;
    initializedHierarchy.current = true;
    const defaults = new Set([...hierarchy.ancestorRefs, ...hierarchy.seedRefs, ...hierarchy.operationalRefs]
      .filter((ref) => (hierarchy.children.get(ref) ?? []).length > 0));
    setExpanded(defaults);
  }, [graphReady, hierarchy]);

  const visibleRows = useMemo(() => {
    type VisibleRow = { node: TaskTreeNode; task: TaskRow | null; depth: number;
      parent: TaskTreeNode | null; scopeOwner: TaskRow | null; excludedBy: string | null };
    const rows: VisibleRow[] = [];
    const seen = new Set<string>();
    const add = (node: TaskTreeNode, depth: number, parent: TaskTreeNode | null,
      inheritedScopeOwner: TaskRow | null, inheritedExclusion: string | null) => {
      if (seen.has(node.ref)) return;
      seen.add(node.ref);
      const task = hierarchy.operationalByRef.get(node.ref) ?? null;
      const ownsTrigger = hierarchy.seedRefs.has(node.ref);
      // A separately triggered Task starts a fresh scope. Otherwise this row
      // inherits the nearest real Task above it. Once a real Task is reached,
      // its graph children inherit from that Task rather than from a distant
      // scheduler root (for example Collect inherits Ingest, not Wiki).
      const scopeOwner = ownsTrigger ? null : inheritedScopeOwner;
      const exactExcluded = scopeOwner &&
        (scopeOwner.excluded_subtask_refs ?? []).includes(node.ref) ? node.ref : null;
      const excludedBy = ownsTrigger ? null : inheritedExclusion ?? exactExcluded;
      rows.push({ node, task, depth, parent, scopeOwner, excludedBy });
      if (!expanded.has(node.ref)) return;
      const childScopeOwner = task && hierarchy.operationalRefs.has(node.ref)
        ? task
        : inheritedScopeOwner;
      for (const child of hierarchy.children.get(node.ref) ?? []) {
        add(child, depth + 1, node, childScopeOwner, excludedBy);
      }
    };
    hierarchy.roots.forEach((node) => add(node, 0, null, null, null));
    return rows;
  }, [expanded, hierarchy]);
  const runningCount = tasks.filter((task) => task.status === "running" && task.subtasks === 0).length;

  function toggleExpanded(ref: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(ref)) next.delete(ref); else next.add(ref);
      return next;
    });
  }

  async function setReasoning(ref: string, reasoningEffort: ReasoningEffort) {
    setTasks((current) => current.map((task) =>
      task.ref === ref ? { ...task, reasoning_effort: reasoningEffort } : task));
    try { await api.setTaskReasoning(ref, reasoningEffort); } catch { refresh(); }
  }

  async function setModel(ref: string, model: ModelPreference) {
    setTasks((current) => current.map((task) =>
      task.ref === ref ? { ...task, model } : task));
    try {
      const result = await api.setTaskModel(ref, model);
      setTasks((current) => current.map((task) => task.ref === ref
        ? { ...task, model: result.model, resolved_model: result.resolved_model }
        : task));
    } catch {
      refresh();
    }
  }

  async function toggleExclusion(owner: TaskRow, taskRef: string, excluded: boolean) {
    const next = new Set(owner.excluded_subtask_refs ?? []);
    if (excluded) next.delete(taskRef); else next.add(taskRef);
    const optimistic = [...next];
    setTasks((current) => current.map((task) =>
      task.ref === owner.ref ? { ...task, excluded_subtask_refs: optimistic } : task));
    try {
      const result = await api.setTaskExclusions(owner.ref, optimistic);
      setTasks((current) => current.map((task) => task.ref === owner.ref
        ? { ...task, excluded_subtask_refs: result.excluded_subtask_refs } : task));
    } catch {
      refresh();
    }
  }

  async function runNow(task: TaskRow) {
    setBusyRef(task.ref);
    try { await api.runTask(task.ref, task.reasoning_effort); } catch { /* surfaced via status poll */ }
    setBusyRef(null);
    refresh();
  }

  async function activateTask() {
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/tasks`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          task: form.task,
          schedule: form.schedule || undefined,
          params: form.request.trim() ? { request: form.request.trim() } : undefined,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setCreating(false);
      setForm({ task: "", schedule: "", request: "" });
      refresh();
    } catch (e) {
      setError(String(e).slice(0, 200));
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-cyan-300/10 px-3 py-1.5">
        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.16em]">
          <span className="text-cyan-300/50">{scheduledTasks.length} schedules</span>
          <span className="text-cyan-300/50">{eventCount} events</span>
          {runningCount > 0 ? (
            <span className="animate-pulse text-emerald-300">
              ● {runningCount} running
            </span>
          ) : null}
          <span className="text-cyan-300/35">task catalog lives in Library</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setCreating((c) => !c)} title="Activate or schedule a task"
            className="text-cyan-300/60 hover:text-cyan-100">
            {creating ? <X size={13} /> : <Plus size={13} />}
          </button>
          <button onClick={refresh} className="text-cyan-300/50 hover:text-cyan-100"><RefreshCw size={12} /></button>
        </div>
      </div>

      {creating ? (
        <div className="shrink-0 space-y-1.5 border-b border-cyan-300/15 bg-[#03101a]/60 p-2">
          <div className="flex gap-1.5">
            <select value={form.task}
              onChange={(e) => setForm({ ...form, task: e.target.value })}
              className="min-w-0 flex-1 rounded border border-cyan-300/20 bg-[#020a12] px-1 py-1 font-mono text-[10px] text-cyan-100">
              <option value="">task…</option>
              {taskCatalog.map((task) => (
                <option key={task.ref} value={task.ref}>{task.title}</option>
              ))}
            </select>
            <input value={form.schedule} placeholder="schedule trigger · cron"
              onChange={(e) => setForm({ ...form, schedule: e.target.value })}
              className="w-40 rounded border border-cyan-300/20 bg-[#020a12] px-2 py-1 font-mono text-[10px] text-cyan-50 outline-none" />
          </div>
          <textarea value={form.request} placeholder="optional target or request"
            onChange={(e) => setForm({ ...form, request: e.target.value })} rows={2}
            className="w-full resize-none rounded border border-cyan-300/20 bg-[#020a12] px-2 py-1 font-mono text-[11px] text-cyan-50 outline-none" />
          {error ? <p className="font-mono text-[10px] text-rose-300">{error}</p> : null}
          <button onClick={activateTask} disabled={!form.task}
            className="rounded border border-cyan-300/40 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-cyan-100 hover:bg-cyan-300/10 disabled:opacity-40">
            {form.schedule ? "Schedule task" : "Run task"}
          </button>
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!tasksLoaded ? (
          <p className="p-4 text-center font-mono text-[10px] text-cyan-300/40">
            Loading task activations…
          </p>
        ) : tasksLoadError ? (
          <p className="p-4 text-center font-mono text-[10px] text-rose-300/70">
            Task activations unavailable · {tasksLoadError}
          </p>
        ) : null}
        {boardTasks.length > 0 ? (
          <div className="sticky top-0 z-10 grid grid-cols-[minmax(0,1fr)_150px_100px_72px_52px] border-b border-cyan-300/15 bg-[#03101a]/95 px-2 py-1 font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/40">
            <span>Task</span>
            <span className="justify-self-center">Agent</span>
            <span className="justify-self-center">Model</span>
            <span className="justify-self-center">Reason</span>
            <span className="justify-self-center">Action</span>
          </div>
        ) : null}
        {visibleRows.map((row) => {
          const { node, task, depth, parent, scopeOwner, excludedBy } = row;
          const displayTitle = task?.title ?? node.title;
          const children = hierarchy.children.get(node.ref) ?? [];
          const hasChildren = children.length > 0;
          const isTaskLeaf = !hasChildren;
          const isConfigurableTask = Boolean(task?.runbook);
          const isExpanded = expanded.has(node.ref);
          const exactExcluded = excludedBy === node.ref;
          const inheritedExcluded = Boolean(excludedBy && !exactExcluded);
          const canToggleExclusion = Boolean(scopeOwner && !inheritedExcluded);
          const assignmentSource = task?.assignee
            ? [task.assignee]
            : scopeOwner?.assignee
              ? [scopeOwner.assignee]
              : hierarchy.assigneesByRef.get(node.ref) ?? [];
          const effectiveStatus = task?.status || scopeOwner?.status;
          const running = effectiveStatus === "running" && !excludedBy;
          const notableStatus = task && ["running", "review", "failed", "blocked"].includes(task.status)
            ? task.status
            : null;
          return (
            <div key={node.ref}
              className={`grid grid-cols-[minmax(0,1fr)_150px_100px_72px_52px] items-center border-b border-cyan-300/8 px-2 py-1.5 hover:bg-cyan-300/[0.035] ${excludedBy ? "opacity-40" : ""} ${running ? "bg-emerald-300/[0.045]" : ""}`}>
              <div className="flex min-w-0 items-start" style={{ paddingLeft: depth * 17 }}>
                <button onClick={() => hasChildren && toggleExpanded(node.ref)} disabled={!hasChildren}
                  title={hasChildren ? `${isExpanded ? "Collapse" : "Expand"} ${displayTitle}` : undefined}
                  className="mr-1 mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-cyan-300/55 hover:text-cyan-100 disabled:text-cyan-300/15">
                  {hasChildren ? (isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : <span className="text-[8px]">·</span>}
                </button>
                <div className="min-w-0">
                  <button onClick={() => openReader(node.ref)}
                    className={`flex w-full items-center gap-1 truncate text-left font-mono hover:text-cyan-300 ${
                    !isTaskLeaf ? "text-[11px] font-semibold uppercase tracking-[0.1em] text-cyan-50" : "text-[11px] text-cyan-100"}`}>
                    {running ? <span className="animate-pulse text-emerald-300">●</span> : null}
                    <span className="truncate">{displayTitle}</span>
                  </button>
                  <div className="flex min-w-0 gap-2 font-mono text-[8px] text-cyan-300/35">
                    {hasChildren ? <span>{children.length} included {children.length === 1 ? "subtask" : "subtasks"}</span> : null}
                    {task?.schedule ? <span className="truncate">trigger · schedule · {task.schedule}</span> : null}
                    {task?.triggers.length ? (
                      <span className="truncate">
                        trigger · event · {task.triggers.join(" · ")}
                      </span>
                    ) : null}
                    {task?.queue_depth ? <span className="truncate text-amber-200/75">{task.queue_depth} queued</span> : null}
                    {!task?.schedule && !task?.triggers.length && scopeOwner ? <span className="truncate">inherits · {scopeOwner.title}</span> : null}
                    {!task?.schedule && !task?.triggers.length && !scopeOwner && parent ? <span className="truncate">included · parent · {parent.title}</span> : null}
                    {!task?.schedule && !task?.triggers.length && !parent ? <span>included · ancestor</span> : null}
                    {notableStatus ? <span className={notableStatus === "running" ? "text-emerald-300/75" : notableStatus === "review" ? "text-amber-300/75" : "text-rose-300/75"}>{notableStatus}</span> : null}
                    {excludedBy ? <span className="truncate text-amber-300/75">excluded · {excludedBy.split("/").pop()}</span> : null}
                    {task?.blocked_reason ? <span className="truncate text-rose-300/70" title={task.blocked_reason}>{task.blocked_reason}</span> : null}
                  </div>
                </div>
              </div>
              <AgentSummary assignees={assignmentSource} agents={agents} />
              {isConfigurableTask && task ? (
                <select value={task.model}
                  disabled={task.status === "running"}
                  onChange={(e) => setModel(task.ref, e.target.value)}
                  title={`Model for ${task.title}; automatic resolves to ${task.resolved_model}`}
                  aria-label={`Model for ${task.title}`}
                  className="w-[94px] justify-self-center rounded border border-cyan-300/20 bg-[#020a12] px-1 py-0.5 font-mono text-[8px] text-cyan-200/70 outline-none hover:border-cyan-300/40 disabled:opacity-45">
                  <option value="auto">Auto · {task.resolved_model.includes("qwen") ? "Qwen" : "Gemma"}</option>
                  {models.filter((model) => model.task_capable).map((model) => (
                    <option key={model.id} value={model.id} disabled={!model.available}>
                      {model.label} · {model.quantization}
                    </option>
                  ))}
                </select>
              ) : task ? (
                <span className="justify-self-center font-mono text-[8px] text-cyan-200/45">
                  {task.resolved_model.includes("qwen") ? "Qwen" : "Gemma"}
                </span>
              ) : <span />}
              {isConfigurableTask && task ? (
                <select value={task.reasoning_effort}
                  disabled={task.status === "running"}
                  onChange={(e) => setReasoning(task.ref, e.target.value as ReasoningEffort)}
                  title={`Reasoning effort for ${task.title}`}
                  aria-label={`Reasoning effort for ${task.title}`}
                  className="w-[66px] justify-self-center rounded border border-cyan-300/20 bg-[#020a12] px-1 py-0.5 font-mono text-[8px] uppercase text-cyan-200/70 outline-none hover:border-cyan-300/40 disabled:opacity-45">
                  <option value="none">None</option><option value="low">Low</option>
                  <option value="medium">Medium</option><option value="high">High</option>
                  <option value="xhigh">XHigh</option>
                </select>
              ) : task ? (
                <span className="justify-self-center font-mono text-[8px] uppercase text-cyan-200/45">
                  {task.reasoning_effort}
                </span>
              ) : <span />}
              <div className="flex items-center justify-self-center gap-1">
                {canToggleExclusion && scopeOwner ? (
                  <button onClick={() => toggleExclusion(scopeOwner, node.ref, exactExcluded)}
                    disabled={scopeOwner.status === "running"}
                    title={exactExcluded
                      ? `Include ${displayTitle} in ${scopeOwner.title}`
                      : `Exclude ${displayTitle} and its descendants from ${scopeOwner.title}`}
                    aria-label={exactExcluded ? `Include ${displayTitle}` : `Exclude ${displayTitle}`}
                    className={`flex h-[20px] w-[20px] items-center justify-center rounded border font-mono text-[13px] disabled:opacity-30 ${exactExcluded
                      ? "border-emerald-300/35 text-emerald-300/75 hover:bg-emerald-300/10"
                      : "border-amber-300/25 text-amber-300/55 hover:bg-amber-300/10"}`}>
                    {exactExcluded ? "+" : "−"}
                  </button>
                ) : null}
                {isConfigurableTask && task && !excludedBy ? (
                  <button onClick={() => runNow(task)}
                    disabled={busyRef === task.ref || task.status === "running"} title={`Run now with ${task.reasoning_effort} reasoning`}
                    className="rounded border border-cyan-300/25 p-1 text-cyan-300/60 hover:bg-cyan-300/10 disabled:opacity-30">
                    <Play size={10} />
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
        {tasksLoaded && !tasksLoadError && boardTasks.length === 0 ? (
          <p className="p-4 font-mono text-[11px] text-cyan-200/40">No scheduled, event-triggered, or running tasks.</p>
        ) : null}
      </div>
    </div>
  );
}
