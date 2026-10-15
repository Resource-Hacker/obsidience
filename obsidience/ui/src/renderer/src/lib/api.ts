/** The Harness API client: every page's HTTP calls and socket origin. */

const API_BASE = "http://127.0.0.1:8765";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

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
export type GraphNavigationRole = "executive" | "guardian" | "curator" | "researcher" | "library" | "discord" | "omnibot";
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
  scene?: "executive" | "library" | "independent";
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

/** The Memory and Code providers' graph (/api/graphs/*) and their /ws/activity operations. */
export interface ProviderNode {
  id: string; name: string; kind: string; color: string;
  x?: number; y?: number; z?: number; size?: number;
  file?: string; qualified_name?: string; ref?: string; text?: string; graph_id?: string;
  start_line?: number; end_line?: number; body_hash?: string; external?: boolean;
  aliases?: string[];
  date?: string; occurred_start?: string | null; occurred_end?: string | null;
  tags?: string[]; proof_count?: number; support?: string[];
}
export interface ProviderEdge { source: string; target: string; kind: string; color?: string; weight?: number }
export interface ProviderGraph {
  provider: string; graph_id: string; nodes: ProviderNode[]; edges: ProviderEdge[];
  total: number; limited: boolean; missed?: number; updated_at?: string; project?: string; revision?: string;
  code_root?: string; code_file?: string; external_count?: number;
  index?: {state: string; updated_at?: string; error?: string};
}
export interface GraphOperation {
  id: string; kind: string; status: string; refs: string[]; label: string;
  graph_id: string; at: number; expires_at: number; refresh: boolean;
}

export interface MemoryBank { id: string; name: string; agent_ref: string; count: number; scene: "executive" | "independent" }
/** Changed records and edges since the shown revision of one memory bank. */
export type MemoryDelta = Pick<ProviderGraph, "provider" | "graph_id" | "nodes" | "edges" | "total" | "limited" | "updated_at"> & {
  delta: true; since: string; revision: string; removed: string[]; removed_edges: ProviderGraph["edges"];
};

export const api = {
  graph: () => json<GraphSnapshot>("/api/graph", { cache: "no-store" }),
  memoryBanks: (signal?: AbortSignal, bank?: string) => json<{ banks: MemoryBank[] }>(
    "/api/graphs/memory/banks" + (bank ? "?bank=" + encodeURIComponent(bank) : ""), { signal }),
  memoryGraph: (bank: string, since?: string, signal?: AbortSignal) => json<ProviderGraph | MemoryDelta>(
    "/api/graphs/memory?bank=" + encodeURIComponent(bank) + (since ? "&since=" + encodeURIComponent(since) : ""), { signal }),
  memoryRecord: (bank: string, id: string, signal?: AbortSignal) => json<Record<string, unknown>>(
    "/api/graphs/memory/record?bank=" + encodeURIComponent(bank) + "&id=" + encodeURIComponent(id), { signal }),
  codeGraph: (signal?: AbortSignal) => json<ProviderGraph>("/api/graphs/code", { signal }),
  refreshCodeGraph: () => json<ProviderGraph["index"]>("/api/graphs/code/refresh", { method: "POST" }),
  /** The Shell command socket's user-only token, read again for every connection. */
  shellCommandToken: () => json<{ token?: unknown }>("/api/shell/command-token", { cache: "no-store" }),
};
