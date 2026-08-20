/** Review queue: staged agent proposals -> approve / reject. */

import { useCallback, useEffect, useState } from "react";
import { Check, X } from "lucide-react";
import { api, type Proposal } from "@/lib/api";

export function ReviewsPaneBody() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.reviews().then(setProposals).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 8_000);
    return () => clearInterval(t);
  }, [refresh]);

  async function decide(name: string, ok: boolean) {
    setError(null);
    try {
      if (ok) await api.approve(name);
      else await api.reject(name, "rejected from review pane");
    } catch (e) {
      setError(String(e));
    }
    refresh();
  }

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-cyan-300/10 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-cyan-300/50">
        {proposals.length} awaiting review
      </div>
      {error ? <p className="px-3 py-1 font-mono text-[10px] text-rose-300">{error}</p> : null}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {proposals.map((p) => (
          <div key={p.file} className="border-b border-cyan-300/8 px-3 py-2">
            <div className="flex items-center gap-2">
              <button onClick={() => setExpanded(expanded === p.file ? null : p.file)}
                className="min-w-0 flex-1 truncate text-left font-mono text-[12px] text-cyan-100 hover:text-cyan-300">
                <span className="text-amber-200/80">{p.action}</span> → {p.target}
              </button>
              <button onClick={() => decide(p.file, true)} title="Approve"
                className="rounded border border-emerald-300/40 p-1 text-emerald-300 hover:bg-emerald-300/10">
                <Check size={12} />
              </button>
              <button onClick={() => decide(p.file, false)} title="Reject"
                className="rounded border border-rose-300/40 p-1 text-rose-300 hover:bg-rose-300/10">
                <X size={12} />
              </button>
            </div>
            <p className="mt-1 font-mono text-[10px] text-cyan-200/50">
              by {p.agent}{p.task ? ` · task ${p.task}` : ""} — {p.reason}
            </p>
            {expanded === p.file ? (
              <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap rounded border border-cyan-300/10 bg-[#020a12] p-2 font-mono text-[10.5px] leading-relaxed text-cyan-100/80">
                {p.body_preview}
              </pre>
            ) : null}
          </div>
        ))}
        {proposals.length === 0 ? (
          <p className="p-4 font-mono text-[11px] text-cyan-200/40">
            Queue is clear. Agent proposals land here before touching the vault.
          </p>
        ) : null}
      </div>
    </div>
  );
}
