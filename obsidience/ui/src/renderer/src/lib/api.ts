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

export const api = {
  graph: () => json<GraphSnapshot>("/api/graph", { cache: "no-store" }),
};

let readerSelection: string | null = null;
let readerGraphId = "";

export function openReader(ref: string, graphId = ""): void {
  readerSelection = ref;
  readerGraphId = graphId;
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

export function announceKnowledgeActivity(activity: KnowledgeActivity): void {
  window.dispatchEvent(new CustomEvent("obsidience:knowledge-activity", { detail: activity }));
}

export function onKnowledgeActivity(handler: (activity: KnowledgeActivity) => void): () => void {
  const fn = (event: Event) => handler((event as CustomEvent<KnowledgeActivity>).detail);
  window.addEventListener("obsidience:knowledge-activity", fn);
  return () => window.removeEventListener("obsidience:knowledge-activity", fn);
}
