/** Review queue: staged agent proposals -> approve / reject. */

import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight, Link2, RefreshCw, X } from "lucide-react";
import { ArticleMarkdown } from "@/components/themes/obsidience/workspace/article-markdown";
import { api, openReader, type Proposal } from "@/lib/api";

function cleanLeaf(value: string): string {
  const leaf = value.replace(/\.md$/i, "").split("/").pop() ?? value;
  return leaf.replaceAll("-", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function ReviewsPaneBody() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [deciding, setDeciding] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.reviews();
      setProposals(next);
      setLoadError(null);
    } catch (e) {
      setLoadError(`Review service unavailable: ${String(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2_000);
    return () => clearInterval(t);
  }, [refresh]);

  async function decide(name: string, ok: boolean) {
    setActionError(null);
    setDeciding(name);
    try {
      if (ok) await api.approve(name);
      else await api.reject(name, "rejected from review pane");
      await refresh();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setDeciding(null);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-cyan-300/10 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-cyan-300/50">
        <span>{loading ? "Loading review queue" : `${proposals.length} awaiting review`}</span>
        <button
          type="button"
          onClick={() => {
            setActionError(null);
            void refresh();
          }}
          disabled={loading}
          title="Refresh review queue"
          aria-label="Refresh review queue"
          className="rounded p-1 text-cyan-300/60 hover:bg-cyan-300/10 hover:text-cyan-100 disabled:opacity-30"
        >
          <RefreshCw size={12} />
        </button>
      </div>
      {loadError || actionError ? (
        <div className="border-b border-rose-300/15 px-3 py-2 font-mono text-[10px] text-rose-300" role="alert">
          <p>{actionError ?? loadError}</p>
          {loadError ? (
            <button type="button" onClick={() => void refresh()} className="mt-1 text-cyan-200 hover:text-cyan-50">
              Retry
            </button>
          ) : null}
        </div>
      ) : null}
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
        {proposals.map((p) => {
          const isLink = p.review_class === "link";
          return (
          <article key={p.file} className={`overflow-hidden rounded-lg border bg-[#020a12]/78 ${
            isLink
              ? "border-violet-300/20 shadow-[inset_2px_0_rgba(196,181,253,0.22)]"
              : "border-cyan-300/12 shadow-[inset_2px_0_rgba(34,211,238,0.1)]"
          }`}>
            <div className="flex items-start gap-2 px-3 py-3">
              <button type="button" onClick={() => setExpanded(expanded === p.file ? null : p.file)}
                aria-expanded={expanded === p.file}
                className="mt-0.5 text-cyan-300/55 hover:text-cyan-100">
                {expanded === p.file ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
              <button type="button" onClick={() => setExpanded(expanded === p.file ? null : p.file)}
                className="min-w-0 flex-1 text-left">
                <span className={`flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.18em] ${
                  isLink ? "text-violet-200/80" : "text-amber-200/65"
                }`}>
                  {isLink ? <Link2 size={10} aria-hidden="true" /> : null}
                  {isLink ? "Link proposal" : `${p.action} article proposal`}
                </span>
                <span className="mt-1 block font-mono text-[14px] font-semibold leading-5 text-cyan-50">
                  {p.title || cleanLeaf(p.target)}
                </span>
                {p.reason ? <span className="mt-1.5 block text-[11px] leading-4 text-cyan-100/58">{p.reason}</span> : null}
                {isLink && p.link_changes ? (
                  <span className="mt-2 block rounded border border-violet-300/15 bg-violet-300/[0.045] px-2 py-1.5 font-mono text-[9px] leading-4">
                    <span className="block uppercase tracking-[0.16em] text-violet-200/55">Relationship change</span>
                    {p.evidence_warning ? (
                      <span className="block text-amber-200/80">{p.evidence_warning}</span>
                    ) : null}
                    {p.link_changes.added.map((ref) => (
                      <span key={`add-${ref}`} className="mt-0.5 block text-emerald-200/75" title={ref}>
                        + {cleanLeaf(ref)}
                      </span>
                    ))}
                    {p.link_changes.removed.map((ref) => (
                      <span key={`remove-${ref}`} className="mt-0.5 block text-rose-200/70" title={ref}>
                        − {cleanLeaf(ref)}
                      </span>
                    ))}
                  </span>
                ) : null}
                {p.blocked_reason ? (
                  <span className="mt-2 block rounded border border-amber-300/20 bg-amber-300/[0.05] px-2 py-1.5 font-mono text-[9px] leading-4 text-amber-200/75">
                    {p.blocked_reason}
                  </span>
                ) : null}
                <span className="mt-2 flex flex-wrap gap-1.5 font-mono text-[8px] text-cyan-200/40">
                  <span className="rounded border border-cyan-300/10 bg-cyan-300/[0.04] px-1.5 py-0.5">{cleanLeaf(p.target)}</span>
                  <span className="rounded border border-violet-300/10 bg-violet-300/[0.04] px-1.5 py-0.5">{p.agent}</span>
                  {p.task ? <span className="rounded border border-emerald-300/10 bg-emerald-300/[0.04] px-1.5 py-0.5">{cleanLeaf(p.task)}</span> : null}
                </span>
              </button>
              <div className="flex shrink-0 gap-1">
                <button type="button" onClick={() => void decide(p.file, true)} title={p.blocked_reason || "Approve proposal"}
                  aria-label={`Approve ${p.title}`}
                  disabled={deciding !== null || !p.approvable}
                  className="flex h-7 w-7 items-center justify-center rounded border border-emerald-300/35 text-emerald-300 hover:bg-emerald-300/10 disabled:opacity-30">
                  <Check size={13} />
                </button>
                <button type="button" onClick={() => void decide(p.file, false)} title="Reject proposal"
                  aria-label={`Reject ${p.title}`}
                  disabled={deciding !== null}
                  className="flex h-7 w-7 items-center justify-center rounded border border-rose-300/35 text-rose-300 hover:bg-rose-300/10 disabled:opacity-30">
                  <X size={13} />
                </button>
              </div>
            </div>
            {expanded === p.file ? (
              <section className={`border-t bg-[#01070d]/72 px-4 py-4 ${
                isLink ? "border-violet-300/12" : "border-cyan-300/10"
              }`}>
                {(p.link_evidence ?? []).map((e) => (
                  <p key={`${e.change}-${e.ref}`} className="mb-3 whitespace-pre-wrap font-mono text-[10px] leading-4 text-cyan-100/65">
                    {e.derivation === "proposed_wikilink" ? "Proposed link" : "Removed accepted link"}
                    {` · body line ${e.body_line}\n${e.excerpt}`}
                  </p>
                ))}
                <p className={`mb-3 font-mono text-[9px] uppercase tracking-[0.2em] ${
                  isLink ? "text-violet-200/50" : "text-cyan-300/45"
                }`}>{isLink ? "Article after link" : "Proposed article"}</p>
                <div className="max-h-[28rem] overflow-y-auto pr-2">
                  <ArticleMarkdown content={p.body_preview} variant="reader" onNavigate={openReader} />
                </div>
              </section>
            ) : null}
          </article>
          );
        })}
        {!loading && !loadError && proposals.length === 0 ? (
          <div className="rounded-lg border border-cyan-300/10 bg-[#020a12]/55 px-5 py-6 text-center">
            <p className="font-mono text-[13px] text-cyan-100/65">Queue is clear</p>
            <p className="mx-auto mt-2 max-w-sm text-[11px] leading-5 text-cyan-200/35">
              Agent proposals will appear here as readable notes, ready for owner approval or rejection.
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
