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
  id: string;
  title: string;
  kind: string;
  status?: string | null;
  assignee?: string | null;
  children?: string[];
  synthetic?: boolean;
  order?: number;
  triggers?: string[];
  routing?: string;
  checkouts?: Partial<Record<"tools" | "skills" | "runbooks" | "tasks", string[]>>;
  source_scopes?: string[];
  source_scope_refs?: string[];
  tags?: string[];
}
export interface GraphLink { source: string; target: string }
export type GraphNavigationRole = "executive" | "guardian" | "curator" | "researcher" | "library";
export interface GraphNavigationSubject {
  id: string;
  title: string;
  parent_id: string | null;
}
export interface GraphNavigationGroup {
  id: GraphNavigationRole;
  title: string;
  subtitle: string;
  role: GraphNavigationRole;
  root_ref: string;
  subjects: GraphNavigationSubject[];
}
export interface GraphNavigation { groups: GraphNavigationGroup[] }
export interface GraphSnapshot {
  nodes: GraphNode[];
  links: GraphLink[];
  auto_curated?: string[];
  navigation: GraphNavigation;
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
  enabled?: boolean;
  schedule?: string | null; next_run?: number | null; blocked_reason?: string | null; last_run?: string | null;
}
export interface Proposal {
  file: string; title: string; action: string; target: string; agent: string;
  task: string; reason: string; proposed_at: string; body_preview: string;
  run_id?: string; approvable: boolean; blocked_reason: string;
  review_class: "article" | "link";
  link_changes: { added: string[]; removed: string[] } | null;
}
export interface NoteDoc {
  ref: string; title: string; kind: string; meta: Record<string, string>; body: string;
  children?: string[];
  auto_curate?: boolean; auto_curate_task?: string | null;
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
  user_speaking: boolean;
  live_transcript: { text: string; final: boolean } | null;
  acoustic_echo_cancellation: boolean;
  speech: SpeechRuntime;
  model: { id: string; label: string; devices: string[] } | null;
  task_ref: string;
  task_run_id: string | null;
  task_status: string;
  scheduler_paused: boolean;
  recent_log: string[];
}
export type KnowledgeActivityPhase = "query_started" | "path" | "speaking" | "query_completed" | "cleared";
export interface KnowledgeActivity {
  phase: KnowledgeActivityPhase;
  refs: string[];
  query?: string;
  at?: number;
  /** Measured uncapped fast-context retrieval time for a live text/voice turn. */
  retrievalMs?: number;
  /** Main Executive graph or one named satellite agent graph. */
  graphId?: string;
}
export type CheckoutAgent = "executive" | "guardian" | "curator" | "researcher";
export interface CheckoutAssignment { agent: CheckoutAgent; ref: string; kind: string }
export interface SourceCheckoutAssignment { agent: CheckoutAgent; tree: string }
export interface VaultFile { ref: string; path: string; title: string; kind: string }
export interface SourceFile {
  key: string; path: string; name: string; media_type: string; size: number;
  modified_at: number; storage: "blob" | "knowledge" | "code" | "system";
  read_only: boolean; articles: string[];
}
export interface SourceDoc extends SourceFile {
  content: string | null; truncated: boolean; sha256: string | null;
}
export interface SourceIssue { path: string; status: string; detail: string }
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
  graph: () => json<GraphSnapshot>("/api/graph"),
  article: (ref: string) => json<NoteDoc>(`/api/articles/${encodeURI(ref)}`),
  files: () => json<VaultFile[]>("/api/files"),
  sourceFiles: () => json<{ files: SourceFile[]; issues: SourceIssue[] }>(
    "/api/source-files",
    { cache: "no-store" },
  ),
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
    json<{ article: string; enabled: boolean; task: string | null }>(
      `/api/articles/${encodeURI(ref)}/auto-curate`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled }),
      }),
  checkouts: () => json<{ assignments: CheckoutAssignment[] }>("/api/library/checkouts"),
  setCheckout: (ref: string, agent: CheckoutAgent, checkedOut: boolean) =>
    json<{ agent: CheckoutAgent; ref: string; kind: string; checked_out: boolean;
      checkout_changed: boolean; paired_skills: string[]; activated_task: string | null;
      activation_state: "started" | "queued" | null; queue_position: number | null;
      queue_depth: number; activation_error: string | null }>(
      `/api/library/checkouts/${encodeURI(ref)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ agent, checked_out: checkedOut }),
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
let sourceSelection: string | null = null;

export function openReader(ref: string): void {
  readerSelection = ref;
  sourceSelection = null;
  window.dispatchEvent(new CustomEvent("obsidience:open-reader", { detail: { ref } }));
}

export function onOpenReader(handler: (ref: string) => void): () => void {
  const fn = (e: Event) => handler((e as CustomEvent<{ ref: string }>).detail.ref);
  window.addEventListener("obsidience:open-reader", fn);
  if (readerSelection) handler(readerSelection);
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
