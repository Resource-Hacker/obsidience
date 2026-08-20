/** Reader: renders vault notes and is the owner editor for tasks/subtasks. */

import { useCallback, useEffect, useState } from "react";
import { Play, Save } from "lucide-react";
import { JarvisMarkdown } from "@/components/themes/jarvis/workspace/jarvis-markdown";
import {
  api,
  onOpenReader,
  openReader,
  type GraphNode,
  type NoteDoc,
  type ReasoningEffort,
  type TaskRow,
} from "@/lib/api";

interface TaskDraft {
  title: string;
  body: string;
  schedule: string;
  assignee: string;
  runbook: string;
  reasoning_effort: ReasoningEffort;
}

const FIELD_CLASS =
  "w-full rounded border border-cyan-300/20 bg-[#020a12] px-2 py-1.5 font-mono text-[10px] text-cyan-50 outline-none focus:border-cyan-300/50 disabled:opacity-45";

const TASK_STATUS_STYLE: Record<string, string> = {
  pending: "border-cyan-300/40 text-cyan-200",
  running: "animate-pulse border-emerald-300/60 bg-emerald-300/5 text-emerald-200",
  review: "border-amber-300/50 text-amber-200",
  completed: "border-emerald-300/25 text-emerald-300/70",
  failed: "border-rose-300/50 text-rose-300",
  blocked: "border-rose-300/40 text-rose-200",
  draft: "border-cyan-300/20 text-cyan-200/50",
};

const CHILD_LABELS: Record<string, string> = {
  tool: "Subtools",
  skill: "Subskills",
  runbook: "Subrunbooks",
  task: "Subtasks",
};

function cleanLink(value: string): string {
  return value.trim().replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0];
}

function resolveOption(value: string, options: Array<{ id: string }>): string {
  const clean = cleanLink(value);
  const leaf = clean.split("/").pop()?.toLowerCase();
  return options.find((option) =>
    option.id === clean || option.id.split("/").pop()?.toLowerCase() === leaf)?.id ?? clean;
}

function draftFor(
  note: NoteDoc,
  task: TaskRow,
  agents: Array<{ id: string }>,
  runbooks: Array<{ id: string }>,
): TaskDraft {
  return {
    title: note.title,
    body: note.body,
    schedule: task.schedule ?? "",
    assignee: resolveOption(task.assignee, agents),
    runbook: resolveOption(task.runbook, runbooks),
    reasoning_effort: task.reasoning_effort,
  };
}

function nextRunLabel(task: TaskRow, container = false): string {
  if (task.status === "running") return container
    ? "Task group running now — its active subtask is highlighted in Jobs and visible in Action Trace."
    : "Running now — live actions are visible in Terminal → Action Trace.";
  if (task.status === "review") return task.schedule
    ? "Schedule paused while this result is awaiting review."
    : "Awaiting review.";
  if (task.schedule && task.next_run) {
    return `Next run ${new Date(task.next_run * 1000).toLocaleString([], {
      dateStyle: "medium",
      timeStyle: "short",
    })}`;
  }
  if (task.schedule) return `Schedule inactive while task status is ${task.status}.`;
  if (task.status === "pending") return "Queued — starts on the next scheduler pass.";
  return container
    ? "Task group is not scheduled. Add a schedule to run its subtasks in order."
    : "Not scheduled. Use Run now for a one-off execution.";
}

export function ReaderPaneBody() {
  const [note, setNote] = useState<NoteDoc | null>(null);
  const [articleNode, setArticleNode] = useState<GraphNode | null>(null);
  const [task, setTask] = useState<TaskRow | null>(null);
  const [agents, setAgents] = useState<GraphNode[]>([]);
  const [runbooks, setRunbooks] = useState<GraphNode[]>([]);
  const [draft, setDraft] = useState<TaskDraft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (ref: string) => {
    setError(null);
    setNotice(null);
    try {
      const [nextNote, tasks, graph] = await Promise.all([api.article(ref), api.tasks(), api.graph()]);
      const nextAgents = graph.nodes.filter((node) => node.kind === "agent")
        .sort((left, right) => left.title.localeCompare(right.title));
      const nextRunbooks = graph.nodes.filter((node) => node.kind === "runbook")
        .sort((left, right) => left.title.localeCompare(right.title));
      const nextArticleNode = graph.nodes.find((node) => node.id === nextNote.ref) ?? null;
      const nextTask = tasks.find((row) => row.ref === nextNote.ref) ?? null;
      setNote(nextNote);
      setArticleNode(nextArticleNode);
      setTask(nextTask);
      setAgents(nextAgents);
      setRunbooks(nextRunbooks);
      setDraft(nextTask ? draftFor(nextNote, nextTask, nextAgents, nextRunbooks) : null);
      setDirty(false);
    } catch (cause) {
      setError(String(cause));
    }
  }, []);

  useEffect(() => onOpenReader(load), [load]);

  // A task Reader is a live operational view, not a snapshot. Poll only the
  // tiny task projection so running/completion and the next firing stay fresh.
  useEffect(() => {
    if (!note || note.kind !== "task" || articleNode?.synthetic) return;
    let live = true;
    const pull = () => api.tasks().then((rows) => {
      if (!live) return;
      const current = rows.find((row) => row.ref === note.ref);
      if (current) setTask(current);
    }).catch(() => undefined);
    const timer = setInterval(pull, 2_000);
    return () => { live = false; clearInterval(timer); };
  }, [articleNode?.synthetic, note]);

  function updateDraft(update: Partial<TaskDraft>) {
    setDraft((current) => current ? { ...current, ...update } : current);
    setDirty(true);
    setNotice(null);
  }

  async function saveTask(): Promise<boolean> {
    if (!note || !task || !draft || !draft.title.trim()) return false;
    setSaving(true);
    setError(null);
    try {
      await api.updateTask(note.ref, draft);
      await load(note.ref);
      setNotice("Task saved.");
      return true;
    } catch (cause) {
      setError(String(cause));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function runNow() {
    if (!note || !task || !draft) return;
    if (dirty && !(await saveTask())) return;
    setLaunching(true);
    setError(null);
    setTask({ ...task, status: "running" });
    try {
      await api.runTask(note.ref, draft.reasoning_effort);
      setNotice("Run dispatched. Status and Action Trace are now live.");
    } catch (cause) {
      setError(String(cause));
      await load(note.ref);
    } finally {
      setLaunching(false);
    }
  }

  if (error && !note) return <p className="p-4 font-mono text-[11px] text-rose-300">{error}</p>;
  if (!note) {
    return (
      <p className="p-4 font-mono text-[11px] text-cyan-200/40">
        Click a node on the graph (or a task title) to read it here.
      </p>
    );
  }

  if (note.kind === "task" && task && draft) {
    const container = task.subtasks > 0;
    const running = task.status === "running";
    const operationalRefs = new Set((task.subtask_refs ?? []).map(cleanLink));
    const taxonomyRefs = (articleNode?.children ?? [])
      .filter((ref) => !operationalRefs.has(cleanLink(ref)));
    return (
      <div className="h-full overflow-y-auto p-3">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-[9px] uppercase tracking-[0.25em] text-cyan-300/40">
              {container ? `task group · ${task.subtasks} subtasks` : "task"} · {note.ref}
            </p>
            <h1 className="mt-1 truncate font-mono text-[15px] uppercase tracking-[0.12em] text-cyan-50">
              {draft.title}
            </h1>
          </div>
          {!container ? (
            <span className={`shrink-0 rounded border px-2 py-1 font-mono text-[9px] uppercase tracking-[0.14em] ${TASK_STATUS_STYLE[task.status] ?? TASK_STATUS_STYLE.draft}`}>
              {task.status === "running" ? "● running" : task.status}
            </span>
          ) : null}
        </div>

        <div className={`mb-3 rounded border p-2 ${running ? "border-emerald-300/25 bg-emerald-300/[0.035]" : "border-cyan-300/12 bg-[#020a12]"}`}>
          <p className={`font-mono text-[10px] ${running ? "text-emerald-200" : "text-cyan-100/70"}`}>
            {nextRunLabel(task, container)}
          </p>
          {task.last_run ? <p className="mt-1 font-mono text-[8px] text-cyan-300/35">Last run: {task.last_run}</p> : null}
          {task.blocked_reason ? <p className="mt-1 font-mono text-[9px] text-rose-300/80">{task.blocked_reason}</p> : null}
        </div>

        <div className="space-y-2 rounded border border-cyan-300/12 bg-[#03101a]/55 p-2.5">
          <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
            Title
            <input value={draft.title} disabled={running}
              onChange={(event) => updateDraft({ title: event.target.value })}
              className={`${FIELD_CLASS} mt-1`} />
          </label>

          {!container ? (
            <>
              <div className="grid grid-cols-2 gap-2">
                <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
                  Agent
                  <select value={draft.assignee} disabled={running}
                    onChange={(event) => updateDraft({ assignee: event.target.value })}
                    className={`${FIELD_CLASS} mt-1`}>
                    <option value="">Unassigned</option>
                    {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.title}</option>)}
                  </select>
                </label>
                <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
                  Reasoning
                  <select value={draft.reasoning_effort} disabled={running}
                    onChange={(event) => updateDraft({ reasoning_effort: event.target.value as ReasoningEffort })}
                    className={`${FIELD_CLASS} mt-1`}>
                    <option value="none">None</option><option value="low">Low</option>
                    <option value="medium">Medium</option><option value="high">High</option>
                  </select>
                </label>
              </div>
              <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
                Runbook
                <select value={draft.runbook} disabled={running}
                  onChange={(event) => updateDraft({ runbook: event.target.value })}
                  className={`${FIELD_CLASS} mt-1`}>
                  <option value="">No runbook</option>
                  {runbooks.map((runbook) => <option key={runbook.id} value={runbook.id}>{runbook.title}</option>)}
                </select>
              </label>
            </>
          ) : null}

          <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
            Schedule
            <input value={draft.schedule} disabled={running} placeholder="cron, e.g. 0 * * * *"
              onChange={(event) => updateDraft({ schedule: event.target.value })}
              className={`${FIELD_CLASS} mt-1`} />
          </label>

          <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
            Task instructions
            <textarea value={draft.body} disabled={running} rows={7}
              onChange={(event) => updateDraft({ body: event.target.value })}
              className={`${FIELD_CLASS} mt-1 resize-y leading-4`} />
          </label>

          {container && task.subtask_refs?.length ? (
            <div>
              <p className="mb-1 font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">Subtasks</p>
              <div className="flex flex-wrap gap-1">
                {task.subtask_refs.map((ref) => (
                  <button key={ref} onClick={() => openReader(cleanLink(ref))}
                    className="rounded border border-cyan-300/20 px-2 py-1 font-mono text-[9px] text-cyan-100/70 hover:border-cyan-300/45 hover:text-cyan-50">
                    {cleanLink(ref).split("/").pop()}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {taxonomyRefs.length ? (
            <div>
              <p className="mb-1 font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">Task hierarchy</p>
              <div className="flex flex-wrap gap-1">
                {taxonomyRefs.map((ref) => (
                  <button key={ref} onClick={() => openReader(cleanLink(ref))}
                    className="rounded border border-cyan-300/20 px-2 py-1 font-mono text-[9px] text-cyan-100/70 hover:border-cyan-300/45 hover:text-cyan-50">
                    {cleanLink(ref).split("/").pop()}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {error ? <p className="font-mono text-[9px] text-rose-300">{error}</p> : null}
          {notice ? <p className="font-mono text-[9px] text-emerald-300/75">{notice}</p> : null}
          <div className="flex gap-2 pt-1">
            <button onClick={() => void saveTask()} disabled={!dirty || saving || running || !draft.title.trim()}
              className="flex items-center gap-1 rounded border border-cyan-300/35 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-100 hover:bg-cyan-300/10 disabled:opacity-35">
              <Save size={10} /> {saving ? "Saving" : "Save task"}
            </button>
            {!container ? (
              <button onClick={() => void runNow()} disabled={launching || running || !draft.runbook}
                className="flex items-center gap-1 rounded border border-emerald-300/35 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.14em] text-emerald-200 hover:bg-emerald-300/10 disabled:opacity-35">
                <Play size={10} /> {running ? "Running" : launching ? "Starting" : dirty ? "Save + run" : "Run now"}
              </button>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  const childRefs = articleNode?.children ?? articleNode?.subtasks ?? [];
  const childLabel = CHILD_LABELS[note.kind] ?? "Children";

  return (
    <div className="h-full overflow-y-auto p-4">
      <p className="font-mono text-[9px] uppercase tracking-[0.25em] text-cyan-300/40">{note.kind} · {note.ref}</p>
      <h1 className="mb-3 mt-1 font-mono text-[15px] uppercase tracking-[0.12em] text-cyan-50">{note.title}</h1>
      {Object.keys(note.meta).length ? (
        <div className="mb-3 rounded border border-cyan-300/10 bg-[#020a12] p-2">
          {Object.entries(note.meta).slice(0, 10).map(([key, value]) => (
            <p key={key} className="font-mono text-[10px] text-cyan-200/60">
              <span className="text-cyan-300/40">{key}:</span> {value}
            </p>
          ))}
        </div>
      ) : null}
      <div className="text-[12.5px] leading-relaxed text-cyan-100/90">
        <JarvisMarkdown content={note.body} />
      </div>
      {childRefs.length ? (
        <div className="mt-4 border-t border-cyan-300/10 pt-3">
          <p className="mb-1.5 font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">{childLabel}</p>
          <div className="flex flex-wrap gap-1">
            {childRefs.map((ref) => (
              <button key={ref} onClick={() => openReader(cleanLink(ref))}
                className="rounded border border-cyan-300/20 px-2 py-1 font-mono text-[9px] text-cyan-100/70 hover:border-cyan-300/45 hover:text-cyan-50">
                {articleNode?.synthetic
                  ? cleanLink(ref).split("/").pop()?.split(".").pop()
                  : cleanLink(ref).split("/").pop()}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
