/** Harness status: counts, LLM target, voice availability, recent runs. */

import { useEffect, useState } from "react";
import { api, type HarnessStatus } from "@/lib/api";

export function StatusPaneBody() {
  const [status, setStatus] = useState<HarnessStatus | null>(null);
  const [runs, setRuns] = useState<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    const pull = () => {
      api.status().then(setStatus).catch(() => setStatus(null));
      api.runs().then(setRuns).catch(() => undefined);
    };
    pull();
    const t = setInterval(pull, 10_000);
    return () => clearInterval(t);
  }, []);

  if (!status) {
    return (
      <p className="p-4 font-mono text-[11px] text-rose-300/80">
        Harness offline — start it with <code>obsidience serve</code>.
      </p>
    );
  }
  return (
    <div className="h-full space-y-2 overflow-y-auto p-3 font-mono text-[11px] text-cyan-100/85">
      <p>{status.notes} notes · {status.tasks} tasks · {status.proposals_pending} pending reviews</p>
      <p className="text-cyan-200/60">
        {Object.entries(status.tasks_by_status).map(([k, v]) => `${k}:${v}`).join("  ")}
      </p>
      <p className="text-cyan-200/60">llm {status.llm.model} @ {status.llm.base_url}</p>
      <p className="text-cyan-200/60">stt {status.voice.stt ? "ready" : `off (${status.voice.reason ?? "?"})`}</p>
      <div className="border-t border-cyan-300/10 pt-2">
        <p className="mb-1 text-[9px] uppercase tracking-[0.2em] text-cyan-300/40">recent runs</p>
        {runs.slice(0, 8).map((r) => (
          <p key={String(r.id)} className="truncate text-[10px] text-cyan-200/60">
            [{String(r.status)}] {String(r.task_ref)} — {String(r.summary).slice(0, 80)}
          </p>
        ))}
      </div>
    </div>
  );
}
