/** Obsidience daemon client (REST + WS). */

export const API_BASE = "http://127.0.0.1:8765";
export const WS_BASE = "ws://127.0.0.1:8765";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const raw = await res.text();
    let detail = raw;
    try {
      const parsed = JSON.parse(raw) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // Plain-text failures are already readable.
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

export interface GraphNode {
  article_ref?: string;
  id: string;
  title: string;
  kind: string;
  status?: string | null;
  assignee?: string | null;
  parent_id?: string;
  navigation_ref?: string;
  children?: string[];
  synthetic?: boolean;
  order?: number;
  triggers?: string[];
  routing?: string;
  dependencies?: Partial<Record<"tools" | "skills" | "runbooks" | "tasks", string[]>>;
  source_scopes?: string[];
  source_scope_refs?: string[];
  tags?: string[];
}
export interface GraphLink {
  source: string;
  target: string;
  derived?: boolean;
  relation?: string;
  via?: string[];
  for_agent?: string;
}
export interface GraphLinkProposal {
  proposal_id: string;
  run_id: string;
  source: string;
  target: string;
}
export interface GraphLinkProposals {
  entries: GraphLinkProposal[];
  truncated: boolean;
}
export interface LinkReviewChange {
  proposal_id: string;
  run_id: string;
  state: "pending" | "approved" | "rejected";
  decided_at?: number;
  links?: Array<{ source: string; target: string }>;
  truncated: boolean;
}
export type GraphNavigationRole = "executive" | "guardian" | "curator" | "researcher" | "library";
export interface GraphNavigationSubject {
  id: string;
  title: string;
  parent_id: string | null;
  path?: string;
  article_ref?: string;
}
export interface GraphNavigationGroup {
  id: GraphNavigationRole;
  title: string;
  subtitle: string;
  role: GraphNavigationRole;
  root_ref: string;
  subjects: GraphNavigationSubject[];
  article_refs?: string[];
}
export interface GraphNavigation { groups: GraphNavigationGroup[] }
export interface GraphSnapshot {
  nodes: GraphNode[];
  links: GraphLink[];
  auto_curated?: string[];
  auto_curate_resolved?: boolean;
  navigation: GraphNavigation;
  link_proposals?: GraphLinkProposals;
}
export interface TaskRow {
  ref: string; title: string; status: string; assignee: string; runbook: string; subtasks: number;
  subtask_refs?: string[];
  excluded_subtask_refs?: string[];
  taxonomy_path?: string;
  reasoning_effort: ReasoningEffort;
  model: ModelPreference;
  resolved_model: string;
  triggers: string[];
  queue_depth?: number;
  execution?: {
    state: "running" | "review" | "needs_attention" | "waiting" | "ready" | "idle";
    label?: string;
    reason: string;
    last_run: { id: string; status: string; finished: number; summary: string } | null;
    retry_allowed: boolean;
    retry_blocked_reason: string;
  };
  enabled?: boolean;
  schedule?: string | null; next_run?: number | null; blocked_reason?: string | null; last_run?: string | null;
}
export interface Proposal {
  file: string; title: string; action: string; target: string; agent: string;
  task: string; reason: string; proposed_at: string; body_preview: string;
  run_id?: string; approvable: boolean; blocked_reason: string;
  review_class: "article" | "link";
  link_changes: { added: string[]; removed: string[] } | null;
  link_evidence: { ref: string; change: "added" | "removed";
    derivation: "proposed_wikilink" | "accepted_wikilink";
    body_line: number; excerpt: string; endpoint_sha256: string }[];
  evidence_warning: string;
}
export interface NoteDoc {
  ref: string; title: string; kind: string; meta: Record<string, string>; body: string;
  children?: string[];
  auto_curate?: boolean; auto_curate_supported?: boolean;
  read_only?: boolean; managed_by?: string;
}
export interface HarnessStatus {
  notes: number; tasks: number; tasks_by_status: Record<string, number>;
  proposals_pending: number; sources: number; source_issues: number;
  speech: SpeechRuntime;
  llm: { base_url: string | null; model: string; models: string[]; residency_policy: "hardware_slots" };
  vault: string; time: string;
}
export type ReasoningEffort = "none" | "low" | "medium" | "high" | "xhigh";
export type ModelPreference = "auto" | string;
export interface ModelOption {
  id: string; label: string; purpose: string; base_url: string;
  context_tokens: number; max_output_tokens: number; quantization: string;
  hardware: string; runtime: string; installed: boolean; loaded: boolean;
  available: boolean; state: string; size_bytes: number | null;
  default_for: string;
  max_context_tokens: number;
  supported_devices: string[];
  allowed_devices: string[];
  min_gpu_count: number;
  device_sets: string[][];
  assigned_devices: string[];
  active_devices: string[];
  gpu_memory_utilization: number;
  max_num_seqs: number;
  task_capable: boolean;
  category: "task_reasoning" | "realtime_interface";
  benchmark_kind: "tokens" | "realtime_audio";
  hardware_assignable: boolean;
  last_benchmark: ModelBenchmark | null;
  capabilities: string[];
  source_manifest: string;
}
export interface ModelsCatalog { models: ModelOption[] }
export interface ModelSettings {
  residency_policy: "hardware_slots";
  hardware: Record<string, string>;
  active_models: string[];
  task_model: string | null;
  hardware_reservations: Record<string, string[]>;
  switching: boolean;
}
export interface ModelBenchmark {
  model_id: string;
  kind: "model_comparison" | "tokens" | "realtime_audio";
  contract?: string;
  devices: string[];
  output_budget_tokens?: number;
  warmup_count?: number;
  sample_count?: number;
  completion_tokens?: number;
  ttft_ms?: number;
  generation_seconds?: number;
  total_seconds?: number;
  seconds?: number;
  tokens_per_second?: number;
  summary: string;
  metrics?: Record<string, number | boolean>;
  source_path?: string;
  tested_at: string;
}
export interface HardwareOption {
  id: string; label: string; available: boolean; linked?: boolean;
}
export interface HardwareSensors {
  device: string; name?: string; driver?: string; status: "online" | "unavailable";
  memory_label?: string; memory_total_mib?: number | null; memory_used_mib?: number | null;
  memory_free_mib?: number | null; memory_used_percent?: number | null;
  utilization_percent?: number | null; memory_controller_percent?: number | null;
  encoder_percent?: number | null; decoder_percent?: number | null;
  media_engine_percent?: number | null; temperature_c?: number | null;
  power_w?: number | null; power_limit_w?: number | null;
  clock_core_mhz?: number | null; clock_memory_mhz?: number | null;
  fan_percent?: number | null; pstate?: string | null;
  pcie_generation?: number | null; pcie_width?: number | null;
  load_1m?: number | null; load_5m?: number | null; load_15m?: number | null;
  physical_cores?: number | null; threads?: number | null;
}
export interface HardwareSlot {
  id: string; label: string; kind: "cpu" | "gpu" | "igpu"; selected: string;
  options: HardwareOption[]; note: string; sensors?: HardwareSensors | null;
}
export interface HardwareInterfaceOption {
  id: string; label: string; available: boolean; detail: string;
}
export interface HardwareInterfaceSlot {
  id: "microphone" | "speaker" | "camera";
  label: string;
  kind: "input" | "output" | "camera";
  selected: string;
  options: HardwareInterfaceOption[];
  note: string;
}
export interface StorageFilesystem {
  id: string;
  source: string | null;
  filesystem: string | null;
  total_bytes: number;
  used_bytes: number;
  available_bytes: number;
  used_percent: number | null;
  mount_points: string[];
}
export interface StorageLocation {
  id: "obsidience" | "models";
  label: string;
  role: "product" | "models";
  path: string;
  available: boolean;
  filesystem_id: string | null;
  mount_point: string | null;
  subvolume: string | null;
  quota_bytes: number | null;
  allocation: "shared_filesystem" | "unavailable";
}
export interface StorageState {
  schema: "obsidience.storage.v1";
  filesystems: StorageFilesystem[];
  locations: StorageLocation[];
}
export interface HardwareState extends ModelSettings {
  policy: "hardware_slots";
  slots: HardwareSlot[];
  interfaces: HardwareInterfaceSlot[];
  speech: SpeechRuntime;
  storage: StorageState;
}
export interface HardwareCameraState {
  active: boolean;
}
export interface SpeechRuntime {
  transport: string;
  turn_taking: string;
  asr: string;
  asr_device: string;
  asr_chunk_ms: number;
  tts: string;
  tts_device: string;
  voice: string;
  voices?: { id: string; label: string }[];
}
export type RealtimePhase = "off" | "starting" | "command" | "proactive" | "stopping" | "error";
export interface RealtimeState {
  schema_version: 1;
  phase: RealtimePhase;
  enabled: boolean;
  ready: boolean;
  transport_ready: boolean;
  proactive: boolean;
  requested_proactive: boolean;
  pid: number | null;
  started_monotonic_ns: number | null;
  last_error: string | null;
  vision_source: string | null;
  audio_source: string;
  audio_sink: string;
  input_level: number;
  capture_active?: boolean;
  user_speaking: boolean;
  live_transcript: { text: string; final: boolean } | null;
  acoustic_echo_cancellation: boolean;
  speech: SpeechRuntime;
  scheduler_paused: boolean;
  recent_log: string[];
}
export type KnowledgeActivityPhase = "admission_started" | "admission_completed" | "query_started" | "path" | "speaking" | "query_completed" | "cleared";
export interface KnowledgeActivity {
  runId?: string;
  turnId?: string;
  phase: KnowledgeActivityPhase;
  refs: string[];
  query?: string;
  at?: number;
  /** Measured uncapped fast-context retrieval time for a live text/voice turn. */
  retrievalMs?: number;
  /** Main Executive graph or one named satellite agent graph. */
  graphId?: string;
}
export type AssignmentAgent = "executive" | "guardian" | "curator" | "researcher";
export type CheckoutAgent = AssignmentAgent; // Source-tree scope remains an independent checkout.
export interface TaskAssignment {
  agent: AssignmentAgent; ref: string; kind: "task"; direct: boolean; inherited: boolean;
}
export interface TaskDependency {
  agent: AssignmentAgent; ref: string; kind: "task" | "runbook" | "skill" | "tool";
}
export interface SourceCheckoutAssignment { agent: CheckoutAgent; tree: string }
export interface VaultFile { ref: string; path: string; title: string; kind: string }
export interface SourceFile {
  key: string; path: string; name: string; media_type: string; size: number;
  modified_at: number; storage: "blob" | "knowledge" | "code" | "system";
  read_only: boolean; articles: string[];
  system_label?: string;
  system_breadcrumbs?: Array<{ path: string; title: string }>;
}
export interface SourceDoc extends SourceFile {
  content: string | null; truncated: boolean; sha256: string | null;
}
export interface SourceIssue { path: string; status: string; detail: string }
interface SourceFilesPage {
  files: SourceFile[];
  issues: SourceIssue[];
  coverage?: { scope: string | null; limit: number; returned: number; consistency: "live";
    complete: boolean; next_cursor: string | null };
}

async function sourceFiles(): Promise<{ files: SourceFile[]; issues: SourceIssue[] }> {
  const files = new Map<string, SourceFile>();
  const issues = new Map<string, SourceIssue>();
  const cursors = new Set<string>();
  let after: string | null = null;
  let scope: string | null | undefined;
  while (true) {
    const page = await json<SourceFilesPage>("/api/source-files"
      + (after === null ? "" : `?after=${encodeURIComponent(after)}`), { cache: "no-store" });
    if (!page || !Array.isArray(page.files) || !Array.isArray(page.issues)) {
      throw new Error("Source hierarchy response was invalid.");
    }
    for (const file of page.files) {
      if (!file || typeof file.key !== "string" || !file.key
          || typeof file.path !== "string" || !file.path) {
        throw new Error("Source hierarchy file was invalid.");
      }
      files.set(file.key, file);
    }
    for (const issue of page.issues) {
      if (!issue || typeof issue.path !== "string" || typeof issue.status !== "string"
          || typeof issue.detail !== "string") {
        throw new Error("Source hierarchy issue was invalid.");
      }
      issues.set(JSON.stringify([issue.path, issue.status, issue.detail]), issue);
    }
    const coverage = page.coverage;
    // A legacy single response remains readable across a development restart.
    if (coverage === undefined && after === null) break;
    if (!coverage || coverage.consistency !== "live" || typeof coverage.complete !== "boolean"
        || coverage.returned !== page.files.length || !Number.isInteger(coverage.limit)
        || coverage.limit < 1 || coverage.limit > 2000 || page.files.length > coverage.limit
        || !(coverage.scope === null || typeof coverage.scope === "string")
        || (scope !== undefined && coverage.scope !== scope)) {
      throw new Error("Source hierarchy page coverage was invalid.");
    }
    scope = coverage.scope;
    if (coverage.complete) {
      if (coverage.next_cursor !== null) throw new Error("Source hierarchy completion was invalid.");
      break;
    }
    const next = coverage.next_cursor;
    if (typeof next !== "string" || !next || cursors.has(next) || !page.files.length
        || next !== page.files[page.files.length - 1].key) {
      throw new Error("Source hierarchy pagination did not advance.");
    }
    cursors.add(next);
    after = next;
  }
  return { files: [...files.values()], issues: [...issues.values()] };
}
export interface VaultMoveResult {
  source: string; destination: string; refs: Record<string, string>; article: boolean;
}
export interface WikiAction {
  ref: string; title: string; path: string; status: string; reasoning_effort: ReasoningEffort;
  agent: string; agent_label: string;
}

export const api = {
  status: () => json<HarnessStatus>("/api/status"),
  models: () => json<ModelsCatalog>("/api/models"),
  model: (modelId: string) => json<ModelOption>(`/api/models/${encodeURIComponent(modelId)}`),
  updateModel: (modelId: string, update: {
    allowed_devices: string[]; context_tokens: number; max_output_tokens: number;
    gpu_memory_utilization: number; max_num_seqs: number;
  }) => json<ModelOption>(`/api/models/${encodeURIComponent(modelId)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(update),
  }),
  benchmarkModel: (modelId: string, devices: string[]) => json<ModelBenchmark>(
    `/api/models/${encodeURIComponent(modelId)}/benchmark`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ devices }),
    }),
  modelSettings: () => json<ModelSettings>("/api/model-settings"),
  hardware: () => json<HardwareState>("/api/hardware"),
  setHardware: (device: string, component: string) => json<HardwareState>("/api/hardware", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ device, component }),
  }),
  setHardwareInterface: (hardwareInterface: string, selection: string) =>
    json<HardwareState>("/api/hardware/interfaces", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ interface: hardwareInterface, selection }),
    }),
  setSpeechVoice: (voice: string) => json<SpeechRuntime>("/api/hardware/voice", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ voice }),
  }),
  hardwareCamera: () => json<HardwareCameraState>("/api/hardware/camera"),
  setHardwareCamera: (active: boolean) => json<HardwareCameraState>("/api/hardware/camera", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ active }),
  }),
  realtime: () => json<RealtimeState>("/api/realtime"),
  startRealtime: () => json<RealtimeState>("/api/realtime/start", { method: "POST" }),
  stopRealtime: () => json<RealtimeState>("/api/realtime/stop", { method: "POST" }),
  setRealtimeProactive: (proactive: boolean) => json<RealtimeState>("/api/realtime/mode", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ proactive }),
  }),
  // Review readback must reach the authority after its committed decision.
  graph: () => json<GraphSnapshot>("/api/graph", { cache: "no-store" }),
  article: (ref: string) => json<NoteDoc>(`/api/articles/${encodeURI(ref)}`),
  files: () => json<VaultFile[]>("/api/files"),
  sourceFiles,
  sourceFile: (key: string) => json<SourceDoc>(
    `/api/source-files/${encodeURI(key)}`,
    { cache: "no-store" },
  ),
  sourceCheckouts: () => json<{ assignments: SourceCheckoutAssignment[] }>(
    "/api/source-checkouts",
    { cache: "no-store" },
  ),
  setSourceCheckout: (tree: string, agent: CheckoutAgent, checkedOut: boolean) =>
    json<{ agent: CheckoutAgent; tree: string; checked_out: boolean;
      checkout_changed: boolean; article_refs: string[] }>(
      `/api/source-checkouts/${encodeURI(tree)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ agent, checked_out: checkedOut }),
      }),
  moveVaultItem: (source: string, destinationParent: string, newName?: string) =>
    json<VaultMoveResult>("/api/files/move", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ source, destination_parent: destinationParent, new_name: newName }),
    }),
  wikiActions: () => json<WikiAction[]>("/api/actions/wiki"),
  updateArticle: (ref: string, update: { title: string; body: string }) =>
    json<{ article: string; updated: boolean }>(`/api/articles/${encodeURI(ref)}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(update),
    }),
  setAutoCurate: (ref: string, enabled: boolean) =>
    json<{ article: string; enabled: boolean }>(
      `/api/articles/${encodeURI(ref)}/auto-curate`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled }),
      }),
  assignments: () => json<{ assignments: TaskAssignment[]; dependencies: TaskDependency[] }>("/api/library/assignments"),
  setAssignment: (ref: string, agent: AssignmentAgent, assigned: boolean) =>
    json<{ agent: AssignmentAgent; ref: string; kind: "task"; assigned: boolean;
      direct: boolean; inherited: boolean; assignment_changed: boolean; activated_task: string | null;
      activation_state: "ready" | "queued" | "blocked" | null;
      activation_error: string | null }>(
      `/api/library/assignments/${encodeURI(ref)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ agent, assigned }),
      }),
  note: (ref: string) => json<NoteDoc>(`/api/notes/${encodeURI(ref)}`),
  tasks: () => json<TaskRow[]>("/api/tasks"),
  runTask: (ref: string, reasoningEffort: ReasoningEffort, params?: Record<string, string>, model?: ModelPreference) => json<{
    started: string; reasoning_effort: string; model: string; resolved_model: string;
  }>(
    `/api/tasks/${encodeURI(ref)}/run`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        reasoning_effort: reasoningEffort,
        ...(params ? { params } : {}),
        ...(model ? { model } : {}),
      }),
    }),
  setTaskReasoning: (ref: string, reasoningEffort: ReasoningEffort) => json<{ task: string; reasoning_effort: string }>(
    `/api/tasks/${encodeURI(ref)}/reasoning`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reasoning_effort: reasoningEffort }),
    }),
  setTaskModel: (ref: string, model: ModelPreference) => json<{
    task: string; model: string; resolved_model: string;
  }>(`/api/tasks/${encodeURI(ref)}/model`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ model }),
  }),
  setTaskAssignee: (ref: string, assignee: string) => json<{ task: string; assignee: string }>(
    `/api/tasks/${encodeURI(ref)}/assignee`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ assignee }),
    }),
  setTaskExclusions: (ref: string, excludedSubtaskRefs: string[]) =>
    json<{ task: string; excluded_subtask_refs: string[] }>(
      `/api/tasks/${encodeURI(ref)}/exclusions`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ excluded_subtask_refs: excludedSubtaskRefs }),
      }),
  updateTask: (ref: string, update: {
    title: string;
    body: string;
    schedule: string;
    assignee: string;
    runbook: string;
    reasoning_effort: ReasoningEffort;
    model: ModelPreference;
  }) => json<{ task: string; updated: boolean }>(`/api/tasks/${encodeURI(ref)}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(update),
  }),
  runs: () => json<Array<Record<string, unknown>>>("/api/runs"),
  reviews: () => json<Proposal[]>("/api/reviews"),
  approve: (name: string) => json(`/api/reviews/${encodeURIComponent(name)}/approve`, { method: "POST" }),
  reject: (name: string, reason = "") => json(
    `/api/reviews/${encodeURIComponent(name)}/reject?reason=${encodeURIComponent(reason)}`, { method: "POST" }),
};

let readerSelection: string | null = null;
let readerGraphId = "";
let sourceSelection: string | null = null;

export function openReader(ref: string, graphId = ""): void {
  readerSelection = ref;
  readerGraphId = graphId;
  sourceSelection = null;
  window.dispatchEvent(new CustomEvent("obsidience:open-reader", { detail: { ref, graphId } }));
}

export function onOpenReader(handler: (ref: string, graphId: string) => void): () => void {
  const fn = (e: Event) => {
    const { ref, graphId = "" } = (e as CustomEvent<{ ref: string; graphId?: string }>).detail;
    handler(ref, graphId);
  };
  window.addEventListener("obsidience:open-reader", fn);
  if (readerSelection) handler(readerSelection, readerGraphId);
  return () => window.removeEventListener("obsidience:open-reader", fn);
}

export function openSourceFile(key: string): void {
  sourceSelection = key;
  window.dispatchEvent(new CustomEvent("obsidience:open-source", { detail: { key } }));
}

export function onOpenSourceFile(handler: (key: string) => void): () => void {
  const fn = (event: Event) => handler((event as CustomEvent<{ key: string }>).detail.key);
  window.addEventListener("obsidience:open-source", fn);
  if (sourceSelection) handler(sourceSelection);
  return () => window.removeEventListener("obsidience:open-source", fn);
}

export function openTasks(): void {
  window.dispatchEvent(new Event("obsidience:open-tasks"));
}

export function onOpenTasks(handler: () => void): () => void {
  window.addEventListener("obsidience:open-tasks", handler);
  return () => window.removeEventListener("obsidience:open-tasks", handler);
}

export function announceKnowledgeActivity(activity: KnowledgeActivity): void {
  window.dispatchEvent(new CustomEvent("obsidience:knowledge-activity", { detail: activity }));
}

export function onKnowledgeActivity(handler: (activity: KnowledgeActivity) => void): () => void {
  const fn = (event: Event) => handler((event as CustomEvent<KnowledgeActivity>).detail);
  window.addEventListener("obsidience:knowledge-activity", fn);
  return () => window.removeEventListener("obsidience:knowledge-activity", fn);
}
