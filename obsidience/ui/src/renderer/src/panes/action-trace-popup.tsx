import { useEffect, useRef, useState } from "react";
import { WS_BASE } from "@/lib/api";
import {
  applyTraceFrame, fieldLabel, traceActionTarget, traceActionTitle, traceChannelLabel, traceEntriesSince, traceRowFinding, traceRowState, traceRuns, traceSimulationLabel, traceText,
  LATENCY_STAGES, TRACE_ENTRY_LIMIT, type ActionTraceEntry, type TraceModelRequest, type TraceRow, type TraceRun, type TraceValue,
} from "./action-trace";

const CHANNEL_COLOR: Record<string, string> = {
  run: "text-sky-200", activation: "text-violet-200", tool: "text-amber-200",
  result: "text-teal-200", status: "text-violet-200", error: "text-rose-300",
  context: "text-sky-200", model: "text-cyan-200",
};
const ROW_GRID = "grid grid-cols-[1.5rem_minmax(0,1fr)_4.75rem_3.75rem] items-baseline gap-2";
const DISCLOSURE = "[&[open]>summary_.trace-chevron]:rotate-90";

function duration(ms: number): string {
  if (ms < 1_000) return `${Number(ms.toFixed(1))} ms`;
  if (ms < 60_000) return `${(ms / 1_000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round(ms % 60_000 / 1_000)}s`;
}

function responseMetrics(request: TraceModelRequest): Record<string, TraceValue> {
  const reported = request.entries.findLast(entry => entry.payload.metrics)?.payload.metrics;
  const metrics = reported && typeof reported === "object" && !Array.isArray(reported) ? { ...reported } : {};
  const waiting = request.entries.find(entry => entry.payload.phase === "waiting");
  const started = request.entries.find(entry => entry.payload.phase === "started");
  if (waiting && started && started.at >= waiting.at) metrics.resource_wait_ms = started.at - waiting.at;
  return metrics;
}

function ResponseMeasurements({ request }: { request: TraceModelRequest }) {
  const latest = request.entries.at(-1)!;
  const metrics = responseMetrics(request);
  return <div className="space-y-2">
    <p className="text-[11px] text-slate-400">{traceText(latest.payload.model_label) || traceText(latest.payload.model) || "Recorded provider measurements"}</p>
    {Object.keys(metrics).length ? <TraceFields value={metrics} label="Response measurements" />
      : <p className="text-slate-500">No completed timing measurements were reported.</p>}
    {latest.payload.error ? <TraceFields value={latest.payload.error} label="Response error" /> : null}
    {!latest.payload.kind && latest.detail ? <TraceFields value={latest.detail} label="Recorded model details" /> : null}
    {request.entries.some(entry => entry.truncated) ? <p className="text-amber-200">These measurements are shortened in the live trace.</p> : null}
  </div>;
}

function ResponseSummary({ request }: { request: TraceModelRequest }) {
  const metrics = responseMetrics(request);
  const parts = [["first_public_delta_ms", "First text"], ["generation_ms", "Generation"], ["resource_wait_ms", "Resource wait"]]
    .flatMap(([key, label]) => typeof metrics[key] === "number" ? [`${label} ${duration(metrics[key])}`] : []);
  return parts.length ? <span className="mt-1 block text-[10px] leading-4 text-cyan-200/70">{parts.join(" · ")}</span> : null;
}

/** Requests without a resulting action belong to Task status, not its step count. */
function ResponseStatus({ run }: { run: TraceRun }) {
  if (!run.modelRequests.length) return null;
  const latestRequest = run.modelRequests.at(-1)!;
  const latest = latestRequest.entries.at(-1)!;
  const active = ["waiting", "started", "result"].includes(traceText(latest.payload.phase))
    && !["completed", "failed", "cancelled", "blocked", "error"].includes(run.status)
    && run.entries.filter(entry => !entry.latency).at(-1)?.id === latest.id;
  const diagnostics = active ? run.modelRequests.slice(0, -1) : run.modelRequests;
  const problems = diagnostics.filter(request => ["error", "interrupted"].includes(traceText(request.entries.at(-1)?.payload.phase))).length;
  return <div className="space-y-2 border-t border-slate-700/30 px-4 py-3 text-[11px]">
    {active ? <p role="status" data-trace-event={latest.id} className="text-cyan-200">{traceActionTitle(latest)}…</p> : null}
    {diagnostics.length ? <details data-trace-event={diagnostics.at(-1)?.entries.at(-1)?.id} className={DISCLOSURE}>
      <summary className={`cursor-pointer list-none rounded ${problems ? "text-rose-200" : "text-slate-400"} focus-visible:outline focus-visible:outline-cyan-300`}>
        <span className="trace-chevron mr-1 inline-block">›</span>Response diagnostics{problems ? ` · ${problems} failed or interrupted` : ""} · {diagnostics.length} {diagnostics.length === 1 ? "request" : "requests"} without a corresponding action in this trace
      </summary>
      <div className="mt-2 space-y-3">
        {diagnostics.map(request => {
          const event = request.entries.at(-1)!;
          return <div key={request.id} className="rounded border border-slate-700/40 p-3">
            <p className={`mb-2 ${["error", "interrupted"].includes(traceText(event.payload.phase)) ? "text-rose-200" : "text-slate-300"}`}>{traceActionTitle(event)}</p>
            <ResponseMeasurements request={request} />
          </div>;
        })}
      </div>
    </details> : null}
  </div>;
}

function LatencyTimeline({ run, entries = run.latencyEntries, label = "Latency timeline" }:
  { run: TraceRun; entries?: ActionTraceEntry[]; label?: string }) {
  if (!entries.length) return null;
  const latest = entries.at(-1)!;
  const unbound = run.id.startsWith("latency:");
  const first = entries[0].latency!;
  const origin = !unbound || first.turnId ? first.monotonicMs : undefined;
  return <details data-trace-event={latest.id} className={`${DISCLOSURE} border-t border-slate-700/30 px-4 py-3 text-[11px]`}>
    <summary className="cursor-pointer list-none rounded text-cyan-200 focus-visible:outline focus-visible:outline-cyan-300">
      <span className="trace-chevron mr-1 inline-block">›</span>{label} · {entries.length} measurements
    </summary>
    <p className="mb-2 mt-3 text-slate-400">Elapsed from first recorded stage; durations may overlap. Only measurements present in the retained trace are shown.</p>
    {unbound ? <p className="mb-2 text-slate-400">These measurements have no unique Task binding in the retained trace.</p> : null}
    <table aria-label={label} className="w-full border-collapse text-left">
      <thead className="text-[10px] text-slate-500"><tr><th className="py-2 font-normal">Stage</th><th className="py-2 text-right font-normal">Measured phase</th><th className="py-2 pl-3 text-right font-normal">Elapsed</th></tr></thead>
      <tbody>{entries.map(entry => {
        const timing = entry.latency!;
        const identity = [timing.speechSequence === undefined ? "" : `Speech segment ${timing.speechSequence}`,
          timing.generation === undefined ? "" : `Generation ${timing.generation}`].filter(Boolean).join(" · ");
        return <tr key={entry.id} data-latency-stage={timing.stage} className="border-t border-slate-700/35">
          <td className="py-2 pr-3 text-slate-200">{LATENCY_STAGES[timing.stage]}
            {identity ? <span className="block text-[10px] text-slate-500">{identity}</span> : null}
          </td>
          <td className="py-2 text-right font-mono text-cyan-100">{timing.durationMs === undefined
            ? <span className="font-sans text-slate-500">Not reported</span> : duration(timing.durationMs)}</td>
          <td className="py-2 pl-3 text-right font-mono text-slate-300">{origin === undefined
            ? <span className="font-sans text-slate-500">Not reported</span> : duration(timing.monotonicMs - origin)}</td>
        </tr>;
      })}</tbody>
    </table>
  </details>;
}

function SimulationTimelines({ run }: { run: TraceRun }) {
  const trials = new Map<string, ActionTraceEntry[]>();
  for (const entry of run.entries) {
    if (!entry.latency || (!entry.trial && entry.payload.simulated !== true)) continue;
    const id = entry.trial?.id ?? entry.id;
    const entries = trials.get(id) ?? [];
    entries.push(entry);
    trials.set(id, entries);
  }
  return <>{[...trials].map(([id, entries]) => <LatencyTimeline key={id} run={run}
    entries={entries.sort((a, b) => a.latency!.monotonicMs - b.latency!.monotonicMs)}
    label={`${traceSimulationLabel(entries[0])} · Latency timeline`} />)}</>;
}

/** Native disclosures preserve expansion and keyboard focus as rows stream in. */
function TraceFields({ value, label = "Details" }: { value: TraceValue; label?: string }) {
  if (value === null) return <span className="text-slate-500">Not supplied</span>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (typeof value !== "object") {
    return <span className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{String(value) || "Empty"}</span>;
  }
  const items = Object.entries(value);
  if (!items.length) return <span className="text-slate-500">{Array.isArray(value) ? "No items" : "No fields"}</span>;
  return (
    <dl aria-label={label} className="divide-y divide-slate-700/35">
      {items.map(([key, item]) => {
        const name = Array.isArray(value) ? `Item ${Number(key) + 1}` : fieldLabel(key);
        const nested = item !== null && typeof item === "object";
        return <div key={key} className="grid grid-cols-[minmax(5rem,28%)_minmax(0,1fr)] gap-3 py-2">
          <dt className="break-words text-slate-400">{name}</dt>
          <dd className="min-w-0 text-slate-200">
            {nested ? <details className={DISCLOSURE}>
              <summary className="cursor-pointer list-none rounded text-cyan-200 focus-visible:outline focus-visible:outline-cyan-300">
                <span className="trace-chevron mr-1 inline-block">›</span>{Object.keys(item).length} {Array.isArray(item) ? "items" : "fields"}
              </summary>
              <TraceFields value={item} label={name} />
            </details> : <TraceFields value={item} />}
          </dd>
        </div>;
      })}
    </dl>
  );
}

function KnowledgeAccounting({ value }: { value: TraceValue | undefined }) {
  if (!value || typeof value !== "object" || Array.isArray(value) || value.version !== 1) return null;
  const entries = Array.isArray(value.entries) ? value.entries.filter((item): item is Record<string, TraceValue> =>
    Boolean(item && typeof item === "object" && !Array.isArray(item) && typeof item.ref === "string")) : [];
  const count = (key: string) => typeof value[key] === "number" ? value[key].toLocaleString() : "Not reported";
  const reasons: Record<string, string> = {
    selected: "Supplied to the agent", article_limit: "Outside the Article allowance",
    graph_limit: "Outside the linked-Article allowance", token_budget: "Did not fit the Knowledge budget",
    after_budget_stop: "Not supplied after packing reached its budget limit",
  };
  return <div aria-label="Knowledge selection" className="mb-4 rounded border border-cyan-300/15 bg-cyan-300/[0.025] p-3 text-[11px]">
    <p className="font-medium text-cyan-100">What Knowledge reached the agent</p>
    <p className="mt-1 text-slate-300">{count("considered_count")} considered · {count("included_count")} supplied · {count("omitted_count")} omitted</p>
    <p className="mt-1 text-slate-400">Estimated Knowledge tokens: {count("estimated_used_tokens")} of {count("estimated_budget_tokens")}. The complete model request is counted separately.</p>
    <p className="mt-1 text-slate-500">Covers eligible search candidates and examined links, not every Article in the Vault.</p>
    {value.status === "no_matches" ? <p className="mt-2 text-slate-300">No eligible Knowledge matched this search.</p> : null}
    {value.status === "empty_query" ? <p className="mt-2 text-slate-300">Knowledge search had no query.</p> : null}
    {value.status === "disabled" ? <p className="mt-2 text-slate-300">No Knowledge Articles were requested.</p> : null}
    <div className="mt-3 space-y-1">
      {entries.map(item => {
        const included = item.decision === "included";
        const label = item.decision === "omitted" ? "Omitted" : !included ? "Decision not reported"
          : item.content === "full" ? "Full Article" : item.content === "excerpt" ? "Excerpt"
          : item.content === "none" ? "No body supplied" : "Body details not reported";
        const origin = item.origin === "graph" ? "Linked from" : item.origin === "direct" ? "Direct search match" : "Search origin not reported";
        return <details key={traceText(item.ref)} className={`${DISCLOSURE} border-t border-slate-700/35 pt-1`}>
          <summary className="flex cursor-pointer list-none items-baseline gap-2 rounded py-2 focus-visible:outline focus-visible:outline-cyan-300">
            <span className="trace-chevron text-cyan-200">›</span>
            <span className="min-w-0 flex-1 break-words text-slate-200">{traceText(item.title) || traceText(item.ref)}</span>
            <span className={`shrink-0 ${included ? "text-teal-200" : "text-amber-200"}`}>{label}</span>
          </summary>
          <div className="space-y-1 pb-3 pl-4 text-slate-400 [overflow-wrap:anywhere]">
            <p>{traceText(item.ref)}</p>
            <p>{origin}{item.origin === "graph" ? ` ${traceText(item.seed_ref) || "an unreported Article"}` : ""}{item.preferred === true ? " · Preferred Source tree" : ""}</p>
            <p>{reasons[traceText(item.reason)] || "Selection reason not reported"}</p>
            {included && typeof item.body_start === "number" && typeof item.body_end === "number" ?
              <p>{item.body_end > item.body_start ? `Body characters ${item.body_start + 1}–${item.body_end}` : "No body characters"} supplied{typeof item.body_chars === "number" ? ` of ${item.body_chars.toLocaleString()}` : ""}.</p> : null}
            {typeof item.omitted_chars === "number" && item.omitted_chars > 0 ? <p>{item.omitted_chars.toLocaleString()} body characters were not supplied.</p> : null}
            {typeof item.included_estimated_tokens === "number" ? <p>Estimated supplied tokens: {item.included_estimated_tokens.toLocaleString()}.</p> : null}
          </div>
        </details>;
      })}
    </div>
    {typeof value.entries_omitted === "number" && value.entries_omitted > 0 ? <p className="mt-2 text-amber-200">{value.entries_omitted} additional candidate details are outside this display limit; the totals include them.</p> : null}
    {value.truncated === true ? <p className="mt-2 text-amber-200">Candidate details were shortened for this trace. Missing decisions and origins are not inferred.</p> : null}
  </div>;
}

function Packet({ entry }: { entry: ActionTraceEntry }) {
  const sections = Array.isArray(entry.payload.sections) ? entry.payload.sections.filter(section =>
    section && typeof section === "object" && !Array.isArray(section) && section.key !== "header") : [];
  return <div>
    <p className="mb-3 text-slate-400">The instructions and context assembled for this task, in the order supplied to the agent.</p>
    <ol className="space-y-1">
      {sections.map((section, index) => {
        if (!section || typeof section !== "object" || Array.isArray(section)) return null;
        const title = traceText(section.title) || fieldLabel(traceText(section.key));
        const explanations: Record<string, string> = {
          "Agent Identity": "Who is responsible", "Task": "The outcome and acceptance conditions",
          "Objective": "The exact request for this run", "Tools": "Actions the agent may use",
          "Skills": "How to use those actions", "Runbook": "The procedure to follow",
          "Bindings": "Current facts and constraints", "Relevant Knowledge": "Relevant accepted articles",
          "Immediate Observations": "Conversation and recent observations",
        };
        let content: TraceValue = traceText(section.text).replace(/^## [^\n]+\n/, "");
        if (section.key === "bindings") {
          try { content = JSON.parse(content); } catch { /* clipped bindings remain visible text */ }
        }
        return <li key={traceText(section.key) || title}>
          <details className={`${DISCLOSURE} rounded border border-violet-300/10 bg-violet-300/[0.025]`}>
            <summary className="flex cursor-pointer list-none items-center gap-2 rounded px-3 py-2.5 focus-visible:outline focus-visible:outline-cyan-300">
              <span className="trace-chevron inline-block text-violet-300">›</span>
              <span className="font-mono text-[10px] text-slate-500">{String(index + 1).padStart(2, "0")}</span>
              <span className="min-w-0 flex-1"><span className="text-violet-100">{title}</span>
                {explanations[title] ? <span className="ml-2 text-[11px] text-slate-500">{explanations[title]}</span> : null}</span>
              <span className="shrink-0 font-mono text-[10px] text-slate-500">{typeof section.chars === "number" ? section.chars.toLocaleString() : ""} chars</span>
            </summary>
            <div className="border-t border-violet-300/10 px-4 py-3 text-slate-200">
              {section.key === "knowledge" ? <KnowledgeAccounting value={entry.payload.knowledge_accounting} /> : null}
              <TraceFields value={content || "No content supplied"} />
              {section.truncated === true ? <p className="mt-2 text-amber-200">This section is shortened in the live trace.</p> : null}
            </div>
          </details>
        </li>;
      })}
    </ol>
    {typeof entry.payload.retrieval_ms === "number" ? <p className="mt-3 text-[11px] text-slate-500">Knowledge retrieved in {duration(entry.payload.retrieval_ms)}.</p> : null}
  </div>;
}

function EventDetails({ row }: { row: TraceRow }) {
  const entry = row.entry;
  const result = row.result;
  const payload = entry.payload;
  if (payload.kind === "packet") return <Packet entry={entry} />;
  if (payload.kind === "tool") return <div className="space-y-4">
    <p className="text-[11px] text-slate-500">Tool <code className="text-slate-300">{traceText(payload.name)}</code>{entry.step !== undefined ? ` · Agent step ${entry.step}` : ""}</p>
    {payload.arguments !== undefined ? <div><p className="mb-1 font-medium text-amber-100">What was requested</p><TraceFields value={payload.arguments} label="Action inputs" /></div> : null}
    {result || payload.phase === "result" ? <div>
      <p className="mb-1 font-medium text-teal-100">What came back</p>
      <TraceFields value={(result ?? entry).payload.result ?? (result ?? entry).detail} label="Returned information" />
      {result?.truncated ? <p className="mt-2 text-amber-200">The returned content is shortened in the live trace.</p> : null}
    </div> : <p className="text-slate-400">Waiting for a result. A requested action does not establish that it succeeded.</p>}
  </div>;
  if (payload.kind === "context") return <TraceFields value={payload.projection ?? {}} label="Working context" />;
  if (payload.kind === "run") {
    const { kind: _kind, ...fields } = payload;
    return <TraceFields value={fields} label="Task outcome" />;
  }
  // Compatibility entries stay readable without guessing correlation or success.
  let legacy: TraceValue = entry.detail || entry.line;
  try { legacy = JSON.parse(entry.detail); } catch { /* ordinary public text */ }
  return <TraceFields value={legacy} />;
}

function ActionRow({ row, index, startedAt }: { row: TraceRow; index: number; startedAt: number }) {
  const entry = row.entry;
  const state = traceRowState(row);
  const finding = traceRowFinding(row);
  const timing = (row.result ?? entry).payload.duration_ms;
  // Model response precedes Tool dispatch/result when their millisecond stamps tie.
  const latest = [...(row.model?.entries ?? []), entry, ...(row.result ? [row.result] : [])].sort((a, b) => a.at - b.at).at(-1)!;
  return <details data-trace-event={latest.id} className={`${DISCLOSURE} border-b border-slate-700/40 last:border-0`}>
    <summary className={`${ROW_GRID} cursor-pointer list-none rounded px-3 py-3 hover:bg-cyan-100/[0.04] focus-visible:outline focus-visible:outline-cyan-300`}>
      <span className="flex items-center gap-1 font-mono text-[10px] text-slate-500"><span className="trace-chevron inline-block">›</span>{String(index + 1).padStart(2, "0")}</span>
      <span className="min-w-0">
        <span className={`mb-0.5 block text-[9px] font-medium uppercase tracking-[0.12em] ${CHANNEL_COLOR[entry.channel]}`}>{traceChannelLabel(entry.channel)}</span>
        <span className="block break-words text-[12px] leading-5 text-slate-100">{traceActionTitle(entry)}</span>
        {entry.payload.kind === "tool" ? <span className="block truncate text-[11px] text-slate-400" title={traceText(entry.payload.name)}>{traceActionTarget(entry) || traceText(entry.payload.name)}</span> : null}
        {finding ? <span className="mt-1 block text-[11px] text-slate-300">{finding}</span> : null}
        {row.model ? <ResponseSummary request={row.model} /> : null}
      </span>
      <span className={`text-[10px] ${["Problem", "Error", "Rejected", "Failed", "Blocked"].includes(state) ? "text-rose-300" : ["Waiting", "Degraded"].includes(state) ? "text-amber-200" : "text-teal-200/85"}`}>{state}</span>
      <span className="text-right font-mono text-[10px] text-slate-500" title={typeof timing === "number" ? "Action duration" : "Time since task started"}>
        {typeof timing === "number" ? duration(timing) : `+${duration(Math.max(0, entry.at - startedAt))}`}
      </span>
    </summary>
    <div className="mx-3 mb-3 rounded border border-slate-700/50 bg-black/20 px-3 py-3 text-[12px] leading-5">
      <EventDetails row={row} />
      {row.model ? <details className={`${DISCLOSURE} mt-4 border-t border-slate-700/40 pt-3`}>
        <summary className="cursor-pointer list-none rounded text-cyan-200 focus-visible:outline focus-visible:outline-cyan-300"><span className="trace-chevron mr-1 inline-block">›</span>Response measurements</summary>
        <div className="mt-2"><ResponseMeasurements request={row.model} /></div>
      </details> : null}
      {entry.truncated ? <p className="mt-3 text-[11px] text-amber-200">This event is shortened for the bounded live view.</p> : null}
    </div>
  </details>;
}

/** One disposable subscription; all Task state and correlation come from Harness. */
export function ActionTracePopup({ since, keptOpen = false, onKeepOpen, onClose }: {
  since: number; keptOpen?: boolean; onKeepOpen?: (value: boolean) => void; onClose?: () => void;
}) {
  const [entries, setEntries] = useState<ActionTraceEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [replayNotice, setReplayNotice] = useState("");
  const [followLatest, setFollowLatest] = useState(true);
  const scrollArea = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let cursor: number | null = null;
    setEntries([]);
    setConnected(false);
    setFollowLatest(true);
    setReplayNotice("");
    const connect = () => {
      if (stopped) return;
      const next = new WebSocket(`${WS_BASE}/ws/trace${cursor === null ? "" : `?after=${cursor}`}`);
      socket = next;
      next.onopen = () => { if (!stopped) setConnected(true); };
      next.onmessage = event => {
        if (stopped || typeof event.data !== "string" || event.data.length > 4_000_000) return;
        try {
          const frame = JSON.parse(event.data);
          if (Number.isSafeInteger(frame.cursor) && frame.cursor >= 0) cursor = frame.cursor;
          if (frame.journal_available === false) setReplayNotice("Trace storage is unavailable; live entries may be incomplete after reconnecting.");
          else if (frame.gap === true) setReplayNotice("Earlier entries are outside retained history. Showing the available trace.");
        } catch { return; }
        setEntries(current => applyTraceFrame(current, event.data, since));
      };
      next.onclose = () => {
        if (stopped) return;
        setConnected(false);
        retry = setTimeout(connect, 1_000);
      };
      next.onerror = () => { if (!stopped) setConnected(false); };
    };
    connect();
    return () => {
      stopped = true;
      if (retry !== null) clearTimeout(retry);
      socket?.close();
    };
  }, [since]);

  useEffect(() => {
    if (!followLatest || !scrollArea.current) return;
    const latestId = entries.at(-1)?.id;
    const target = Array.from(scrollArea.current.querySelectorAll<HTMLElement>("[data-trace-event]"))
      .find(element => element.dataset.traceEvent === latestId);
    target?.scrollIntoView({ block: "nearest" });
  }, [entries, followLatest]);

  const current = traceEntriesSince(entries, since);
  const runs = traceRuns(current);
  const latest = current.at(-1);
  const latestRun = runs.find(run => run.entries.some(entry => entry.id === latest?.id));
  return (
    <section aria-label="Live Action Trace"
      onPointerDown={event => { event.stopPropagation(); onKeepOpen?.(true); }}
      onWheel={event => { event.stopPropagation(); setFollowLatest(false); onKeepOpen?.(true); }}
      onClickCapture={event => { if ((event.target as HTMLElement).closest("summary")) setFollowLatest(false); }}
      onFocusCapture={event => { if ((event.target as HTMLElement).tagName === "SUMMARY") onKeepOpen?.(true); }}
      onKeyDown={event => { event.stopPropagation(); if (event.key === "Escape") onClose?.(); }}
      className="pointer-events-auto absolute left-4 top-16 z-40 flex max-h-[min(80vh,calc(100%_-_5rem))] w-[min(48rem,calc(100%_-_2rem))] flex-col overflow-hidden rounded-xl border border-cyan-200/20 bg-[#07111b]/95 font-sans text-slate-200 shadow-[0_16px_60px_#0009] backdrop-blur-xl">
      <div className="shrink-0 border-b border-cyan-200/10 bg-gradient-to-r from-cyan-300/[0.07] to-violet-300/[0.05] px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="text-sm font-semibold tracking-wide text-cyan-50">Action Trace</span>
            <span role="status" className={`rounded-full border px-2 py-0.5 text-[9px] tracking-wider ${connected ? "border-teal-200/20 text-teal-200" : "border-amber-200/20 text-amber-200"}`}>
              {connected ? "LIVE" : "RECONNECTING"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" aria-pressed={followLatest} onClick={() => setFollowLatest(!followLatest)}
              className="rounded px-1 py-1 text-[10px] text-cyan-200 hover:text-cyan-50 focus-visible:outline focus-visible:outline-cyan-300">
              {followLatest ? "Following live" : "Follow latest"}
            </button>
            <button type="button" aria-pressed={keptOpen} onPointerDown={event => event.stopPropagation()}
              onClick={() => onKeepOpen?.(!keptOpen)} className="rounded border border-slate-500/40 px-2 py-1 text-[10px] text-slate-300 hover:border-cyan-200/60 focus-visible:outline focus-visible:outline-cyan-300">
              {keptOpen ? "Kept open" : "Keep open"}
            </button>
            <button type="button" aria-label="Close action trace" onClick={onClose}
              className="rounded px-2 py-0.5 text-lg leading-5 text-slate-400 hover:text-white focus-visible:outline focus-visible:outline-cyan-300">×</button>
          </div>
        </div>
        <p className="mt-1.5 text-[11px] leading-4 text-slate-400">Follow the task from instructions to actions to outcome. Expand any row to see the evidence.</p>
        {replayNotice && <p role="status" className="mt-1 text-[11px] text-amber-200">{replayNotice}</p>}
      </div>
      <div ref={scrollArea} className="min-h-0 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]" aria-label="Task steps">
        {runs.length ? runs.map(run => <details key={run.id} open className={`${DISCLOSURE} border-b border-cyan-200/15 last:border-0`}>
          <summary className="flex cursor-pointer list-none items-center gap-2 bg-cyan-100/[0.025] px-4 py-3 focus-visible:outline focus-visible:outline-cyan-300">
            <span className="trace-chevron inline-block text-cyan-200">›</span>
            <span className="min-w-0 flex-1"><span className="block break-words text-[13px] font-semibold text-cyan-50">{run.title}</span>
              <span className="mt-0.5 block text-[10px] text-slate-500">{run.agent ? `${run.agent} · ` : ""}{run.rows.length} steps shown</span></span>
            {run.status ? <span className={`shrink-0 rounded-md border px-2 py-1 text-[10px] ${["failed", "error", "blocked"].includes(run.status) ? "border-rose-300/20 text-rose-200" : "border-cyan-300/15 text-cyan-100"}`}>{fieldLabel(run.status)}</span> : null}
          </summary>
          {run.objective ? <p className="line-clamp-2 border-t border-slate-700/30 px-4 py-2 text-[12px] leading-5 text-slate-300">{run.objective}</p> : null}
          {run.rows.length ? <div className={`${ROW_GRID} border-y border-slate-700/40 px-3 py-1.5 text-[9px] uppercase tracking-widest text-slate-500`} aria-hidden="true">
            <span>#</span><span>Step / evidence</span><span>State</span><span className="text-right">Time</span>
          </div> : null}
          {run.rows.map((row, index) => <ActionRow key={row.id} row={row} index={index} startedAt={run.at} />)}
          <ResponseStatus run={run} />
          <LatencyTimeline run={run} />
          <SimulationTimelines run={run} />
        </details>) : <p className="px-4 py-6 text-[12px] text-slate-400">Waiting for the first task event…</p>}
      </div>
      <div className="flex shrink-0 items-center justify-between gap-3 border-t border-cyan-200/10 px-4 py-2 text-[10px] text-slate-500">
        <span className="min-w-0 truncate" aria-live="polite" aria-atomic="true">{latest ? `${latestRun?.agent || "System"} · ${traceActionTitle(latest)}` : "Connecting to task activity"}</span>
        <span className="shrink-0">{current.length >= TRACE_ENTRY_LIMIT ? `Latest ${TRACE_ENTRY_LIMIT} events` : `${current.length} events`} · {keptOpen ? "Stays open while you read" : "Select a row to keep open"}</span>
      </div>
    </section>
  );
}
