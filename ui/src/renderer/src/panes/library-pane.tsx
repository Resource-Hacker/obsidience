/** Curated primitive catalog. Accepted Tools, Skills, Runbooks, and Tasks live
 *  here; proposed changes continue through the Review Queue. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw, Search } from "lucide-react";
import {
  knowledgeRoleForAgent,
  paintKnowledgeRoleIcon,
} from "@/components/themes/jarvis/knowledge-role-icons";
import { api, openReader, type GraphNode, type TaskRow } from "@/lib/api";

const SHELVES = ["tool", "skill", "runbook", "task"] as const;
type Shelf = (typeof SHELVES)[number];

const SHELF_LABELS: Record<Shelf, string> = {
  tool: "Tools",
  skill: "Skills",
  runbook: "Runbooks",
  task: "Tasks",
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

  const refresh = useCallback(() => {
    Promise.all([api.graph(), api.tasks(), api.reviews()]).then(([graph, taskRows, reviews]) => {
      setNodes(graph.nodes.filter((node) => SHELVES.includes(node.kind as Shelf)));
      setTasks(taskRows);
      setReviewCount(reviews.length);
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 10_000);
    return () => clearInterval(timer);
  }, [refresh]);

  const counts = useMemo(() => Object.fromEntries(SHELVES.map((kind) => [
    kind,
    nodes.filter((node) => node.kind === kind).length,
  ])) as Record<Shelf, number>, [nodes]);

  const taskTree = useMemo(() => {
    const byRef = new Map(tasks.map((task) => [task.ref, task]));
    const byName = new Map(tasks.map((task) => [task.ref.split("/").pop()?.toLowerCase(), task]));
    const children = new Map<string, TaskRow[]>();
    const childRefs = new Set<string>();
    const resolve = (raw: string) => {
      const ref = cleanLink(raw);
      return byRef.get(ref) ?? byName.get(ref.split("/").pop()?.toLowerCase());
    };
    for (const task of tasks) {
      const rows = (task.subtask_refs ?? []).flatMap((raw) => {
        const child = resolve(raw);
        return child ? [child] : [];
      });
      children.set(task.ref, rows);
      rows.forEach((child) => childRefs.add(child.ref));
    }
    const roots = tasks.filter((task) => !childRefs.has(task.ref));
    return { children, roots: roots.length ? roots : tasks };
  }, [tasks]);

  useEffect(() => {
    setExpanded(new Set(taskTree.roots.filter((task) => task.subtasks > 0).map((task) => task.ref)));
  }, [taskTree.roots]);

  const needle = query.trim().toLowerCase();
  const shelfNodes = useMemo(() => nodes
    .filter((node) => node.kind === shelf)
    .filter((node) => !needle || `${node.title} ${node.id} ${(node.tags ?? []).join(" ")}`.toLowerCase().includes(needle))
    .sort((left, right) => left.title.localeCompare(right.title)), [needle, nodes, shelf]);

  const visibleTasks = useMemo(() => {
    const rows: Array<{ task: TaskRow; depth: number }> = [];
    const seen = new Set<string>();
    const matches = (task: TaskRow) => !needle || `${task.title} ${task.ref}`.toLowerCase().includes(needle);
    const branchMatches = (task: TaskRow): boolean => matches(task) ||
      (taskTree.children.get(task.ref) ?? []).some(branchMatches);
    const add = (task: TaskRow, depth: number) => {
      if (seen.has(task.ref) || !branchMatches(task)) return;
      seen.add(task.ref);
      rows.push({ task, depth });
      if (!needle && !expanded.has(task.ref)) return;
      for (const child of taskTree.children.get(task.ref) ?? []) add(child, depth + 1);
    };
    taskTree.roots.forEach((task) => add(task, 0));
    return rows;
  }, [expanded, needle, taskTree]);

  function toggleTask(ref: string) {
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
            {nodes.length} accepted · {reviewCount} awaiting curation
          </p>
        </div>
        <button onClick={refresh} title="Refresh library" className="text-emerald-300/50 hover:text-emerald-100">
          <RefreshCw size={12} />
        </button>
      </div>

      <div className="grid shrink-0 grid-cols-4 border-b border-emerald-300/10">
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
        {shelf === "task" ? visibleTasks.map(({ task, depth }) => {
          const children = taskTree.children.get(task.ref) ?? [];
          const hasChildren = children.length > 0;
          return (
            <div key={task.ref} className="flex items-start border-b border-emerald-300/[0.07] px-2 py-1.5 hover:bg-emerald-300/[0.04]"
              style={{ paddingLeft: 8 + depth * 17 }}>
              <button onClick={() => hasChildren && toggleTask(task.ref)} disabled={!hasChildren}
                className="mr-1 mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-emerald-300/45 disabled:text-emerald-300/10">
                {hasChildren ? (expanded.has(task.ref) ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : <span className="text-[8px]">·</span>}
              </button>
              <button onClick={() => openReader(task.ref)} className="min-w-0 flex-1 text-left">
                <span className={`block truncate font-mono text-[11px] hover:text-emerald-200 ${hasChildren ? "font-semibold uppercase tracking-[0.08em] text-emerald-50" : "text-emerald-100/80"}`}>
                  {task.title}
                </span>
                <span className="flex gap-2 font-mono text-[8px] text-emerald-200/35">
                  {hasChildren ? <span>{children.length} subtasks</span> : <span>{task.status}</span>}
                  {task.schedule ? <span className="truncate">scheduled {task.schedule}</span> : null}
                </span>
              </button>
            </div>
          );
        }) : shelfNodes.map((node) => (
          <button key={node.id} onClick={() => openReader(node.id)}
            className="block w-full border-b border-emerald-300/[0.07] px-3 py-2 text-left hover:bg-emerald-300/[0.04]">
            <span className="block truncate font-mono text-[11px] text-emerald-100/85 hover:text-emerald-100">{node.title}</span>
            <span className="block truncate font-mono text-[8px] text-emerald-200/30">{node.id}</span>
          </button>
        ))}
        {(shelf === "task" ? visibleTasks.length === 0 : shelfNodes.length === 0) ? (
          <p className="p-4 font-mono text-[10px] text-emerald-200/35">No matching {SHELF_LABELS[shelf].toLowerCase()}.</p>
        ) : null}
      </div>
    </div>
  );
}
