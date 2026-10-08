/** Ephemeral projections of owner events; never an inference or execution source. */
export interface GraphOperation {
  id: string;
  kind: "context" | "read" | "search" | "list" | "tool" | "edit" | "review";
  status: "running" | "returned" | "completed" | "pending" | "approved" | "rejected" | "failed" | "interrupted";
  label: string;
  refs: string[];
  graph_id: string;
  run_id: string;
  started_at: number;
  at: number;
  omitted_refs: number;
  refresh?: boolean;
  /** Zero holds the actual result through its run and queued/playing speech. */
  expires_at?: number;
}

export interface GraphActivityAccent { color: string; mode: number }
export const ACTIVITY_LINGER_MS = 6_000;

export function operationDeadline(entry: GraphOperation): number {
  return Number.isFinite(entry.expires_at) ? entry.expires_at!
    : entry.status === "running" ? 0 : entry.at + ACTIVITY_LINGER_MS;
}

export function currentOperations(entries: GraphOperation[], now = Date.now()): GraphOperation[] {
  const latest = new Map<string, GraphOperation>();
  for (const entry of entries) {
    if (!entry || typeof entry.id !== "string" || typeof entry.label !== "string"
      || !["context", "read", "search", "list", "tool", "edit", "review"].includes(entry.kind)
      || !["running", "returned", "completed", "pending", "approved", "rejected", "failed", "interrupted"].includes(entry.status)
      || !Array.isArray(entry.refs) || !entry.refs.every((ref) => typeof ref === "string")
      || !Number.isFinite(entry.at) || !Number.isFinite(entry.started_at)) continue;
    const previous = latest.get(entry.id);
    if (previous && (previous.at > entry.at || (previous.status !== "running" && entry.status === "running"))) continue;
    latest.set(entry.id, { ...entry, refs: entry.refs.slice(0, 128) });
  }
  // Apply expiry AFTER replacement: a release must remove the held version.
  const values = [...latest.values()].filter((entry) => !operationDeadline(entry)
    || now < operationDeadline(entry)).sort((a, b) => a.at - b.at);
  const running = values.filter((entry) => !operationDeadline(entry)).slice(-96);
  const room = 96 - running.length;
  const settled = room ? values.filter((entry) => operationDeadline(entry)).slice(-room) : [];
  return [...settled, ...running].sort((a, b) => a.at - b.at);
}

export function operationAccent(entry: GraphOperation): GraphActivityAccent | null {
  if (["rejected", "failed", "interrupted"].includes(entry.status)) return { color: "#fb7185", mode: 5 };
  if (entry.kind === "context") return null; // Preserve the existing packet palette.
  if (entry.status === "pending") return { color: "#fbbf24", mode: 3 };
  if (entry.status === "approved" || entry.kind === "edit") return { color: "#6ee7b7", mode: 4 };
  if (["read", "search", "list"].includes(entry.kind)) return { color: "#67e8f9", mode: 1 };
  return { color: "#c4b5fd", mode: 2 };
}

export function operationStatus(entry: GraphOperation): string {
  if (entry.status === "running") return "Active";
  if (entry.status === "returned") return entry.kind === "search" ? "Matches returned"
    : entry.kind === "list" ? "Titles listed"
    : entry.kind === "read" && (!entry.run_id || entry.refs.length > 1) ? "Read" : "Returned";
  return { completed: "Saved", pending: "Awaiting Review", approved: "Approved",
    rejected: "Rejected", failed: "Failed", interrupted: "Interrupted" }[entry.status];
}
