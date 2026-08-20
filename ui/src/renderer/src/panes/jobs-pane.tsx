/** Jobs pane — where tasks are ASSIGNED: create, schedule, run, and watch
 *  task instances under the interpreter. ("Job" is operational vocabulary
 *  for a task instance, not a fifth primitive.) */

import { useCallback, useEffect, useState } from "react";
import { Play, Plus, RefreshCw, X } from "lucide-react";
import { API_BASE, api, openReader, type TaskRow } from "@/lib/api";

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
  const [busyRef, setBusyRef] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [runbooks, setRunbooks] = useState<string[]>([]);
  const [form, setForm] = useState({ title: "", runbook: "", schedule: "", body: "" });
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.tasks().then(setTasks).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8_000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    if (!creating) return;
    api.graph().then((g) =>
      setRunbooks(g.nodes.filter((n) => n.kind === "runbook").map((n) => n.id)),
    ).catch(() => undefined);
  }, [creating]);

  async function runNow(ref: string) {
    setBusyRef(ref);
    try { await api.runTask(ref); } catch { /* surfaced via status poll */ }
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
          start: !form.schedule,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setCreating(false);
      setForm({ title: "", runbook: "", schedule: "", body: "" });
      refresh();
    } catch (e) {
      setError(String(e).slice(0, 200));
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-cyan-300/10 px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-cyan-300/50">
          {tasks.length} tasks
        </span>
        <div className="flex items-center gap-2">
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
        {(() => {
          const byRef = new Map(tasks.map((t) => [t.ref, t]));
          const resolveChild = (r: string) => byRef.get(r) ?? byRef.get(`Tasks/${r.split("/").pop()}`);
          const childRefs = new Set(tasks.flatMap((t) => (t.subtask_refs ?? []).map((r) => resolveChild(r)?.ref)).filter(Boolean));
          const roots = tasks.filter((t) => !childRefs.has(t.ref));
          const ordered: Array<{ t: TaskRow; depth: number }> = [];
          const push = (t: TaskRow, depth: number) => {
            ordered.push({ t, depth });
            if (depth < 3) for (const r of t.subtask_refs ?? []) {
              const c = resolveChild(r);
              if (c) push(c, depth + 1);
            }
          };
          roots.forEach((t) => push(t, 0));
          return ordered.map(({ t, depth }) => (
          <div key={t.ref} className="flex items-center gap-2 border-b border-cyan-300/8 py-2 pr-3"
            style={{ paddingLeft: 12 + depth * 18 }}>
            {depth > 0 ? <span className="shrink-0 font-mono text-[10px] text-cyan-300/30">└</span> : null}
            <span className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider ${STATUS_STYLE[t.status] ?? STATUS_STYLE.draft}`}>
              {t.status}
            </span>
            <button onClick={() => openReader(t.ref)}
              className={`min-w-0 flex-1 truncate text-left font-mono hover:text-cyan-300 ${
                t.subtasks ? "text-[12.5px] uppercase tracking-[0.14em] text-cyan-50" : "text-[12px] text-cyan-100"}`}>
              {t.title}
            </button>
            {t.assignee ? (
              <span className="shrink-0 font-mono text-[9px] text-teal-300/70">
                {t.assignee.replace(/\[\[Agents\//, "").replace(/\]\]/, "")}
              </span>
            ) : null}
            {t.subtasks ? (
              <span className="shrink-0 font-mono text-[9px] text-violet-300/70">▤ {t.subtasks}</span>
            ) : null}
            {t.schedule ? (
              <span className="shrink-0 font-mono text-[9px] text-cyan-300/40">⏰ {t.schedule}</span>
            ) : null}
            {t.blocked_reason ? (
              <span className="max-w-[34%] shrink-0 truncate font-mono text-[9px] text-rose-300/70" title={t.blocked_reason}>
                {t.blocked_reason}
              </span>
            ) : null}
            <button
              onClick={() => runNow(t.ref)}
              disabled={busyRef === t.ref || t.status === "running"}
              title="Run now"
              className="shrink-0 rounded border border-cyan-300/25 p-1 text-cyan-300/60 hover:bg-cyan-300/10 disabled:opacity-30">
              <Play size={11} />
            </button>
          </div>
          ));
        })()}
        {tasks.length === 0 ? (
          <p className="p-4 font-mono text-[11px] text-cyan-200/40">No task notes in the vault yet — assign one with +.</p>
        ) : null}
      </div>
    </div>
  );
}
