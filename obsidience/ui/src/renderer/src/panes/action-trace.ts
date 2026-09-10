/** Disposable presentation of the Harness's single public Action Trace. */
export type TraceValue = null | boolean | number | string | TraceValue[] | { [key: string]: TraceValue };
export interface TracePacketSection {
  key: string; title: string; text: string; chars: number; sha256: string; truncated: boolean;
}
export const LATENCY_STAGES = {
  input_final: "Input accepted", preparation: "Conversation preparation", selection: "Task selection",
  activation: "Task activation", model_wait: "Model availability", model_preflight: "Model request preparation",
  model_first_public: "First model text", model_complete: "Model response complete", answer_committed: "Answer saved",
  speech_received: "Speech request received", aec_ready: "Echo cancellation ready", first_pcm: "First audio generated",
  first_output_write: "First audio output write", speech_onset: "Speech detected", first_partial: "First recognized words",
  speech_final: "Speech recognition complete",
} as const;
export interface TraceLatency {
  stage: keyof typeof LATENCY_STAGES;
  monotonicMs: number;
  durationMs?: number;
  turnId?: string;
  speechSequence?: number;
  generation?: number;
}
export interface ActionTraceEntry {
  id: string;
  sequence?: number;
  at: number;
  channel: string;
  line: string;
  detail: string;
  runId?: string;
  taskRef?: string;
  agentRef?: string;
  callId?: string;
  step?: number;
  truncated: boolean;
  payload: Record<string, TraceValue>;
  latency?: TraceLatency;
  trial?: TraceTrial;
}

export interface TraceTrial {
  id: string;
  case_id: string;
  split: "train" | "holdout";
  variant: "baseline" | "candidate";
  repetition: number;
}

export interface TraceModelRequest {
  id: string;
  entries: ActionTraceEntry[];
}
export interface TraceRow {
  id: string;
  entry: ActionTraceEntry;
  result?: ActionTraceEntry;
  model?: TraceModelRequest;
}
export interface TraceRun {
  id: string;
  title: string;
  agent: string;
  at: number;
  status: string;
  summary: string;
  objective: string;
  entries: ActionTraceEntry[];
  rows: TraceRow[];
  modelRequests: TraceModelRequest[];
  latencyEntries: ActionTraceEntry[];
}

export const TRACE_ENTRY_LIMIT = 160;
const TRACE_FRAME_LIMIT = 4_000_000;
const CHANNELS = new Set(["run", "activation", "tool", "result", "status", "error", "context", "model", "latency", "measurement"]);

function exactId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 160
    && !/[\u0000-\u001f\u007f]/.test(value);
}

function trialFromWire(value: unknown): TraceTrial | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const trial = value as Record<string, unknown>;
  if (Object.keys(trial).sort().join(",") !== "case_id,id,repetition,split,variant"
      || typeof trial.id !== "string" || !/^[A-Za-z0-9_.:-]{1,160}$/.test(trial.id)
      || typeof trial.case_id !== "string" || !/^[A-Za-z0-9_.-]{1,64}$/.test(trial.case_id)
      || typeof trial.split !== "string" || !["train", "holdout"].includes(trial.split)
      || typeof trial.variant !== "string" || !["baseline", "candidate"].includes(trial.variant)
      || !Number.isSafeInteger(trial.repetition) || Number(trial.repetition) < 1 || Number(trial.repetition) > 3) return null;
  return trial as unknown as TraceTrial;
}

function latencyFromWire(payload: Record<string, unknown>, row: Record<string, unknown>): TraceLatency | null {
  if (typeof payload.stage !== "string" || !Object.hasOwn(LATENCY_STAGES, payload.stage)
      || typeof payload.monotonic_ms !== "number" || !Number.isFinite(payload.monotonic_ms) || payload.monotonic_ms < 0
      || (payload.duration_ms !== undefined && (typeof payload.duration_ms !== "number"
        || !Number.isFinite(payload.duration_ms) || payload.duration_ms < 0))) return null;
  for (const value of [payload.turn_id, payload.run_id, row.run_id]) {
    if (value !== undefined && !exactId(value)) return null;
  }
  if (payload.run_id !== undefined && row.run_id !== undefined && payload.run_id !== row.run_id) return null;
  for (const key of ["speech_sequence", "generation"]) {
    if (payload[key] !== undefined && (!Number.isSafeInteger(payload[key]) || Number(payload[key]) < 0)) return null;
  }
  return { stage: payload.stage as TraceLatency["stage"], monotonicMs: payload.monotonic_ms,
    durationMs: payload.duration_ms as number | undefined, turnId: payload.turn_id as string | undefined,
    speechSequence: payload.speech_sequence as number | undefined, generation: payload.generation as number | undefined };
}

function turnBindings(entries: ActionTraceEntry[]): Map<string, Set<string>> {
  const bindings = new Map<string, Set<string>>();
  for (const entry of entries) {
    const turnId = entry.latency?.turnId ?? (entry.payload.kind === "run" ? entry.payload.turn_id : undefined);
    if (!exactId(turnId) || !exactId(entry.runId)) continue;
    const runs = bindings.get(turnId) ?? new Set<string>();
    runs.add(entry.runId);
    bindings.set(turnId, runs);
  }
  return bindings;
}

function latencyRunId(entry: ActionTraceEntry, bindings: Map<string, Set<string>>): string | undefined {
  if (entry.runId) return entry.runId;
  const runs = entry.latency?.turnId ? bindings.get(entry.latency.turnId) : undefined;
  return runs?.size === 1 ? [...runs][0] : undefined;
}

/** Earlier timing enters this view only through a retained exact identity. */
export function traceEntriesSince(entries: ActionTraceEntry[], since: number): ActionTraceEntry[] {
  const recent = entries.filter(entry => entry.at >= since);
  const runs = new Set(recent.flatMap(entry => entry.runId ? [entry.runId] : []));
  const turns = new Set(recent.flatMap(entry => entry.latency?.turnId ? [entry.latency.turnId] : []));
  const bindings = turnBindings(entries);
  return entries.filter(entry => {
    if (entry.at >= since) return true;
    if (!entry.latency) return false;
    const run = latencyRunId(entry, bindings);
    return run ? runs.has(run) : Boolean(entry.latency.turnId && turns.has(entry.latency.turnId));
  });
}

function compact(value: string, limit: number): string {
  const text = value.replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function publicValue(value: unknown, depth = 0, budget = { chars: 70_000 }): TraceValue {
  if (budget.chars <= 0 || depth > 10) return "[Display limit reached]";
  if (typeof value === "string") {
    const cap = Math.min(50_000, budget.chars);
    budget.chars -= Math.min(value.length, cap);
    return value.length > cap ? `${value.slice(0, cap)}… [Display limit reached]` : value;
  }
  if (value === null || typeof value === "boolean") return value as null | boolean;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (Array.isArray(value)) return value.slice(0, 200).map(item => publicValue(item, depth + 1, budget));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).slice(0, 100)
      .filter(([key]) => !key.startsWith("_") && !["reasoning", "reasoning_content", "analysis", "chain_of_thought"].includes(key))
      .map(([key, item]) => [key.slice(0, 120), publicValue(item, depth + 1, budget)]));
  }
  return null;
}

function entryFromWire(value: unknown, since: number): ActionTraceEntry | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (typeof row.at !== "number" || !Number.isFinite(row.at)
      || typeof row.channel !== "string" || !CHANNELS.has(row.channel)
      || typeof row.line !== "string" || !row.line.trim()) return null;
  const detail = Array.isArray(row.detail)
    ? row.detail.slice(0, 12).filter((item): item is string => typeof item === "string").map(item => item.slice(0, 500)).join("\n") : "";
  const payload = publicValue(row.payload);
  const latencyPayload = row.payload && typeof row.payload === "object" && !Array.isArray(row.payload)
    ? row.payload as Record<string, unknown> : undefined;
  const latency = latencyPayload?.kind === "latency" ? latencyFromWire(latencyPayload, row) : undefined;
  const trial = row.trial === undefined ? undefined : trialFromWire(row.trial);
  if (trial === null) return null;
  if (latency === null || (["latency", "measurement"].includes(row.channel) && !latency)) return null;
  if (row.at < since && !latency) return null;
  return {
    id: typeof row.id === "string" ? row.id.slice(0, 160) : JSON.stringify([row.at, row.channel, row.line, detail]),
    sequence: Number.isSafeInteger(row.seq) && Number(row.seq) > 0 ? Number(row.seq) : undefined,
    at: row.at, channel: row.channel, line: compact(row.line, 300), detail,
    runId: exactId(row.run_id) ? row.run_id
      : latency && exactId(latencyPayload?.run_id) ? latencyPayload.run_id : undefined,
    taskRef: typeof row.task_ref === "string" ? row.task_ref.slice(0, 300) : undefined,
    agentRef: typeof row.agent_ref === "string" ? row.agent_ref.slice(0, 300) : undefined,
    callId: typeof row.call_id === "string" ? row.call_id.slice(0, 200) : undefined,
    step: typeof row.step === "number" && Number.isFinite(row.step) ? row.step : undefined,
    truncated: row.truncated === true,
    payload: payload && !Array.isArray(payload) && typeof payload === "object" ? payload : {},
    latency,
    trial,
  };
}

export function applyTraceFrame(current: ActionTraceEntry[], frame: unknown, since: number): ActionTraceEntry[] {
  if (typeof frame !== "string" || frame.length > TRACE_FRAME_LIMIT) return current;
  try {
    const payload = JSON.parse(frame);
    if (!payload || typeof payload !== "object") return current;
    let entries: ActionTraceEntry[];
    if (["snapshot", "replay"].includes(payload.type) && Array.isArray(payload.entries)) {
      entries = payload.entries.slice(-500).map((row: unknown) => entryFromWire(row, since))
        .filter((row: ActionTraceEntry | null): row is ActionTraceEntry => row !== null);
      if (payload.type === "replay") entries = [...current, ...entries];
    } else if (payload.type === "entry") {
      const entry = entryFromWire(payload.entry, since);
      if (!entry) return current;
      entries = [...current, entry];
    } else return current;
    const order = (a: ActionTraceEntry, b: ActionTraceEntry) =>
      a.sequence !== undefined && b.sequence !== undefined ? a.sequence - b.sequence : a.at - b.at;
    const unique = [...new Map(entries.map(entry => [entry.id, entry])).values()].sort(order);
    const task = unique.findLast(entry => entry.channel === "run");
    const packet = task?.runId ? unique.find(entry => entry.runId === task.runId && entry.payload.kind === "packet") : undefined;
    const bindings = turnBindings(unique);
    const timings = task?.runId ? unique.filter(entry => entry.latency && latencyRunId(entry, bindings) === task.runId) : [];
    // Retain early and late measurements without displacing the bounded action tail.
    const timingAnchors = timings.length > 32 ? [...timings.slice(0, 16), ...timings.slice(-16)] : timings;
    // Keep the current Task's instructions inspectable throughout a long run.
    const anchors = [task, packet, ...timingAnchors].filter((entry): entry is ActionTraceEntry => Boolean(entry));
    const tail = unique.filter(entry => !anchors.includes(entry)).slice(-(TRACE_ENTRY_LIMIT - anchors.length));
    return [...anchors, ...tail].sort(order);
  } catch {
    return current;
  }
}

export function traceText(value: TraceValue | undefined): string {
  return typeof value === "string" ? value : "";
}
export function fieldLabel(key: string): string {
  const known: Record<string, string> = {
    ref: "Article", refs: "Articles", task_ref: "Task article", agent_ref: "Agent article",
    first_public_delta_ms: "Time to first text (ms)", preflight_ms: "Preparation (ms)",
    generation_ms: "Response generation (ms)", cached_input_tokens: "Reused input tokens",
    resource_wait_ms: "Waiting for model availability (ms)",
    retrieval_ms: "Knowledge retrieval (ms)", duration_ms: "Duration (ms)",
    source_ref: "Source file", reasoning_effort: "Reasoning setting", url: "Web address",
    sha256: "Content fingerprint", truncated: "Shortened for display",
    history: "Execution history", runbook_ref: "Runbook article", tool_ref: "Tool article",
    runbook_sha256: "Recorded Runbook revision", tool_sha256: "Recorded Tool revision",
    scan_complete: "Complete within time window", excluded: "Records excluded from comparisons",
    eligible_runs: "Attempts used for failure rate", eligible_calls: "Calls used for error rate",
    evidence_run_ids: "Supporting runs", evidence_calls: "Supporting calls",
    findings_omitted: "Additional findings outside display limit",
  };
  return known[key] ?? key.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_\.]+/g, " ").replace(/^./, c => c.toUpperCase());
}

export function traceChannelLabel(channel: string): string {
  return ({ run: "Task", activation: "Preparation", tool: "Action", result: "Result",
    status: "Outcome", error: "Problem", context: "Context", model: "Model" })[channel] ?? "Event";
}

export function traceSimulationLabel(entry: ActionTraceEntry): string {
  const trial = entry.trial;
  if (trial) return `Simulation · ${fieldLabel(trial.variant)} · ${trial.case_id} · ${trial.split === "train" ? "Training" : "Holdout"} · repetition ${trial.repetition}`;
  // Retained events from the first evaluator have only the controller's label.
  // Preserve that display warning without guessing a trial or correlation.
  return entry.payload.simulated === true || entry.line.startsWith("Simulation · ") ? "Simulation" : "";
}

export function traceActionTitle(entry: ActionTraceEntry): string {
  const title = actionTitle(entry);
  const simulation = traceSimulationLabel(entry);
  return simulation && !title.startsWith("Simulation · ") ? `${simulation} · ${title}` : title;
}

function actionTitle(entry: ActionTraceEntry): string {
  if (entry.latency) return LATENCY_STAGES[entry.latency.stage];
  const name = traceText(entry.payload.name);
  const titles: Record<string, string> = {
    "vault.read": "Read an article", "vault.search": "Find related knowledge", "vault.list": "Browse articles",
    "web.search": "Search the web", "web.fetch": "Read a web page", "web.read": "Read a web page",
    "source.read": "Read source material", "source.handoff": "Hand research to Alexandria",
    "vault.propose": "Propose an article change", "review.decide": "Apply a review decision",
    "task.complete": "Submit the task outcome", "task.create": "Create a follow-up task",
    "harness.status": "Check system health", "computer.observe": "Look at the current application",
    "task.inspect": "Inspect a task", "review.inspect": "Inspect pending reviews",
    "computer.click": "Click a control", "window.activate": "Focus an application",
    "window.place": "Place an application", "application.launch": "Open an application",
    "observations.temporary.read": "Read recent observations",
  };
  if (entry.payload.kind === "packet") return "Thinking Packet";
  if (entry.payload.kind === "model") return ({ waiting: "Waiting for model availability", started: "Preparing the next response",
    result: "Response received", error: "Response generation failed", interrupted: "Response generation interrupted" })[traceText(entry.payload.phase)] ?? "Response measurements";
  if (entry.payload.kind === "context") return "Update working context";
  return name ? titles[name] ?? fieldLabel(name) : entry.line;
}

export function traceActionTarget(entry: ActionTraceEntry): string {
  const args = entry.payload.arguments;
  if (!args || typeof args !== "object" || Array.isArray(args)) return "";
  for (const key of ["query", "ref", "source_ref", "url", "path", "title", "application", "target"]) {
    const value = traceText(args[key]);
    if (value) return compact(value, 180);
  }
  return "";
}

const INSPECTION_STATUS_LABELS: Record<string, string> = {
  "task.inspect": "Inspected task", "harness.status": "Harness health",
};

/** Inspection findings describe the subject, separately from the Tool execution. */
export function traceRowFinding(row: TraceRow): string {
  const value = row.result ?? row.entry;
  const label = INSPECTION_STATUS_LABELS[traceText(row.entry.payload.name) || traceText(value.payload.name)];
  const result = value.payload.result;
  if (!label || value.payload.status !== "returned" || !result || typeof result !== "object" || Array.isArray(result)) return "";
  const status = traceText(result.status);
  return status ? `${label}: ${fieldLabel(compact(status, 60))}` : "";
}

export function traceRowState(row: TraceRow): string {
  const value = row.result ?? row.entry;
  if (value.channel === "error") return "Problem";
  if (row.entry.payload.kind === "tool") {
    if (!row.result && row.entry.payload.phase === "start") return "Waiting";
    const status = traceText(value.payload.status);
    const result = value.payload.result;
    if (status === "returned" && result && typeof result === "object" && !Array.isArray(result)) {
      const reported = traceText(result.status);
      if (!INSPECTION_STATUS_LABELS[traceText(row.entry.payload.name) || traceText(value.payload.name)]
          && ["failed", "error", "blocked", "rejected", "degraded"].includes(reported)) return fieldLabel(reported);
    }
    return ({ error: "Error", rejected: "Rejected", interrupted: "Interrupted", returned: "Returned" })[status] ?? "Returned";
  }
  if (value.payload.kind === "packet") return "Prepared";
  if (value.payload.kind === "model") return ({ waiting: "Waiting", started: "Generating", result: "Measured",
    error: "Error", interrupted: "Interrupted" })[traceText(value.payload.phase)] ?? "Measured";
  return value.payload.kind === "run" ? fieldLabel(traceText(value.payload.status) || "recorded") : "Recorded";
}

/** Correlate only explicit run/call identities. Legacy rows remain separate events. */
export function traceRuns(entries: ActionTraceEntry[]): TraceRun[] {
  const groups = new Map<string, TraceRun>();
  const bindings = turnBindings(entries);
  let legacyId = "unbound";
  for (const entry of entries) {
    if (!entry.runId && entry.channel === "run") legacyId = entry.id;
    const id = entry.latency ? latencyRunId(entry, bindings)
      ?? (entry.latency.turnId ? `latency:turn:${entry.latency.turnId}` : `latency:event:${entry.id}`)
      : entry.runId ?? legacyId;
    let run = groups.get(id);
    if (!run) {
      run = { id, title: entry.taskRef?.split("/").at(-1) ?? (entry.latency ? "Response timing" : "System activity"), agent: "", at: entry.at,
        status: "", summary: "", objective: "", entries: [], rows: [], modelRequests: [], latencyEntries: [] };
      groups.set(id, run);
    }
    run.entries.push(entry);
    if (entry.latency && !entry.trial && entry.payload.simulated !== true) run.latencyEntries.push(entry);
    if (entry.channel === "run" && !entry.trial && entry.payload.simulated !== true) run.at = entry.at;
    if (entry.payload.kind === "packet" && !entry.trial && entry.payload.simulated !== true && Array.isArray(entry.payload.sections)) {
      const objective = entry.payload.sections.find(section => section && typeof section === "object"
        && !Array.isArray(section) && section.key === "objective");
      if (objective && typeof objective === "object" && !Array.isArray(objective)) {
        run.objective = traceText(objective.text).replace(/^## Objective\s*\n/, "");
      }
    }
    if (entry.payload.kind === "run" && !entry.trial && entry.payload.simulated !== true) {
      run.title = traceText(entry.payload.task_title) || run.title;
      run.agent = traceText(entry.payload.agent_title) || run.agent;
      run.status = traceText(entry.payload.status) || run.status;
      run.summary = traceText(entry.payload.summary) || run.summary;
    } else if (entry.channel === "run" && !entry.trial && entry.payload.simulated !== true) run.title = entry.line;
  }
  for (const run of groups.values()) {
    const calls = new Map<string, TraceRow>();
    const models = new Map<string, TraceModelRequest>();
    const correlation = (entry: ActionTraceEntry) => JSON.stringify([entry.trial?.id ?? null, entry.callId]);
    run.latencyEntries.sort((a, b) => a.latency!.monotonicMs - b.latency!.monotonicMs);
    for (const entry of run.entries) {
      if (entry.latency) continue;
      if (entry.payload.kind === "model" || entry.channel === "model") {
        const id = entry.runId && entry.callId ? correlation(entry) : entry.id;
        const request = models.get(id) ?? { id, entries: [] };
        request.entries.push(entry);
        models.set(id, request);
        continue;
      }
      if (entry.callId && entry.payload.kind === "tool" && entry.payload.phase === "result") {
        const call = calls.get(correlation(entry));
        if (call) { call.result = entry; continue; }
      }
      const row = { id: entry.id, entry };
      run.rows.push(row);
      if (entry.callId && entry.payload.kind === "tool" && entry.payload.phase === "start") calls.set(correlation(entry), row);
    }
    // A provider request produces at most one Tool action in its exact executor
    // step. Missing or ambiguous identities stay at Task level, never guessed.
    for (const request of models.values()) {
      const first = request.entries[0];
      const step = first.step;
      const matching = run.rows.filter(row => row.entry.payload.kind === "tool" && row.entry.step === step
        && row.entry.runId === first.runId && row.entry.trial?.id === first.trial?.id && row.entry.callId);
      const sameStep = [...models.values()].filter(model => model.entries.some(entry => entry.step === step
        && entry.trial?.id === first.trial?.id));
      if (first.runId && first.callId && Number.isInteger(step) && step! > 0
          && request.entries.every(entry => entry.step === step) && matching.length === 1 && sameStep.length === 1) {
        matching[0].model = request;
      } else run.modelRequests.push(request);
    }
  }
  return [...groups.values()];
}
