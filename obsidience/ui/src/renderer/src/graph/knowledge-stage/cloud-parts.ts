/** What every Knowledge-stage cloud of one snapshot is built from: the Library
 *  primitive kinds and their authored hierarchy, the Article endpoints of links,
 *  and the tables each cloud fills (link-review scope, label titles). */

import type { GraphLink, GraphNode } from "@/lib/api";

export const PRIMITIVE_FOLDER_BY_KIND: Record<string, string> = {
  tool: "Tools", skill: "Skills", runbook: "Runbooks", task: "Tasks",
};
const PRIMITIVE_KINDS = new Set(["tool", "skill", "runbook", "task"]);

export function primitiveKindOf(node: GraphNode): string | null {
  return node.tags?.includes("task-taxonomy") ? "task"
    : PRIMITIVE_KINDS.has(node.kind) ? node.kind : null;
}

/** Parent and index Articles retain semantic links; Brain peers are navigation only. */
export function isArticleEndpoint(node: GraphNode): boolean {
  return node.kind !== "agent";
}

/** Each member's parent by the authored child refs of a member of its own
 *  primitive kind; the first parent wins and a cycle is never closed. */
export function hierarchyParents(members: GraphNode[], displayAliases: ReadonlyMap<string, string>): Map<string, string> {
  const subRef = (raw: string, pool: Set<string>): string | null => {
    const clean = raw.trim().replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0].split("#")[0];
    const displayed = displayAliases.get(clean) ?? clean;
    return pool.has(displayed) ? displayed : null;
  };
  const childRefsOf = (node: GraphNode): string[] => node.children ?? [];
  const pool = new Set(members.map((node) => node.id));
  const byId = new Map(members.map((node) => [node.id, node]));
  const parentOf = new Map<string, string>();
  for (const parent of members) {
    for (const raw of childRefsOf(parent)) {
      const child = subRef(raw, pool);
      if (!child || child === parent.id || parentOf.has(child) ||
          primitiveKindOf(byId.get(child) as GraphNode) !== primitiveKindOf(parent)) continue;
      let cursor = parent.id;
      let cyclic = false;
      while (parentOf.has(cursor)) {
        cursor = parentOf.get(cursor) as string;
        if (cursor === child) { cyclic = true; break; }
      }
      if (!cyclic) parentOf.set(child, parent.id);
    }
  }
  return parentOf;
}

/** One cloud's accepted links and scope, against which Review previews spring in. */
export interface ReviewScope {
  articleIds: Set<string>; agentRef?: string; scopeRefs: Set<string>; links: GraphLink[];
  edgeColorEnd: (id: string) => string;
}

export interface CloudInputs {
  all: GraphNode[];
  displayAliases: ReadonlyMap<string, string>;
  linkPairs: GraphLink[];
  autoCurated: ReadonlySet<string>;
  /** Filled by each cloud: its link-review scope by graph id, and label titles. */
  reviewScopes: Map<string, ReviewScope>;
  titles: Map<string, string>;
}
