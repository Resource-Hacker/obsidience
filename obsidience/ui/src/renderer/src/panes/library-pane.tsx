/** Passive capability catalog. Knowledge checkout and Task assignment belong to Reader. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw, Search } from "lucide-react";
import {
  knowledgeRoleForAgent,
  paintKnowledgeRoleIcon,
} from "@/components/themes/obsidience/knowledge-role-icons";
import {
  api,
  openReader,
  type GraphNode,
  type TaskRow,
} from "@/lib/api";

const SHELVES = ["tool", "task"] as const;
type Shelf = (typeof SHELVES)[number];

const SHELF_LABELS: Record<Shelf, string> = {
  tool: "Tools + Skills",
  task: "Tasks",
};

const CHILD_LABELS: Record<Shelf, string> = {
  tool: "subtools",
  task: "subtasks",
};

function cleanLink(value: string): string {
  return value.trim().replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0];
}

function LibraryGlyph() {
  const holder = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const element = holder.current;
    if (!element) return;
    const canvas = paintKnowledgeRoleIcon(knowledgeRoleForAgent("library"), 64);
    canvas.style.width = "24px";
    canvas.style.height = "24px";
    element.replaceChildren(canvas);
  }, []);
  return <span ref={holder} className="block h-6 w-6 shrink-0" />;
}

export function LibraryPaneBody() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [reviewCount, setReviewCount] = useState(0);
  const [shelf, setShelf] = useState<Shelf>("task");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const initializedShelves = useRef<Set<Shelf>>(new Set());
  const refresh = useCallback(() => {
    Promise.all([api.graph(), api.tasks(), api.reviews()]).then(([graph, taskRows, reviews]) => {
      const members = new Set(graph.navigation.groups.find((group) => group.id === "library")?.article_refs ?? []);
      setNodes(graph.nodes.filter((node) =>
        members.has(node.id) && (SHELVES.includes(node.kind as Shelf) || node.tags?.includes("task-taxonomy"))));
      setTasks(taskRows);
      setReviewCount(reviews.length);
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const isAcceptedArticle = (node: GraphNode) => !node.synthetic;
  const counts = useMemo(() => Object.fromEntries(SHELVES.map((kind) => [
    kind,
    nodes.filter((node) => node.kind === kind && isAcceptedArticle(node)).length,
  ])) as Record<Shelf, number>, [nodes]);
  const acceptedCount = useMemo(() => nodes.filter(isAcceptedArticle).length, [nodes]);

  const taskByRef = useMemo(() => new Map(tasks.map((task) => [task.ref, task])), [tasks]);
  const shelfNodes = useMemo(() => nodes
    .filter((node) => node.kind === shelf ||
      (shelf === "task" && node.tags?.includes("task-taxonomy")))
    .sort((left, right) => (left.order ?? Number.MAX_SAFE_INTEGER) - (right.order ?? Number.MAX_SAFE_INTEGER)
      || left.title.localeCompare(right.title)), [nodes, shelf]);

  const hierarchy = useMemo(() => {
    const byRef = new Map(shelfNodes.map((node) => [node.id, node]));
    const children = new Map<string, GraphNode[]>();
    const childRefs = new Set<string>();
    const parentOf = new Map<string, string>();
    const resolve = (raw: string) => {
      const ref = cleanLink(raw);
      return byRef.get(ref);
    };
    for (const node of shelfNodes) {
      const rows = (node.children ?? []).flatMap((raw) => {
        const child = resolve(raw);
        if (!child || child.id === node.id || parentOf.has(child.id)) return [];
        let cursor = node.id;
        while (parentOf.has(cursor)) {
          cursor = parentOf.get(cursor) as string;
          if (cursor === child.id) return [];
        }
        parentOf.set(child.id, node.id);
        childRefs.add(child.id);
        return [child];
      });
      children.set(node.id, rows);
    }
    const roots = shelfNodes.filter((node) => !childRefs.has(node.id));
    return { children, parentOf, roots: roots.length ? roots : shelfNodes };
  }, [shelfNodes]);

  useEffect(() => {
    if (initializedShelves.current.has(shelf) || hierarchy.roots.length === 0) return;
    initializedShelves.current.add(shelf);
    setExpanded((current) => new Set([
      ...current,
      ...hierarchy.roots.filter((node) => (hierarchy.children.get(node.id) ?? []).length > 0)
        .map((node) => node.id),
    ]));
  }, [hierarchy, shelf]);

  const needle = query.trim().toLowerCase();
  const visibleNodes = useMemo(() => {
    const rows: Array<{ node: GraphNode; depth: number }> = [];
    const seen = new Set<string>();
    const matchCache = new Map<string, boolean>();
    const matches = (node: GraphNode) => !needle ||
      `${node.title} ${node.id} ${(node.tags ?? []).join(" ")}`.toLowerCase().includes(needle);
    const branchMatches = (node: GraphNode): boolean => {
      const cached = matchCache.get(node.id);
      if (cached !== undefined) return cached;
      matchCache.set(node.id, false);
      const result = matches(node) || (hierarchy.children.get(node.id) ?? []).some(branchMatches);
      matchCache.set(node.id, result);
      return result;
    };
    const add = (node: GraphNode, depth: number) => {
      if (seen.has(node.id) || !branchMatches(node)) return;
      seen.add(node.id);
      rows.push({ node, depth });
      if (!needle && !expanded.has(node.id)) return;
      for (const child of hierarchy.children.get(node.id) ?? []) add(child, depth + 1);
    };
    hierarchy.roots.forEach((node) => add(node, 0));
    return rows;
  }, [expanded, hierarchy, needle]);

  function toggleNode(ref: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(ref)) next.delete(ref); else next.add(ref);
      return next;
    });
  }

  return (
    <div className="flex h-full flex-col bg-[#02080e]/70">
      <div className="flex shrink-0 items-center gap-2 border-b border-emerald-300/15 px-3 py-2">
        <LibraryGlyph />
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-emerald-200">Curated Library</p>
          <p className="font-mono text-[8px] text-emerald-200/45">
            {acceptedCount} accepted · {reviewCount} awaiting curation
          </p>
        </div>
        <button onClick={refresh} title="Refresh library" className="text-emerald-300/50 hover:text-emerald-100">
          <RefreshCw size={12} />
        </button>
      </div>

      <div className="grid shrink-0 grid-cols-2 border-b border-emerald-300/10">
        {SHELVES.map((kind) => (
          <button key={kind} onClick={() => setShelf(kind)}
            className={`border-r border-emerald-300/10 px-1 py-2 font-mono text-[9px] uppercase tracking-[0.12em] last:border-r-0 ${
              shelf === kind ? "bg-emerald-300/10 text-emerald-100" : "text-emerald-200/45 hover:bg-emerald-300/5 hover:text-emerald-100"
            }`}>
            {SHELF_LABELS[kind]} <span className="opacity-55">{counts[kind]}</span>
          </button>
        ))}
      </div>

      <label className="mx-2 mt-2 flex shrink-0 items-center gap-1.5 rounded border border-emerald-300/15 bg-[#020a0c] px-2 py-1">
        <Search size={11} className="text-emerald-300/35" />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${SHELF_LABELS[shelf].toLowerCase()}`}
          className="min-w-0 flex-1 bg-transparent font-mono text-[10px] text-emerald-50 outline-none placeholder:text-emerald-200/25" />
      </label>

      <div className="mt-1 min-h-0 flex-1 overflow-y-auto">
        {visibleNodes.map(({ node, depth }) => {
          const task = taskByRef.get(node.id);
          const children = hierarchy.children.get(node.id) ?? [];
          const hasChildren = children.length > 0;
          const knowledge = node.kind === "knowledge";
          const displayTitle = hierarchy.parentOf.get(node.id)?.startsWith("@library/Tools/")
            ? node.title.split(".").pop() ?? node.title
            : node.title;
          return (
            <div key={node.id} className={`flex items-start border-b px-2 py-1.5 ${knowledge
              ? "border-emerald-300/15 bg-emerald-300/[0.035] hover:bg-emerald-300/[0.065]"
              : "border-emerald-300/[0.07] hover:bg-emerald-300/[0.04]"}`}
              style={{ paddingLeft: 8 + depth * 17 }}>
              <button onClick={() => hasChildren && toggleNode(node.id)} disabled={!hasChildren}
                className="mr-1 mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-emerald-300/45 disabled:text-emerald-300/10">
                {hasChildren ? (expanded.has(node.id) ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : <span className="text-[8px]">·</span>}
              </button>
              <button onClick={() => openReader(node.id, "library")} className="min-w-0 flex-1 text-left">
                <span className={`block truncate font-mono text-[11px] hover:text-emerald-200 ${knowledge
                  ? "font-semibold uppercase tracking-[0.14em] text-emerald-200/75"
                  : hasChildren ? "font-semibold uppercase tracking-[0.08em] text-emerald-50" : "text-emerald-100/80"}`}>
                  {displayTitle}
                </span>
                <span className="flex gap-2 font-mono text-[8px] text-emerald-200/35">
                  {knowledge
                    ? <span>knowledge · {children.length} tasks</span>
                    : hasChildren
                    ? <span>{children.length} {CHILD_LABELS[shelf]}</span>
                    : <span>{node.synthetic ? "article" : task?.status ?? node.id}</span>}
                  {task?.schedule ? <span className="truncate">scheduled {task.schedule}</span> : null}
                </span>
              </button>
              {shelf === "tool" ? (
                <button
                  type="button"
                  onClick={() => openReader(`@library/Skills/${node.title.replaceAll(".", "/")}`, "library")}
                  title={`Read the Skill paired with ${node.title}`}
                  className="mr-1 mt-0.5 shrink-0 rounded border border-violet-300/20 px-1.5 py-0.5 font-mono text-[7px] uppercase tracking-[0.08em] text-violet-200/60 hover:border-violet-200/45 hover:text-violet-100"
                >
                  Skill
                </button>
              ) : null}

            </div>
          );
        })}
        {visibleNodes.length === 0 ? (
          <p className="p-4 font-mono text-[10px] text-emerald-200/35">No matching {SHELF_LABELS[shelf].toLowerCase()}.</p>
        ) : null}
      </div>
    </div>
  );
}
