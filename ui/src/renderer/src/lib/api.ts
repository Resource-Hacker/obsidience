/** Obsidience daemon client (REST + WS). */

export const API_BASE = "http://127.0.0.1:8765";
export const WS_BASE = "ws://127.0.0.1:8765";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) throw new Error(`${path}: ${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

export interface GraphNode {
  id: string;
  title: string;
  kind: string;
  status?: string | null;
  assignee?: string | null;
  subtasks?: string[];
  checkouts?: Partial<Record<"tools" | "skills" | "runbooks" | "tasks", string[]>>;
  tags?: string[];
}
export interface GraphLink { source: string; target: string }
export interface TaskRow {
  ref: string; title: string; status: string; assignee: string; runbook: string; subtasks: number;
  subtask_refs?: string[];
  reasoning_effort: ReasoningEffort;
  schedule?: string | null; next_run?: number | null; blocked_reason?: string | null; last_run?: string | null;
}
export interface Proposal {
  file: string; title: string; action: string; target: string; agent: string;
  task: string; reason: string; proposed_at: string; body_preview: string;
}
export interface NoteDoc {
  ref: string; title: string; kind: string; meta: Record<string, string>; body: string;
}
export interface HarnessStatus {
  notes: number; tasks: number; tasks_by_status: Record<string, number>;
  proposals_pending: number; voice: { stt: boolean; reason?: string };
  llm: { base_url: string; model: string }; vault: string; time: string;
}
export type ReasoningEffort = "none" | "low" | "medium" | "high";
export type CheckoutAgent = "executive" | "guardian" | "curator" | "researcher";
export interface CheckoutAssignment { agent: CheckoutAgent; ref: string; kind: string }

export const api = {
  status: () => json<HarnessStatus>("/api/status"),
  graph: () => json<{ nodes: GraphNode[]; links: GraphLink[] }>("/api/graph"),
  article: (ref: string) => json<NoteDoc>(`/api/articles/${encodeURI(ref)}`),
  checkouts: () => json<{ assignments: CheckoutAssignment[] }>("/api/library/checkouts"),
  setCheckout: (ref: string, agent: CheckoutAgent, checkedOut: boolean) =>
    json<{ agent: CheckoutAgent; ref: string; kind: string; checked_out: boolean }>(
      `/api/library/checkouts/${encodeURI(ref)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ agent, checked_out: checkedOut }),
      }),
  note: (ref: string) => json<NoteDoc>(`/api/notes/${encodeURI(ref)}`),
  tasks: () => json<TaskRow[]>("/api/tasks"),
  runTask: (ref: string, reasoningEffort: ReasoningEffort) => json<{ started: string; reasoning_effort: string }>(
    `/api/tasks/${encodeURI(ref)}/run`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reasoning_effort: reasoningEffort }),
    }),
  setTaskReasoning: (ref: string, reasoningEffort: ReasoningEffort) => json<{ task: string; reasoning_effort: string }>(
    `/api/tasks/${encodeURI(ref)}/reasoning`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reasoning_effort: reasoningEffort }),
    }),
  setTaskAssignee: (ref: string, assignee: string) => json<{ task: string; assignee: string }>(
    `/api/tasks/${encodeURI(ref)}/assignee`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ assignee }),
    }),
  updateTask: (ref: string, update: {
    title: string;
    body: string;
    schedule: string;
    assignee: string;
    runbook: string;
    reasoning_effort: ReasoningEffort;
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
  transcribe: async (blob: Blob): Promise<string> => {
    const form = new FormData();
    form.append("file", blob, "utterance.webm");
    const res = await fetch(`${API_BASE}/api/voice/transcribe`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`transcribe: ${res.status}`);
    return ((await res.json()) as { text: string }).text;
  },
};

export function openReader(ref: string): void {
  window.dispatchEvent(new CustomEvent("obsidience:open-reader", { detail: { ref } }));
}

export function onOpenReader(handler: (ref: string) => void): () => void {
  const fn = (e: Event) => handler((e as CustomEvent<{ ref: string }>).detail.ref);
  window.addEventListener("obsidience:open-reader", fn);
  return () => window.removeEventListener("obsidience:open-reader", fn);
}
