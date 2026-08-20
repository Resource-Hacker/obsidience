/** Tasks pane: fleet task list with statuses, run-now, and reader links. */

import { useCallback, useEffect, useState } from "react";
import { Play, RefreshCw } from "lucide-react";
import { api, openReader, type TaskRow } from "@/lib/api";

const STATUS_STYLE: Record<string, string> = {
  ready: "text-cyan-200 border-cyan-300/40",
  active: "text-emerald-200 border-emerald-300/50 animate-pulse",
  review: "text-amber-200 border-amber-300/50",
  done: "text-emerald-300/70 border-emerald-300/25",
  failed: "text-rose-300 border-rose-300/50",
  blocked: "text-rose-200 border-rose-300/40",
  draft: "text-cyan-200/50 border-cyan-300/20",
};

export function TasksPaneBody() {
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [busyRef, setBusyRef] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.tasks().then(setTasks).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8_000);
    return () => clearInterval(t);
  }, [refresh]);

  async function runNow(ref: string) {
    setBusyRef(ref);
    try { await api.runTask(ref); } catch { /* surfaced via status poll */ }
    setBusyRef(null);
    refresh();
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-cyan-300/10 px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-cyan-300/50">
          {tasks.length} tasks
        </span>
        <button onClick={refresh} className="text-cyan-300/50 hover:text-cyan-100"><RefreshCw size={12} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tasks.map((t) => (
          <div key={t.ref} className="flex items-center gap-2 border-b border-cyan-300/8 px-3 py-2">
            <span className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider ${STATUS_STYLE[t.status] ?? STATUS_STYLE.draft}`}>
              {t.status}
            </span>
            <button onClick={() => openReader(t.ref)}
              className="min-w-0 flex-1 truncate text-left font-mono text-[12px] text-cyan-100 hover:text-cyan-300">
              {t.title}
            </button>
            {t.schedule ? (
              <span className="shrink-0 font-mono text-[9px] text-cyan-300/40">⏰ {t.schedule}</span>
            ) : null}
            {t.blocked_reason ? (
              <span className="max-w-[38%] shrink-0 truncate font-mono text-[9px] text-rose-300/70" title={t.blocked_reason}>
                {t.blocked_reason}
              </span>
            ) : null}
            <button
              onClick={() => runNow(t.ref)}
              disabled={busyRef === t.ref || t.status === "active"}
              title="Run now"
              className="shrink-0 rounded border border-cyan-300/25 p-1 text-cyan-300/60 hover:bg-cyan-300/10 disabled:opacity-30">
              <Play size={11} />
            </button>
          </div>
        ))}
        {tasks.length === 0 ? (
          <p className="p-4 font-mono text-[11px] text-cyan-200/40">No task notes in the vault yet.</p>
        ) : null}
      </div>
    </div>
  );
}
