/** Curated shared-asset catalog. One paired Tool + Skill tab and Tasks live
 *  here; per-agent synthesized Runbooks stay on agent graphs. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw, Search } from "lucide-react";
import {
  knowledgeRoleForAgent,
  paintKnowledgeRoleIcon,
} from "@/components/themes/obsidience/knowledge-role-icons";
import {
  api,
  openReader,
  type CheckoutAgent,
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

const CHECKOUT_AGENTS: ReadonlyArray<{ id: CheckoutAgent; label: string }> = [
  { id: "executive", label: "Executive" },
  { id: "guardian", label: "Guardian" },
  { id: "curator", label: "Curator" },
  { id: "researcher", label: "Researcher" },
];

const CHECKED_STYLE: Record<CheckoutAgent, string> = {
  executive: "border-cyan-300/70 bg-cyan-300/15 shadow-[0_0_9px_rgba(103,232,249,0.45)]",
  guardian: "border-blue-400/70 bg-blue-400/15 shadow-[0_0_9px_rgba(96,165,250,0.45)]",
  curator: "border-amber-400/70 bg-amber-400/15 shadow-[0_0_9px_rgba(251,191,36,0.45)]",
  researcher: "border-purple-400/70 bg-purple-400/15 shadow-[0_0_9px_rgba(192,132,252,0.45)]",
};

const UNCHECKED_STYLE: Record<CheckoutAgent, string> = {
  executive: "border-cyan-300/15 hover:border-cyan-300/40",
  guardian: "border-blue-400/15 hover:border-blue-400/40",
  curator: "border-amber-400/15 hover:border-amber-400/40",
  researcher: "border-purple-400/15 hover:border-purple-400/40",
};

function checkoutKey(ref: string, agent: CheckoutAgent): string {
  return `${ref}\u0000${agent}`;
}

function isCheckoutable(node: GraphNode): boolean {
  return node.kind === "task" || node.kind === "tool";
}

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

function CheckoutGlyph({ agent, size = 17 }: { agent: CheckoutAgent; size?: number }) {
  const holder = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const element = holder.current;
    if (!element) return;
    const canvas = paintKnowledgeRoleIcon(knowledgeRoleForAgent(agent), Math.max(48, size * 3));
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    element.replaceChildren(canvas);
  }, [agent, size]);
  return <span ref={holder} className="block shrink-0" style={{ width: size, height: size }} />;
}

function CheckoutControls({
  itemRef,
  selected,
  busy,
  onToggle,
}: {
  itemRef: string;
  selected: Set<string>;
  busy: Set<string>;
  onToggle: (ref: string, agent: CheckoutAgent) => void;
}) {
  return (
    <div className="ml-2 flex shrink-0 items-center gap-1" aria-label="Agent checkouts">
      {CHECKOUT_AGENTS.map(({ id, label }) => {
        const key = checkoutKey(itemRef, id);
        const checked = selected.has(key);
        return (
          <button key={id} type="button" aria-pressed={checked}
            disabled={busy.has(key)}
            title={`${checked ? "Return from" : "Check out to"} ${label}`}
            onClick={(event) => { event.stopPropagation(); onToggle(itemRef, id); }}
            className={`flex h-6 w-6 items-center justify-center rounded border transition-all disabled:opacity-35 ${
              checked ? CHECKED_STYLE[id] : `${UNCHECKED_STYLE[id]} bg-[#020a0c]/70 opacity-55 hover:opacity-100`
            }`}>
            <CheckoutGlyph agent={id} />
          </button>
        );
      })}
    </div>
  );
}

export function LibraryPaneBody() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [tasks, setTasks] = useState<TaskRow[]>([]);
  const [reviewCount, setReviewCount] = useState(0);
  const [shelf, setShelf] = useState<Shelf>("task");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const initializedShelves = useRef<Set<Shelf>>(new Set());
  const [checkouts, setCheckouts] = useState<Set<string>>(new Set());
  const [busyCheckouts, setBusyCheckouts] = useState<Set<string>>(new Set());
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const [checkoutNotice, setCheckoutNotice] = useState<string | null>(null);

  const refresh = useCallback(() => {
    Promise.all([api.graph(), api.tasks(), api.reviews(), api.checkouts()]).then(([graph, taskRows, reviews, checkoutSnapshot]) => {
      setNodes(graph.nodes.filter((node) =>
        SHELVES.includes(node.kind as Shelf) || node.tags?.includes("task-taxonomy")));
      setTasks(taskRows);
      setReviewCount(reviews.length);
      setCheckouts(new Set(checkoutSnapshot.assignments.map((assignment) => checkoutKey(assignment.ref, assignment.agent))));
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
    const byName = new Map(shelfNodes.map((node) => [node.id.split("/").pop()?.toLowerCase(), node]));
    const children = new Map<string, GraphNode[]>();
    const childRefs = new Set<string>();
    const parentOf = new Map<string, string>();
    const resolve = (raw: string) => {
      const ref = cleanLink(raw);
      return byRef.get(ref) ?? byName.get(ref.split("/").pop()?.toLowerCase());
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

  async function toggleCheckout(ref: string, agent: CheckoutAgent) {
    const key = checkoutKey(ref, agent);
    if (busyCheckouts.has(key)) return;
    const checkedOut = !checkouts.has(key);
    setCheckoutError(null);
    setCheckoutNotice(null);
    setBusyCheckouts((current) => new Set(current).add(key));
    setCheckouts((current) => {
      const next = new Set(current);
      if (checkedOut) next.add(key); else next.delete(key);
      return next;
    });
    try {
      const result = await api.setCheckout(ref, agent, checkedOut);
      const label = CHECKOUT_AGENTS.find((candidate) => candidate.id === agent)?.label ?? agent;
      if (result.activation_error) {
        setCheckoutError(`Checkout saved for ${label}, but ${result.activation_error}`);
      } else if (!result.checkout_changed) {
        setCheckoutNotice(`${label} already had this item checked out.`);
      } else if (!checkedOut) {
        setCheckoutNotice(`Returned from ${label}.`);
      } else if (result.activation_state === "queued") {
        setCheckoutNotice(`Checked out to ${label}. Runbook generation is queued at position ${result.queue_position}.`);
      } else if (result.activation_state === "started") {
        setCheckoutNotice(`Checked out to ${label}. Runbook generation started.`);
      } else {
        setCheckoutNotice(`Checked out to ${label}.`);
      }
      refresh();
      window.dispatchEvent(new Event("obsidience:graph-refresh"));
    } catch (error) {
      setCheckouts((current) => {
        const next = new Set(current);
        if (checkedOut) next.delete(key); else next.add(key);
        return next;
      });
      setCheckoutError(String(error).slice(0, 180));
    } finally {
      setBusyCheckouts((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
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

      <div className="mx-2 mt-1.5 flex shrink-0 items-center justify-end gap-2 border-b border-emerald-300/10 pb-1.5">
        <span className="mr-auto font-mono text-[8px] uppercase tracking-[0.14em] text-emerald-200/30">Checkout</span>
        {CHECKOUT_AGENTS.map(({ id, label }) => (
          <span key={id} className="flex items-center gap-0.5 font-mono text-[7px] uppercase text-emerald-100/45" title={label}>
            <CheckoutGlyph agent={id} size={13} /> {label.slice(0, 3)}
          </span>
        ))}
      </div>
      {checkoutError ? <p className="shrink-0 px-3 py-1 font-mono text-[9px] text-rose-300">{checkoutError}</p> : null}
      {checkoutNotice ? <p className="shrink-0 px-3 py-1 font-mono text-[9px] text-emerald-200/75">{checkoutNotice}</p> : null}

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
              <button onClick={() => openReader(node.id)} className="min-w-0 flex-1 text-left">
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
                  onClick={() => openReader(`@library/Skills/${node.title.replaceAll(".", "/")}`)}
                  title={`Read the Skill paired with ${node.title}`}
                  className="mr-1 mt-0.5 shrink-0 rounded border border-violet-300/20 px-1.5 py-0.5 font-mono text-[7px] uppercase tracking-[0.08em] text-violet-200/60 hover:border-violet-200/45 hover:text-violet-100"
                >
                  Skill
                </button>
              ) : null}
              {isCheckoutable(node) ? (
                <CheckoutControls itemRef={node.id}
                  selected={checkouts} busy={busyCheckouts} onToggle={toggleCheckout} />
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
