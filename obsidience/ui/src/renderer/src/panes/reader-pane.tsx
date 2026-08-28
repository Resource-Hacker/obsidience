/** Reader: knowledge explorer, article workspace, and source blob explorer. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AppWindow,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Computer,
  Cpu,
  Database,
  ExternalLink,
  FileText,
  Folder,
  FolderOpen,
  GripVertical,
  HardDrive,
  Network,
  Package,
  PanelLeft,
  PanelRight,
  Pencil,
  Play,
  RefreshCw,
  Save,
  Server,
  Usb,
  X,
} from "lucide-react";
import { ArticleMarkdown } from "@/components/themes/obsidience/workspace/article-markdown";
import {
  knowledgeRoleForAgent,
  knowledgeRoleTint,
  paintKnowledgeRoleIcon,
  type KnowledgeRole,
} from "@/components/themes/obsidience/knowledge-role-icons";
import {
  api,
  onOpenSourceFile,
  onOpenReader,
  openTasks,
  openReader,
  openSourceFile,
  type GraphNode,
  type GraphNavigation,
  type GraphNavigationGroup,
  type ModelBenchmark,
  type ModelOption,
  type ModelPreference,
  type NoteDoc,
  type ReasoningEffort,
  type CheckoutAgent,
  type SourceDoc,
  type SourceFile,
  type SourceIssue,
  type StorageFilesystem,
  type StorageLocation,
  type StorageState,
  type TaskRow,
  type VaultFile,
  type WikiAction,
} from "@/lib/api";
import {
  type ReaderDockLayout,
  type ReaderDockPosition,
  type ReaderModuleId,
  type ReaderModulePlacement,
} from "@/lib/reader-docking";

interface TaskDraft {
  title: string;
  body: string;
  schedule: string;
  assignee: string;
  runbook: string;
  reasoning_effort: ReasoningEffort;
  model: ModelPreference;
}

interface ArticleDraft { title: string; body: string }

interface ModelDraft {
  allowed_devices: string[];
  context_tokens: number;
  max_output_tokens: number;
  gpu_memory_utilization: number;
  max_num_seqs: number;
}

const RUNTIME_MODEL_PREFIX = "@runtime/model/";
const GPU_LABELS: Record<string, string> = {
  rtx4080: "RTX 4080 SUPER",
  rtx4000: "RTX 4000 Ada",
};

const SOURCE_CHECKOUT_AGENTS: ReadonlyArray<{ id: CheckoutAgent; label: string }> = [
  { id: "executive", label: "Executive" },
  { id: "guardian", label: "Guardian" },
  { id: "curator", label: "Curator" },
  { id: "researcher", label: "Researcher" },
];

const SOURCE_CHECKED_STYLE: Record<CheckoutAgent, string> = {
  executive: "border-cyan-300/70 bg-cyan-300/15 shadow-[0_0_8px_rgba(103,232,249,0.4)]",
  guardian: "border-blue-400/70 bg-blue-400/15 shadow-[0_0_8px_rgba(96,165,250,0.4)]",
  curator: "border-amber-400/70 bg-amber-400/15 shadow-[0_0_8px_rgba(251,191,36,0.4)]",
  researcher: "border-purple-400/70 bg-purple-400/15 shadow-[0_0_8px_rgba(192,132,252,0.4)]",
};

export interface ReaderDockingProps {
  layout: ReaderDockLayout;
  dragging: ReaderModuleId | null;
  onCollapse: (id: ReaderModuleId) => void;
  onExpand: (id: ReaderModuleId) => void;
  onFloat: (id: ReaderModuleId) => void;
  onDock: (
    id: ReaderModuleId,
    side: Exclude<ReaderModulePlacement, "floating">,
    position: ReaderDockPosition,
  ) => void;
  onDragStart: (id: ReaderModuleId) => void;
  onDragEnd: () => void;
}

interface ReaderModuleChrome {
  id: ReaderModuleId;
  docking: ReaderDockingProps;
}

interface ExplorerNode {
  key: string;
  name: string;
  path: string;
  folder: boolean;
  ref?: string;
  kind?: string;
  virtual?: boolean;
  children: ExplorerNode[];
}

type ExplorerGroupId = "executive" | "guardian" | "curator" | "researcher" | "library";

interface ExplorerGroup {
  id: ExplorerGroupId;
  label: string;
  subtitle: string;
  role: KnowledgeRole;
  rootRef: string;
  tree: ExplorerNode[];
  count: number;
}

interface ExplorerMenu {
  node: ExplorerNode;
  x: number;
  y: number;
  value: string;
  error?: string;
}

const PROTECTED_TREE_ROOTS = new Set([
  "Agents", "Tools", "Skills", "Tasks", "Runbooks", "raw", "_staging",
]);

const FIELD_CLASS =
  "w-full rounded border border-cyan-300/20 bg-[#020a12] px-2 py-1.5 font-mono text-[10px] text-cyan-50 outline-none focus:border-cyan-300/50 disabled:opacity-45";

const TASK_STATUS_STYLE: Record<string, string> = {
  pending: "border-cyan-300/40 text-cyan-200",
  running: "animate-pulse border-emerald-300/60 bg-emerald-300/5 text-emerald-200",
  review: "border-amber-300/50 text-amber-200",
  completed: "border-emerald-300/25 text-emerald-300/70",
  failed: "border-rose-300/50 text-rose-300",
  blocked: "border-rose-300/40 text-rose-200",
  draft: "border-cyan-300/20 text-cyan-200/50",
};

const CHILD_LABELS: Record<string, string> = {
  tool: "Subtools",
  skill: "Subskills",
  runbook: "Subrunbooks",
  task: "Subtasks",
};

function cleanLink(value: string): string {
  return value.trim().replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0];
}

function resolveOption(value: string, options: Array<{ id: string }>): string {
  const clean = cleanLink(value);
  const leaf = clean.split("/").pop()?.toLowerCase();
  return options.find((option) =>
    option.id === clean || option.id.split("/").pop()?.toLowerCase() === leaf)?.id ?? clean;
}

function draftFor(
  note: NoteDoc,
  task: TaskRow,
  agents: Array<{ id: string }>,
  runbooks: Array<{ id: string }>,
): TaskDraft {
  return {
    title: note.title,
    body: note.body,
    schedule: task.schedule ?? "",
    assignee: resolveOption(task.assignee, agents),
    runbook: resolveOption(task.runbook, runbooks),
    reasoning_effort: task.reasoning_effort,
    model: task.model,
  };
}

function parentForTask(taskRef: string, tasks: TaskRow[]): TaskRow | null {
  return tasks.find((candidate) =>
    (candidate.subtask_refs ?? []).some((ref) => cleanLink(ref) === taskRef)) ?? null;
}

function formatNextRun(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString([], {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function triggerFor(task: TaskRow, parent: TaskRow | null): {
  kind: "Event" | "Schedule" | "Parent task" | "Manual";
  detail: string;
  nextRun: string | null;
} {
  if (task.triggers.length) {
    return {
      kind: "Event",
      detail: `On event · ${task.triggers.join(" · ")}${task.schedule ? ` · schedule · ${task.schedule}` : ""}`,
      nextRun: task.next_run ? `Next scheduled run: ${formatNextRun(task.next_run)}` : null,
    };
  }
  if (parent) {
    return {
      kind: "Parent task",
      detail: `${parent.title} dispatches this subtask in sequence.`,
      nextRun: parent.next_run ? `Next parent run: ${formatNextRun(parent.next_run)}` : null,
    };
  }
  if (task.schedule) {
    return {
      kind: "Schedule",
      detail: task.schedule,
      nextRun: task.next_run ? `Next run: ${formatNextRun(task.next_run)}` : null,
    };
  }
  return {
    kind: "Manual",
    detail: "Runs only when Run now is selected.",
    nextRun: null,
  };
}

function ExplorerRoleGlyph({ role, size = 32 }: { role: KnowledgeRole; size?: number }) {
  const holder = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const element = holder.current;
    if (!element) return;
    const canvas = paintKnowledgeRoleIcon(role, Math.max(64, size * 3));
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    element.replaceChildren(canvas);
  }, [role, size]);
  return <span ref={holder} className="block shrink-0" style={{ width: size, height: size }} />;
}

function SourceCheckoutGlyph({ agent }: { agent: CheckoutAgent }) {
  const holder = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const element = holder.current;
    if (!element) return;
    const canvas = paintKnowledgeRoleIcon(knowledgeRoleForAgent(agent), 48);
    canvas.style.width = "14px";
    canvas.style.height = "14px";
    element.replaceChildren(canvas);
  }, [agent]);
  return <span ref={holder} className="block h-3.5 w-3.5 shrink-0" />;
}

function sourceCheckoutKey(tree: string, agent: CheckoutAgent): string {
  return `${tree}\u0000${agent}`;
}

function fileGroup(path: string): ExplorerGroupId {
  if (path.startsWith("Agents/Heimdall/")) return "guardian";
  if (path.startsWith("Agents/Alexandria/")) return "curator";
  if (path.startsWith("Agents/Darwin/")) return "researcher";
  if (path.startsWith("Sources/")) return "researcher";
  if (/^(Tools|Skills|Tasks)\//.test(path)) return "library";
  return "executive";
}

function folderArticleRef(path: string, group: ExplorerGroupId): string {
  if (group === "library" && ["Tools", "Skills", "Tasks"].includes(path)) {
    return `@library/${path}`;
  }
  return `@branch/${path}`;
}

function buildFileTree(files: VaultFile[], group: ExplorerGroupId, stripPrefix = ""): ExplorerNode[] {
  const roots: ExplorerNode[] = [];
  const base = stripPrefix.replace(/\/$/, "");
  const ensureFolder = (siblings: ExplorerNode[], name: string, path: string) => {
    const key = `folder:${path}`;
    let folder = siblings.find((node) => node.key === key);
    if (!folder) {
      folder = {
        key,
        name,
        path,
        folder: true,
        ref: folderArticleRef(path, group),
        kind: "knowledge",
        children: [],
      };
      siblings.push(folder);
    }
    return folder;
  };
  for (const file of files) {
    const displayPath = base && file.path.startsWith(`${base}/`)
      ? file.path.slice(base.length + 1)
      : file.path;
    const parts = displayPath.replace(/\.md$/i, "").split("/").filter(Boolean);
    const basename = parts.pop() ?? file.title;
    let siblings = roots;
    let prefix = "";
    let parent: ExplorerNode | null = null;
    for (const part of parts) {
      prefix = prefix ? `${prefix}/${part}` : part;
      parent = ensureFolder(siblings, part, base ? `${base}/${prefix}` : prefix);
      siblings = parent.children;
    }
    if (["index", "readme"].includes(basename.toLowerCase()) && parent) {
      parent.ref = file.ref;
      parent.kind = file.kind;
      parent.name = file.title;
      continue;
    }
    siblings.push({
      key: `file:${file.ref}`,
      name: file.title || basename,
      path: file.path,
      folder: false,
      ref: file.ref,
      kind: file.kind,
      children: [],
    });
  }
  const sort = (nodes: ExplorerNode[]) => {
    nodes.sort((left, right) => {
      const folderOrder = Number(right.folder) - Number(left.folder);
      return folderOrder || left.name.localeCompare(right.name);
    });
    nodes.forEach((node) => sort(node.children));
    return nodes;
  };
  return sort(roots);
}

function graphProjectionNode(
  ref: string,
  byId: Map<string, GraphNode>,
  namespace: string,
  visiting = new Set<string>(),
  allowed?: Set<string>,
): ExplorerNode | null {
  const node = byId.get(ref);
  if (!node || visiting.has(ref) || (allowed && !allowed.has(ref))) return null;
  const nextVisiting = new Set(visiting).add(ref);
  const children = (node.children ?? [])
    .map(cleanLink)
    .map((child) => graphProjectionNode(child, byId, namespace, nextVisiting, allowed))
    .filter((child): child is ExplorerNode => Boolean(child));
  return {
    key: `projection:${namespace}:${ref}`,
    name: node.title,
    path: `@projection/${namespace}/${ref}`,
    folder: children.length > 0,
    ref,
    kind: node.kind,
    virtual: true,
    children,
  };
}

function graphProjectionRoots(refs: string[], nodes: GraphNode[], namespace: string): ExplorerNode[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const parentByChild = new Map<string, string>();
  for (const node of nodes) {
    for (const child of node.children ?? []) parentByChild.set(cleanLink(child), node.id);
  }
  const roots = new Set(refs.map(cleanLink).filter((ref) => byId.has(ref)));
  const allowed = new Set(roots);
  const queue = [...roots];
  while (queue.length) {
    const ref = queue.shift() as string;
    const node = byId.get(ref);
    for (const child of node?.children ?? []) {
      const childRef = cleanLink(child);
      if (!allowed.has(childRef) && byId.get(childRef)?.kind === node?.kind) {
        allowed.add(childRef);
        queue.push(childRef);
      }
    }
  }
  for (const ref of [...allowed]) {
    let cursor = ref;
    let parent = parentByChild.get(cursor);
    while (parent && byId.get(parent)?.kind === byId.get(ref)?.kind) {
      allowed.add(parent);
      cursor = parent;
      parent = parentByChild.get(cursor);
    }
  }
  const projectedRoots = [...allowed].filter((ref) => {
    let parent = parentByChild.get(ref);
    while (parent) {
      if (allowed.has(parent)) return false;
      parent = parentByChild.get(parent);
    }
    return true;
  });
  return projectedRoots
    .map((ref) => graphProjectionNode(ref, byId, namespace, new Set(), allowed))
    .filter((node): node is ExplorerNode => Boolean(node));
}

function subjectExplorerNodes(group: GraphNavigationGroup, namespace: string): Map<string, ExplorerNode> {
  const subjects = new Map(group.subjects.map((subject) => [subject.id, {
    key: `${namespace}:${subject.id}`,
    name: subject.title,
    path: subject.id,
    folder: true,
    ref: subject.id,
    kind: "knowledge",
    virtual: true,
    children: [],
  } satisfies ExplorerNode]));
  for (const subject of group.subjects) {
    if (subject.parent_id) subjects.get(subject.parent_id)?.children.push(subjects.get(subject.id) as ExplorerNode);
  }
  return subjects;
}

function libraryProjection(nodes: GraphNode[], group: GraphNavigationGroup): ExplorerNode[] {
  return group.subjects.filter((subject) => !subject.parent_id).map((subject) => {
    const kind = subject.id === "@library/Tasks" ? "task" : "tool";
    const members = [...nodes.filter((node) => node.kind === kind ||
      (kind === "task" && node.tags?.includes("task-taxonomy")))].sort((left, right) =>
      (left.order ?? Number.MAX_SAFE_INTEGER) - (right.order ?? Number.MAX_SAFE_INTEGER)
      || left.title.localeCompare(right.title));
    const children = graphProjectionRoots(
      members.map((node) => node.id),
      nodes,
      `library:${kind}`,
    );
    return {
      key: `library-shelf:${subject.id}`,
      name: subject.title,
      path: subject.id,
      folder: children.length > 0,
      ref: subject.id,
      kind: "knowledge",
      virtual: true,
      children,
    };
  });
}

function agentProjection(group: GraphNavigationGroup, nodes: GraphNode[], files: VaultFile[]): ExplorerNode[] {
  const identityRef = group.root_ref;
  const agentName = identityRef.split("/")[1] ?? group.title;
  const identity = nodes.find((node) => node.id === identityRef);
  const subjects = subjectExplorerNodes(group, `agent-subject:${agentName}`);
  const subject = (key: string) => subjects.get(`@sat/${agentName}/${key}`);

  const checkoutFields = ["tools", "skills", "runbooks", "tasks"] as const;
  for (const field of checkoutFields) {
    const refs = [...(identity?.checkouts?.[field] ?? [])];
    if (field === "tasks") {
      refs.push(...nodes.filter((node) => node.kind === "task" &&
        String(node.assignee ?? "").includes(agentName)).map((node) => node.id));
    }
    subject(field)?.children.push(...graphProjectionRoots(refs, nodes, `${agentName}:${field}`));
  }

  const sourceRefs = new Set(identity?.source_scope_refs ?? []);
  subject("knowledge")?.children.push(...buildFileTree(
    files.filter((file) => sourceRefs.has(file.ref)),
    group.id as ExplorerGroupId,
  ));

  const otherAgents = nodes.filter((node) => node.kind === "agent" && node.id !== identityRef);
  subject("other-agents")?.children.push(...otherAgents.map((node) => ({
    key: `agent-peer:${agentName}:${node.id}`,
    name: node.title,
    path: `@projection/${agentName}/peers/${node.id}`,
    folder: false,
    ref: node.id,
    kind: node.kind,
    virtual: true,
    children: [],
  })));

  const localPrefix = `Agents/${agentName}/`;
  for (const node of nodes.filter((candidate) => candidate.id.startsWith(localPrefix) && candidate.id !== identityRef)) {
    const localPath = node.id.slice(localPrefix.length);
    const segment = localPath.split("/", 1)[0]
      .toLowerCase().replaceAll("_", "-").replaceAll(" ", "-");
    const subject = localPath.startsWith("Observations/Temporary Observations/")
      ? subjects.get(`@sat/${agentName}/temporary-observations`)
      : subjects.get(`@sat/${agentName}/${segment}`) ?? subjects.get(`@sat/${agentName}/observations`);
    const projected = graphProjectionNode(node.id, new Map(nodes.map((item) => [item.id, item])), `${agentName}:local`);
    if (subject && projected) subject.children.push(projected);
  }

  if (agentName === "Darwin") {
    const byId = new Map(nodes.map((node) => [node.id, node]));
    for (const node of nodes.filter((candidate) => candidate.id.startsWith("Sources/"))) {
      const basename = node.id.split("/").pop()?.toLowerCase();
      if (basename === "readme" || basename === "index") continue;
      const subject = subjects.get(`@sat/${agentName}/sources`);
      const projected = graphProjectionNode(node.id, byId, `${agentName}:sources`);
      if (subject && projected) subject.children.push(projected);
    }
  }

  return group.subjects
    .filter((row) => !row.parent_id)
    .map((row) => subjects.get(row.id) as ExplorerNode)
    .filter(Boolean);
}

function executiveProjection(files: VaultFile[], nodes: GraphNode[], group: GraphNavigationGroup): ExplorerNode[] {
  const identity = nodes.find((node) => node.id === group.root_ref);
  const subjects = subjectExplorerNodes(group, "executive-subject");
  const subject = (ref: string) => subjects.get(ref);

  const checkoutFields = ["tools", "skills", "runbooks", "tasks"] as const;
  for (const field of checkoutFields) {
    const refs = [...(identity?.checkouts?.[field] ?? [])];
    if (field === "tasks") {
      refs.push(...nodes.filter((node) => node.kind === "task" &&
        String(node.assignee ?? "").includes("Agents/Executive/Executive")).map((node) => node.id));
    }
    subject(`@branch/${field[0].toUpperCase()}${field.slice(1)}`)?.children.push(
      ...graphProjectionRoots(refs, nodes, `executive:${field}`),
    );
  }

  subject("@agent/Architecture")?.children.push(...buildFileTree(
    files.filter((file) => file.path.startsWith("Agents/Executive/Architecture/")),
    "executive",
    "Agents/Executive/Architecture",
  ));
  subject("@agent/Subagents")?.children.push(...buildFileTree(
    files.filter((file) => file.path.startsWith("Agents/Executive/Subagents/")),
    "executive",
    "Agents/Executive/Subagents",
  ));
  const byId = new Map(nodes.map((node) => [node.id, node]));
  subject("@agent/Subagents")?.children.push(...nodes
    .filter((node) => node.kind === "agent" && node.id.startsWith("Agents/")
      && node.id !== "Agents/Executive/Executive")
    .map((node) => graphProjectionNode(node.id, byId, "executive:subagents"))
    .filter((node): node is ExplorerNode => Boolean(node)));

  const temporaryPrefix = "Agents/Executive/Observations/Temporary Observations/";
  subject("@agent/Observations")?.children.push(...buildFileTree(
    files.filter((file) =>
      file.path.startsWith("Agents/Executive/Observations/") && !file.path.startsWith(temporaryPrefix)),
    "executive",
    "Agents/Executive/Observations",
  ));
  subject("@agent/Temporary Observations")?.children.push(...buildFileTree(
    files.filter((file) => file.path.startsWith(temporaryPrefix)),
    "executive",
    "Agents/Executive/Observations/Temporary Observations",
  ));

  const handledAgentPrefixes = [
    "Agents/Executive/Architecture/",
    "Agents/Executive/Subagents/",
    "Agents/Executive/Observations/",
  ];
  const worldKnowledge = buildFileTree(files.filter((file) =>
    fileGroup(file.path) === "executive" &&
    !file.path.startsWith("Agents/Executive/") &&
    !handledAgentPrefixes.some((prefix) => file.path.startsWith(prefix)) &&
    !file.path.startsWith("Runbooks/")), "executive");

  return [
    ...group.subjects.filter((row) => !row.parent_id)
      .map((row) => subjects.get(row.id) as ExplorerNode),
    ...worldKnowledge,
  ];
}

function treeRefCount(nodes: ExplorerNode[]): number {
  const refs = new Set<string>();
  const visit = (rows: ExplorerNode[]) => rows.forEach((node) => {
    if (node.ref && !node.ref.startsWith("@sat/")) refs.add(node.ref);
    visit(node.children);
  });
  visit(nodes);
  return refs.size;
}

function buildExplorerGroups(files: VaultFile[], graphNodes: GraphNode[], navigation: GraphNavigation): ExplorerGroup[] {
  return navigation.groups.map((group) => {
    const spec = {
      id: group.id as ExplorerGroupId,
      label: group.title,
      subtitle: group.subtitle,
      role: group.role as KnowledgeRole,
      rootRef: group.root_ref,
    };
    const tree = group.id === "library"
      ? libraryProjection(graphNodes, group)
      : group.id === "executive"
        ? executiveProjection(files, graphNodes, group)
        : agentProjection(group, graphNodes, files);
    return { ...spec, tree, count: treeRefCount(tree) };
  });
}

function explorerPathToRef(nodes: ExplorerNode[], ref: string): ExplorerNode[] | null {
  for (const node of nodes) {
    if (node.ref === ref) return [node];
    const childPath = explorerPathToRef(node.children, ref);
    if (childPath) return [node, ...childPath];
  }
  return null;
}

function filterTree(nodes: ExplorerNode[], query: string): ExplorerNode[] {
  if (!query) return nodes;
  const needle = query.toLowerCase();
  return nodes.flatMap((node) => {
    const children = filterTree(node.children, query);
    return node.name.toLowerCase().includes(needle) || children.length
      ? [{ ...node, children }]
      : [];
  });
}

function ReaderModuleControls({
  chrome,
  tint,
}: {
  chrome: ReaderModuleChrome;
  tint: "cyan" | "violet";
}) {
  const state = chrome.docking.layout[chrome.id];
  const base = tint === "cyan"
    ? "border-cyan-300/15 text-cyan-200/45 hover:border-cyan-300/40 hover:text-cyan-50"
    : "border-violet-300/15 text-violet-200/45 hover:border-violet-300/40 hover:text-violet-50";
  const button = `flex h-4 w-4 items-center justify-center rounded border ${base}`;
  return (
    <span className="flex items-center gap-1">
      {state.placement === "floating" ? (
        <>
          <button type="button" onClick={() => chrome.docking.onDock(chrome.id, "left", "bottom")}
            title="Dock left" aria-label={`Dock ${chrome.id} left`} className={button}>
            <PanelLeft size={9} />
          </button>
          <button type="button" onClick={() => chrome.docking.onDock(chrome.id, "right", "bottom")}
            title="Dock right" aria-label={`Dock ${chrome.id} right`} className={button}>
            <PanelRight size={9} />
          </button>
        </>
      ) : (
        <>
          <button type="button" onClick={() => chrome.docking.onFloat(chrome.id)}
            title="Detach as pane" aria-label={`Detach ${chrome.id} pane`} className={button}>
            <ExternalLink size={9} />
          </button>
          <button type="button" onClick={() => chrome.docking.onCollapse(chrome.id)}
            title={`Collapse ${chrome.id}`} aria-label={`Collapse ${chrome.id}`} className={button}>
            {state.placement === "left" ? <ChevronLeft size={10} /> : <ChevronRight size={10} />}
          </button>
        </>
      )}
    </span>
  );
}

function ReaderModuleDragHandle({
  chrome,
  children,
}: {
  chrome: ReaderModuleChrome;
  children: React.ReactNode;
}) {
  return (
    <span draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("application/x-obsidience-reader-module", chrome.id);
        chrome.docking.onDragStart(chrome.id);
      }}
      onDragEnd={(event) => {
        if (event.dataTransfer.dropEffect === "none" && chrome.docking.layout[chrome.id].placement !== "floating") {
          chrome.docking.onFloat(chrome.id);
        }
        chrome.docking.onDragEnd();
      }}
      title="Drag to dock, stack, or detach"
      className="flex cursor-grab items-center gap-1.5 active:cursor-grabbing">
      <GripVertical size={9} className="opacity-40" />
      {children}
    </span>
  );
}

function KnowledgeExplorer({
  selectedRef,
  chrome,
}: {
  selectedRef: string | null;
  chrome: ReaderModuleChrome;
}) {
  const [files, setFiles] = useState<VaultFile[]>([]);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [navigation, setNavigation] = useState<GraphNavigation>({ groups: [] });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<ExplorerGroupId>>(new Set(["executive"]));
  const [query, setQuery] = useState("");
  const [moving, setMoving] = useState(false);
  const [dragSource, setDragSource] = useState<ExplorerNode | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [menu, setMenu] = useState<ExplorerMenu | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState(false);
  const initialized = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const [nextFiles, graph] = await Promise.all([api.files(), api.graph()]);
      setFiles(nextFiles);
      setGraphNodes(graph.nodes);
      setNavigation(graph.navigation);
      return true;
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    let active = true;
    let retry: number | undefined;
    const loadExplorer = async () => {
      const loaded = await refresh();
      if (active && !loaded) retry = window.setTimeout(loadExplorer, 1_000);
    };
    const handleKnowledgeChange = () => { void refresh(); };
    void loadExplorer();
    window.addEventListener("obsidience:knowledge-changed", handleKnowledgeChange);
    return () => {
      active = false;
      if (retry !== undefined) window.clearTimeout(retry);
      window.removeEventListener("obsidience:knowledge-changed", handleKnowledgeChange);
    };
  }, [refresh]);
  const groups = useMemo(
    () => buildExplorerGroups(files, graphNodes, navigation),
    [files, graphNodes, navigation],
  );
  const visibleGroups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return groups;
    return groups.flatMap((group) => {
      const groupMatches = `${group.label} ${group.subtitle}`.toLowerCase().includes(needle);
      const tree = groupMatches ? group.tree : filterTree(group.tree, needle);
      return tree.length ? [{ ...group, tree }] : [];
    });
  }, [groups, query]);

  useEffect(() => {
    if (initialized.current || groups.length === 0 || groups.every((group) => group.tree.length === 0)) return;
    initialized.current = true;
    setExpanded(new Set(groups.flatMap((group) => group.tree.filter((node) => node.folder).map((node) => node.key))));
  }, [groups]);

  useEffect(() => {
    if (!selectedRef) return;
    const selected = files.find((file) => file.ref === selectedRef);
    let selectedGroup = selected ? fileGroup(selected.path) : null;
    if (selectedRef === "@vault") selectedGroup = "executive";
    if (selectedRef.startsWith("@branch/") || selectedRef.startsWith("@agent/")) selectedGroup = "executive";
    if (selectedRef === "@library" || selectedRef.startsWith("@library/")) selectedGroup = "library";
    for (const group of groups) {
      const agentName = group.rootRef.split("/")[1];
      if (selectedRef === group.rootRef || (agentName && selectedRef.startsWith(`@sat/${agentName}/`))) {
        selectedGroup = group.id;
      }
    }
    if (selectedGroup) {
      setExpandedGroups((current) => new Set(current).add(selectedGroup));
      const group = groups.find((candidate) => candidate.id === selectedGroup);
      const path = group ? explorerPathToRef(group.tree, selectedRef) : null;
      if (path) {
        setExpanded((current) => new Set([
          ...current,
          ...path.filter((node) => node.folder).map((node) => node.key),
        ]));
      }
    }
    if (!selected) return;
    const parts = selected.path.split("/").slice(0, -1);
    let prefix = "";
    setExpanded((current) => {
      const next = new Set(current);
      parts.forEach((part) => {
        prefix = prefix ? `${prefix}/${part}` : part;
        next.add(`folder:${prefix}`);
      });
      return next;
    });
  }, [files, groups, selectedRef]);

  const toggle = (key: string) => setExpanded((current) => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  const toggleGroup = (id: ExplorerGroupId) => setExpandedGroups((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const manageable = (node: ExplorerNode) => {
    if (node.virtual) return false;
    const first = node.path.split("/", 1)[0];
    return first !== "raw" && first !== "_staging" &&
      !(node.folder && !node.path.includes("/") && PROTECTED_TREE_ROOTS.has(node.path));
  };

  function movedSelection(refs: Record<string, string>) {
    if (selectedRef && refs[selectedRef]) openReader(refs[selectedRef]);
  }

  async function renameItem() {
    if (!menu || moving || !menu.value.trim()) return;
    const current = menu;
    const parent = current.node.path.includes("/")
      ? current.node.path.slice(0, current.node.path.lastIndexOf("/"))
      : "";
    setMoving(true);
    setActionNotice(null);
    setActionError(false);
    try {
      const result = await api.moveVaultItem(current.node.path, parent, current.value.trim());
      movedSelection(result.refs);
      setMenu(null);
      setActionNotice(`Renamed ${current.node.name} to ${current.value.trim()}.`);
      await refresh();
      window.dispatchEvent(new Event("obsidience:knowledge-changed"));
    } catch (cause) {
      setMenu({ ...current, error: String(cause) });
    } finally {
      setMoving(false);
    }
  }

  function canDrop(source: ExplorerNode | null, target: ExplorerNode) {
    if (!source || !target.folder || !manageable(source) || !manageable(target)) return false;
    if (source.path === target.path || target.path.startsWith(`${source.path}/`)) return false;
    const currentParent = source.path.includes("/")
      ? source.path.slice(0, source.path.lastIndexOf("/"))
      : "";
    return currentParent !== target.path;
  }

  async function dropInto(target: ExplorerNode) {
    const source = dragSource;
    setDropTarget(null);
    setDragSource(null);
    if (!canDrop(source, target) || !source || moving) return;
    setMoving(true);
    setActionNotice(null);
    setActionError(false);
    try {
      const result = await api.moveVaultItem(source.path, target.path);
      movedSelection(result.refs);
      setActionNotice(`Moved ${source.name} into ${target.name}.`);
      await refresh();
      window.dispatchEvent(new Event("obsidience:knowledge-changed"));
    } catch (cause) {
      setActionError(true);
      setActionNotice(String(cause));
    } finally {
      setMoving(false);
    }
  }

  const renderNodes = (nodes: ExplorerNode[], depth = 0): React.ReactNode => nodes.map((node) => {
    const folder = node.folder;
    const open = expanded.has(node.key) || Boolean(query.trim());
    const selected = node.ref === selectedRef;
    const draggable = manageable(node);
    return (
      <div key={node.key}>
        <div onClick={() => node.ref && openReader(node.ref)} draggable={draggable && !moving}
          onContextMenu={(event) => {
            event.preventDefault();
            event.stopPropagation();
            if (draggable) setMenu({ node, x: event.clientX, y: event.clientY, value: node.name });
          }}
          onDragStart={(event) => {
            if (!draggable) return;
            setDragSource(node);
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("application/x-obsidience-vault-path", node.path);
          }}
          onDragEnd={() => { setDragSource(null); setDropTarget(null); }}
          onDragOver={(event) => {
            if (!canDrop(dragSource, node)) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            setDropTarget(node.key);
          }}
          onDragLeave={() => setDropTarget((current) => current === node.key ? null : current)}
          onDrop={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void dropInto(node);
          }}
          className={`flex items-center py-0.5 pr-1 ${node.ref ? "cursor-pointer" : ""} ${dropTarget === node.key ? "bg-emerald-300/15 text-emerald-100 ring-1 ring-inset ring-emerald-300/40" : selected ? "bg-cyan-300/10 text-cyan-50" : "text-cyan-100/65 hover:bg-cyan-300/[0.045]"}`}
          style={{ paddingLeft: 4 + depth * 12 }}>
          <button type="button" onClick={(event) => { event.stopPropagation(); if (folder) toggle(node.key); }} disabled={!folder}
            className="flex h-4 w-4 shrink-0 items-center justify-center text-cyan-300/45 disabled:text-transparent">
            {folder ? (open ? <ChevronDown size={10} /> : <ChevronRight size={10} />) : null}
          </button>
          {folder
            ? (open ? <FolderOpen size={11} className="mr-1 shrink-0 text-cyan-300/60" /> : <Folder size={11} className="mr-1 shrink-0 text-cyan-300/60" />)
            : <FileText size={10} className="mr-1 shrink-0 text-cyan-300/40" />}
          <button type="button" disabled={!node.ref}
            title={node.ref ?? node.name}
            className="min-w-0 flex-1 truncate text-left font-mono text-[9px] disabled:cursor-default">
            {node.name}
          </button>
        </div>
        {folder && open ? renderNodes(node.children, depth + 1) : null}
      </div>
    );
  });

  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-[#020a12]/75">
      <div className="border-b border-cyan-300/10 p-2">
        <div className="mb-1 flex items-center justify-between font-mono text-[8px] uppercase tracking-[0.18em] text-cyan-300/50">
          <ReaderModuleDragHandle chrome={chrome}><span>Knowledge</span></ReaderModuleDragHandle>
          <span className="flex items-center gap-1.5">
            <span>{files.length}</span>
            <ReaderModuleControls chrome={chrome} tint="cyan" />
          </span>
        </div>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter articles"
          className={`${FIELD_CLASS} py-1 text-[9px]`} />
        {actionNotice ? <p className={`mt-1 truncate font-mono text-[8px] ${actionError ? "text-rose-300/80" : "text-emerald-300/70"}`} title={actionNotice}>{actionNotice}</p> : null}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        <div className="space-y-1.5">
          {visibleGroups.map((group) => {
            const open = expandedGroups.has(group.id) || Boolean(query.trim());
            const tint = knowledgeRoleTint(group.role);
            return (
              <section key={group.id}>
                <div className="flex overflow-hidden rounded border bg-[#030b12]/90"
                  style={{ borderColor: `${tint}55`, boxShadow: open ? `0 0 16px ${tint}16` : undefined }}>
                  <button type="button" onClick={() => toggleGroup(group.id)}
                    aria-expanded={open}
                    className="flex min-w-0 flex-1 items-center gap-2.5 px-2 py-2 text-left hover:bg-white/[0.025]">
                    <ExplorerRoleGlyph role={group.role} size={31} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-[10px] uppercase tracking-[0.16em]"
                        style={{ color: tint }}>{group.label}</span>
                      <span className="mt-0.5 block truncate font-mono text-[8px] uppercase tracking-[0.12em] text-cyan-100/35">
                        {group.subtitle} · {group.count}
                      </span>
                    </span>
                    {open ? <ChevronDown size={13} style={{ color: tint }} /> : <ChevronRight size={13} style={{ color: tint }} />}
                  </button>
                  <button type="button" onClick={() => openReader(group.rootRef)}
                    title={`Read ${group.label}`}
                    className="flex w-8 shrink-0 items-center justify-center border-l hover:bg-white/[0.035]"
                    style={{ borderColor: `${tint}33`, color: `${tint}aa` }}>
                    <FileText size={11} />
                  </button>
                </div>
                {open ? (
                  <div className="ml-4 border-l py-1 pl-1" style={{ borderColor: `${tint}33` }}>
                    {group.tree.length ? renderNodes(group.tree) : (
                      <p className="px-2 py-1 font-mono text-[8px] text-cyan-100/30">No knowledge assigned.</p>
                    )}
                  </div>
                ) : null}
              </section>
            );
          })}
        </div>
      </div>
      {menu ? (
        <>
          <button type="button" aria-label="Close rename menu" onClick={() => setMenu(null)}
            className="fixed inset-0 z-[80] cursor-default bg-transparent" />
          <form onSubmit={(event) => { event.preventDefault(); void renameItem(); }}
            onClick={(event) => event.stopPropagation()}
            className="fixed z-[81] w-52 rounded border border-cyan-300/30 bg-[#020a12] p-2 shadow-[0_0_24px_rgba(34,211,238,0.12)]"
            style={{ left: Math.min(menu.x, window.innerWidth - 220), top: Math.min(menu.y, window.innerHeight - 132) }}>
            <p className="mb-1 font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
              Rename {menu.node.folder ? "folder" : "article"}
            </p>
            <input autoFocus value={menu.value} disabled={moving}
              onChange={(event) => setMenu({ ...menu, value: event.target.value, error: undefined })}
              onKeyDown={(event) => { if (event.key === "Escape") setMenu(null); }}
              className={`${FIELD_CLASS} text-[9px]`} />
            {menu.error ? <p className="mt-1 line-clamp-2 font-mono text-[8px] text-rose-300/80">{menu.error}</p> : null}
            <div className="mt-2 flex justify-end gap-1">
              <button type="button" onClick={() => setMenu(null)}
                className="rounded border border-cyan-300/15 px-2 py-1 font-mono text-[8px] uppercase text-cyan-200/55">Cancel</button>
              <button type="submit" disabled={moving || !menu.value.trim() || menu.value.trim() === menu.node.name}
                className="rounded border border-cyan-300/35 px-2 py-1 font-mono text-[8px] uppercase text-cyan-100 disabled:opacity-35">
                {moving ? "Renaming" : "Rename"}
              </button>
            </div>
          </form>
        </>
      ) : null}
    </aside>
  );
}

interface SourceTreeNode {
  key: string;
  name: string;
  folder: boolean;
  file?: SourceFile;
  virtual?: boolean;
  backingPath?: string;
  subtitle?: string;
  order?: number;
  storage?: {
    filesystem?: StorageFilesystem;
    location?: StorageLocation;
  };
  children: SourceTreeNode[];
}

const SOURCE_VIEW = {
  system: "@view/system",
  hardware: "@view/system/hardware",
  compute: "@view/system/hardware/compute",
  drives: "@view/system/hardware/drives",
  volume: "@view/system/hardware/drives/system-volume",
  obsidience: "@view/system/hardware/drives/system-volume/obsidience",
  modelsDrive: "@view/system/hardware/drives/system-volume/models",
  devices: "@view/system/hardware/devices",
  applications: "@view/system/applications",
  network: "@view/network",
} as const;

const SYSTEM_SOURCE_PREFIX = "obsidience/state/system";

interface SourceRoute {
  parent: "system" | "obsidience" | "compute" | "devices" | "applications" | "network" | "modelsDrive";
  relativePath: string;
  physicalBase: string;
  virtualAncestors: string[];
}

function sourceRoute(file: SourceFile): SourceRoute {
  const compute = `${SYSTEM_SOURCE_PREFIX}/hardware/compute/`;
  const devices = `${SYSTEM_SOURCE_PREFIX}/hardware/devices/`;
  const applications = `${SYSTEM_SOURCE_PREFIX}/applications/`;
  const network = `${SYSTEM_SOURCE_PREFIX}/network/`;
  const volume = `${SYSTEM_SOURCE_PREFIX}/hardware/drives/system-volume/`;
  const modelSources = "obsidience/evidence/models/";
  if (file.path.startsWith(compute)) return {
    parent: "compute",
    relativePath: file.path.slice(compute.length),
    physicalBase: compute.slice(0, -1),
    virtualAncestors: [SOURCE_VIEW.system, SOURCE_VIEW.hardware, SOURCE_VIEW.compute],
  };
  if (file.path.startsWith(devices)) return {
    parent: "devices",
    relativePath: file.path.slice(devices.length),
    physicalBase: devices.slice(0, -1),
    virtualAncestors: [SOURCE_VIEW.system, SOURCE_VIEW.hardware, SOURCE_VIEW.devices],
  };
  if (file.path.startsWith(applications)) return {
    parent: "applications",
    relativePath: file.path.slice(applications.length),
    physicalBase: applications.slice(0, -1),
    virtualAncestors: [SOURCE_VIEW.system, SOURCE_VIEW.applications],
  };
  if (file.path.startsWith(network)) return {
    parent: "network",
    relativePath: file.path.slice(network.length),
    physicalBase: network.slice(0, -1),
    virtualAncestors: [SOURCE_VIEW.network],
  };
  if (file.path === `${volume}obsidience.json`) return {
    parent: "obsidience",
    relativePath: file.name,
    physicalBase: volume.slice(0, -1),
    virtualAncestors: [SOURCE_VIEW.system, SOURCE_VIEW.hardware, SOURCE_VIEW.drives, SOURCE_VIEW.volume, SOURCE_VIEW.obsidience],
  };
  if (file.path === `${volume}ai-models.json`) return {
    parent: "modelsDrive",
    relativePath: file.name,
    physicalBase: volume.slice(0, -1),
    virtualAncestors: [SOURCE_VIEW.system, SOURCE_VIEW.hardware, SOURCE_VIEW.drives, SOURCE_VIEW.volume, SOURCE_VIEW.modelsDrive],
  };
  if (file.path.startsWith(modelSources)) return {
    parent: "modelsDrive",
    relativePath: file.path.slice(modelSources.length),
    physicalBase: modelSources.slice(0, -1),
    virtualAncestors: [SOURCE_VIEW.system, SOURCE_VIEW.hardware, SOURCE_VIEW.drives, SOURCE_VIEW.volume, SOURCE_VIEW.modelsDrive],
  };
  if (file.path === `${SYSTEM_SOURCE_PREFIX}/system.json`) return {
    parent: "system",
    relativePath: file.name,
    physicalBase: SYSTEM_SOURCE_PREFIX,
    virtualAncestors: [SOURCE_VIEW.system],
  };
  const productPrefix = "obsidience/";
  return {
    parent: "obsidience",
    relativePath: file.path.startsWith(productPrefix) ? file.path.slice(productPrefix.length) : file.path,
    physicalBase: file.path.startsWith(productPrefix) ? "obsidience" : "",
    virtualAncestors: [SOURCE_VIEW.system, SOURCE_VIEW.hardware, SOURCE_VIEW.drives, SOURCE_VIEW.volume, SOURCE_VIEW.obsidience],
  };
}

function sourcePresentationAncestors(file: SourceFile): string[] {
  const route = sourceRoute(file);
  const parts = route.relativePath.split("/").filter(Boolean);
  parts.pop();
  let prefix = route.physicalBase;
  const physical = parts.map((part) => {
    prefix = prefix ? `${prefix}/${part}` : part;
    return prefix;
  });
  return [...route.virtualAncestors, ...physical];
}

function sourceFolderName(path: string, name: string): string {
  return path.startsWith(`${SYSTEM_SOURCE_PREFIX}/`)
    ? name.replace(/[-_]+/g, " ").toUpperCase()
    : name;
}

function buildSourceTree(files: SourceFile[], storage: StorageState | null): SourceTreeNode[] {
  const hasTree = (path: string) => files.some((file) =>
    file.path === path || file.path.startsWith(`${path}/`));
  const filesystemFor = (location?: StorageLocation) =>
    storage?.filesystems.find((filesystem) => filesystem.id === location?.filesystem_id);
  const obsidienceLocation = storage?.locations.find((location) => location.id === "obsidience");
  const modelsLocation = storage?.locations.find((location) => location.id === "models");
  const sharedFilesystem = storage?.filesystems.length === 1 ? storage.filesystems[0] : undefined;

  const obsidience: SourceTreeNode = {
    key: SOURCE_VIEW.obsidience,
    name: "OBSIDIENCE",
    folder: true,
    virtual: true,
    backingPath: "obsidience",
    subtitle: obsidienceLocation?.available
      ? `${obsidienceLocation.path} · shared filesystem · no quota`
      : "Storage unavailable",
    order: 0,
    storage: { location: obsidienceLocation, filesystem: filesystemFor(obsidienceLocation) },
    children: [],
  };
  const modelsDrive: SourceTreeNode = {
    key: SOURCE_VIEW.modelsDrive,
    name: modelsLocation?.label ?? "AI Models",
    folder: true,
    virtual: true,
    backingPath: "obsidience/evidence/models",
    subtitle: modelsLocation?.available
      ? `${modelsLocation.path} · shared filesystem · no quota`
      : "Storage unavailable",
    order: 1,
    storage: { location: modelsLocation, filesystem: filesystemFor(modelsLocation) },
    children: [],
  };
  const volume: SourceTreeNode = {
    key: SOURCE_VIEW.volume,
    name: "SYSTEM VOLUME",
    folder: true,
    virtual: true,
    backingPath: `${SYSTEM_SOURCE_PREFIX}/hardware/drives/system-volume`,
    subtitle: sharedFilesystem ? "BTRFS · one shared physical capacity pool" : "Physical storage volume",
    order: 0,
    storage: { filesystem: sharedFilesystem },
    children: [obsidience, modelsDrive].filter((node) =>
      Boolean(node.backingPath && hasTree(node.backingPath))),
  };
  const compute: SourceTreeNode = {
    key: SOURCE_VIEW.compute,
    name: "COMPUTE",
    folder: true,
    virtual: true,
    backingPath: `${SYSTEM_SOURCE_PREFIX}/hardware/compute`,
    subtitle: "Processors and accelerators",
    order: 0,
    children: [],
  };
  const drives: SourceTreeNode = {
    key: SOURCE_VIEW.drives,
    name: "DRIVES",
    folder: true,
    virtual: true,
    backingPath: `${SYSTEM_SOURCE_PREFIX}/hardware/drives`,
    subtitle: "Volumes and their actual files",
    order: 1,
    children: [volume],
  };
  const devices: SourceTreeNode = {
    key: SOURCE_VIEW.devices,
    name: "DEVICES",
    folder: true,
    virtual: true,
    backingPath: `${SYSTEM_SOURCE_PREFIX}/hardware/devices`,
    subtitle: "Input and output",
    order: 2,
    children: [],
  };
  const hardware: SourceTreeNode = {
    key: SOURCE_VIEW.hardware,
    name: "HARDWARE",
    folder: true,
    virtual: true,
    backingPath: `${SYSTEM_SOURCE_PREFIX}/hardware`,
    subtitle: "Physical computer",
    order: 0,
    children: [compute, drives, devices].filter((node) =>
      Boolean(node.backingPath && hasTree(node.backingPath))),
  };
  const applications: SourceTreeNode = {
    key: SOURCE_VIEW.applications,
    name: "APPLICATIONS",
    folder: true,
    virtual: true,
    backingPath: `${SYSTEM_SOURCE_PREFIX}/applications`,
    subtitle: "Obsidience shell and integrated applications",
    order: 1,
    children: [],
  };
  const system: SourceTreeNode = {
    key: SOURCE_VIEW.system,
    name: "SYSTEM",
    folder: true,
    virtual: true,
    backingPath: SYSTEM_SOURCE_PREFIX,
    subtitle: "This PC",
    order: 0,
    children: [hardware, applications].filter((node) =>
      Boolean(node.backingPath && hasTree(node.backingPath))),
  };
  const network: SourceTreeNode = {
    key: SOURCE_VIEW.network,
    name: "NETWORK",
    folder: true,
    virtual: true,
    backingPath: `${SYSTEM_SOURCE_PREFIX}/network`,
    subtitle: "Connections and remote systems",
    order: 1,
    children: [],
  };
  const parents = {
    system,
    obsidience,
    compute,
    devices,
    applications,
    network,
    modelsDrive,
  };

  for (const file of files) {
    const route = sourceRoute(file);
    const parts = route.relativePath.split("/").filter(Boolean);
    const filename = parts.pop() ?? file.name;
    let children = parents[route.parent].children;
    let prefix = route.physicalBase;
    for (const part of parts) {
      prefix = prefix ? `${prefix}/${part}` : part;
      let folder = children.find((node) => node.folder && node.key === prefix);
      if (!folder) {
        folder = {
          key: prefix,
          name: sourceFolderName(prefix, part),
          folder: true,
          backingPath: prefix,
          children: [],
        };
        children.push(folder);
      }
      children = folder.children;
    }
    children.push({ key: file.key, name: filename, folder: false, file, children: [] });
  }
  const sort = (nodes: SourceTreeNode[]) => {
    nodes.sort((left, right) => {
      if (left.order !== undefined || right.order !== undefined) {
        return (left.order ?? Number.MAX_SAFE_INTEGER) - (right.order ?? Number.MAX_SAFE_INTEGER);
      }
      return Number(right.folder) - Number(left.folder) || left.name.localeCompare(right.name);
    });
    nodes.forEach((node) => sort(node.children));
  };
  const roots = [system, network].filter((node) =>
    Boolean(node.backingPath && hasTree(node.backingPath)));
  sort(roots);
  return roots;
}

function filterSourceTree(nodes: SourceTreeNode[], needle: string): SourceTreeNode[] {
  if (!needle) return nodes;
  return nodes.flatMap((node) => {
    const children = filterSourceTree(node.children, needle);
    const matches = `${node.name} ${node.key} ${node.subtitle ?? ""} ${node.file?.articles.join(" ") ?? ""}`
      .toLowerCase().includes(needle);
    return matches || children.length ? [{ ...node, children }] : [];
  });
}

function pruneEmptySourceTree(nodes: SourceTreeNode[]): SourceTreeNode[] {
  return nodes.flatMap((node) => {
    if (!node.folder) return [node];
    const children = pruneEmptySourceTree(node.children);
    return children.length ? [{ ...node, children }] : [];
  });
}

function sourceMatchesArticle(file: SourceFile, selectedRef: string): boolean {
  if (file.articles.includes(selectedRef)) return true;
  if (!selectedRef.startsWith("@branch/")) return false;
  const branch = selectedRef.slice("@branch/".length);
  if (branch === "ADMECH Workstation" && file.storage === "system") return true;
  return file.articles.some((ref) => ref === branch || ref.startsWith(`${branch}/`));
}

function readableBytes(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  if (bytes < 1_048_576) return `${(bytes / 1_024).toFixed(1)} KB`;
  if (bytes < 1_073_741_824) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes < 1_099_511_627_776) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
  return `${(bytes / 1_099_511_627_776).toFixed(1)} TB`;
}

function SourceFolderGlyph({ node, open }: { node: SourceTreeNode; open: boolean }) {
  const className = node.virtual ? "text-violet-200/75" : "text-violet-300/50";
  if (node.key === SOURCE_VIEW.system) return <Computer size={12} className="text-cyan-200/80" />;
  if (node.key === SOURCE_VIEW.obsidience) return <Package size={11} className={className} />;
  if (node.key === SOURCE_VIEW.hardware) return <Server size={11} className="text-emerald-300/70" />;
  if (node.key === SOURCE_VIEW.compute) return <Cpu size={11} className="text-emerald-300/70" />;
  if (node.key === SOURCE_VIEW.drives || node.key === SOURCE_VIEW.volume || node.storage?.location) return <HardDrive size={11} className="text-sky-300/70" />;
  if (node.key === SOURCE_VIEW.devices) return <Usb size={11} className="text-amber-300/70" />;
  if (node.key === SOURCE_VIEW.applications) return <AppWindow size={11} className="text-fuchsia-300/70" />;
  if (node.key === SOURCE_VIEW.network) return <Network size={11} className="text-blue-300/70" />;
  return open
    ? <FolderOpen size={10} className={className} />
    : <Folder size={10} className={className} />;
}

type PythonTokenKind =
  | "plain" | "comment" | "string" | "keyword" | "constant"
  | "number" | "builtin" | "definition" | "call" | "decorator" | "operator";

interface PythonToken { text: string; kind: PythonTokenKind }

const PYTHON_KEYWORDS = new Set([
  "and", "as", "assert", "async", "await", "break", "case", "class", "continue",
  "def", "del", "elif", "else", "except", "finally", "for", "from", "global",
  "if", "import", "in", "is", "lambda", "match", "nonlocal", "not", "or", "pass",
  "raise", "return", "try", "while", "with", "yield",
]);
const PYTHON_CONSTANTS = new Set(["True", "False", "None", "Ellipsis", "NotImplemented", "self", "cls"]);
const PYTHON_BUILTINS = new Set([
  "abs", "all", "any", "bool", "bytes", "callable", "classmethod", "dict", "dir",
  "enumerate", "filter", "float", "format", "frozenset", "getattr", "hasattr", "hash",
  "help", "hex", "id", "input", "int", "isinstance", "issubclass", "iter", "len",
  "list", "map", "max", "memoryview", "min", "next", "object", "open", "ord", "pow",
  "print", "property", "range", "repr", "reversed", "round", "set", "setattr", "slice",
  "sorted", "staticmethod", "str", "sum", "super", "tuple", "type", "vars", "zip",
]);
const PYTHON_TOKEN_STYLE: Record<PythonTokenKind, string> = {
  plain: "text-slate-200/88",
  comment: "italic text-slate-500",
  string: "text-emerald-300/90",
  keyword: "font-medium text-fuchsia-300/95",
  constant: "text-amber-300/95",
  number: "text-orange-300/95",
  builtin: "text-cyan-300/90",
  definition: "font-semibold text-sky-300",
  call: "text-blue-300/95",
  decorator: "text-yellow-300/90",
  operator: "text-violet-300/75",
};

function pythonTokens(source: string): PythonToken[][] {
  let multilineQuote: "'''" | "\"\"\"" | null = null;
  const push = (tokens: PythonToken[], text: string, kind: PythonTokenKind) => {
    if (!text) return;
    const last = tokens.at(-1);
    if (last?.kind === kind) last.text += text;
    else tokens.push({ text, kind });
  };

  return source.split("\n").map((line) => {
    const tokens: PythonToken[] = [];
    let cursor = 0;
    let expectDefinition = false;

    while (cursor < line.length) {
      if (multilineQuote) {
        const end = line.indexOf(multilineQuote, cursor);
        if (end < 0) {
          push(tokens, line.slice(cursor), "string");
          cursor = line.length;
          continue;
        }
        push(tokens, line.slice(cursor, end + multilineQuote.length), "string");
        cursor = end + multilineQuote.length;
        multilineQuote = null;
        continue;
      }

      const rest = line.slice(cursor);
      const whitespace = rest.match(/^\s+/)?.[0];
      if (whitespace) {
        push(tokens, whitespace, "plain");
        cursor += whitespace.length;
        continue;
      }
      if (line[cursor] === "#") {
        push(tokens, line.slice(cursor), "comment");
        break;
      }

      const decorator = rest.match(/^@[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*/)?.[0];
      if (decorator) {
        push(tokens, decorator, "decorator");
        cursor += decorator.length;
        continue;
      }

      const stringOpening = rest.match(/^(?:[rRuUbBfF]{1,3})?(?:'''|\"\"\"|'|\")/)?.[0];
      if (stringOpening) {
        const quote: "'''" | "\"\"\"" | "'" | "\"" = stringOpening.endsWith("'''")
          ? "'''" : stringOpening.endsWith("\"\"\"") ? "\"\"\""
            : stringOpening.endsWith("'") ? "'" : "\"";
        if (quote === "'''" || quote === "\"\"\"") {
          const end = line.indexOf(quote, cursor + stringOpening.length);
          if (end < 0) {
            push(tokens, line.slice(cursor), "string");
            multilineQuote = quote;
            break;
          }
          push(tokens, line.slice(cursor, end + quote.length), "string");
          cursor = end + quote.length;
          continue;
        }
        let end = cursor + stringOpening.length;
        let escaped = false;
        while (end < line.length) {
          const character = line[end];
          end += 1;
          if (!escaped && character === quote) break;
          escaped = !escaped && character === "\\";
          if (character !== "\\") escaped = false;
        }
        push(tokens, line.slice(cursor, end), "string");
        cursor = end;
        continue;
      }

      const identifier = rest.match(/^[A-Za-z_]\w*/)?.[0];
      if (identifier) {
        let kind: PythonTokenKind = "plain";
        if (expectDefinition) {
          kind = "definition";
          expectDefinition = false;
        } else if (PYTHON_CONSTANTS.has(identifier)) kind = "constant";
        else if (PYTHON_KEYWORDS.has(identifier)) kind = "keyword";
        else if (PYTHON_BUILTINS.has(identifier)) kind = "builtin";
        else if (rest.slice(identifier.length).trimStart().startsWith("(")) kind = "call";
        push(tokens, identifier, kind);
        if (identifier === "def" || identifier === "class") expectDefinition = true;
        cursor += identifier.length;
        continue;
      }

      const number = rest.match(/^(?:0[xX][\dA-Fa-f](?:_?[\dA-Fa-f])*|0[bB][01](?:_?[01])*|0[oO][0-7](?:_?[0-7])*|(?:\d(?:_?\d)*)?(?:\.\d(?:_?\d)*)|\d(?:_?\d)*(?:[eE][+-]?\d(?:_?\d)*)?)[jJ]?/)?.[0];
      if (number) {
        push(tokens, number, "number");
        cursor += number.length;
        continue;
      }

      const operator = rest.match(/^(?:\*\*|\/\/|<<|>>|:=|==|!=|<=|>=|->|\+=|-=|\*=|\/=|%=|&=|\|=|\^=|[+\-*\/%@&|^~<>=:])/)?.[0];
      if (operator) {
        push(tokens, operator, "operator");
        cursor += operator.length;
        continue;
      }
      push(tokens, line[cursor], "plain");
      cursor += 1;
    }
    return tokens;
  });
}

function PythonSource({ content, truncated }: { content: string; truncated: boolean }) {
  const lines = useMemo(() => pythonTokens(content), [content]);
  return (
    <div className="overflow-hidden rounded-lg border border-violet-300/16 bg-[#04070d]/96 shadow-[0_18px_52px_rgba(0,0,0,0.28)]">
      <div className="flex items-center justify-between border-b border-violet-300/10 bg-[linear-gradient(90deg,rgba(139,92,246,0.07),rgba(34,211,238,0.025))] px-3 py-2">
        <span className="flex items-center gap-1.5" aria-hidden="true">
          <span className="h-1.5 w-1.5 rounded-full bg-fuchsia-300/55" />
          <span className="h-1.5 w-1.5 rounded-full bg-violet-300/45" />
          <span className="h-1.5 w-1.5 rounded-full bg-cyan-300/55" />
        </span>
        <span className="font-mono text-[8px] uppercase tracking-[0.2em] text-violet-200/45">Python · read only</span>
      </div>
      <div className="overflow-x-auto py-3 font-mono text-[11px] leading-[1.72]" style={{ tabSize: 4 }}>
        {lines.map((tokens, index) => (
          <div key={index} className="group flex min-w-max hover:bg-cyan-300/[0.025]">
            <span className="sticky left-0 w-12 shrink-0 select-none border-r border-violet-300/[0.07] bg-[#04070d] pr-3 text-right text-[9px] text-slate-600 group-hover:text-slate-500">
              {index + 1}
            </span>
            <code className="block min-w-0 pl-4 pr-6">
              {tokens.length ? tokens.map((token, tokenIndex) => (
                <span key={tokenIndex} className={PYTHON_TOKEN_STYLE[token.kind]}>{token.text}</span>
              )) : " "}
            </code>
          </div>
        ))}
      </div>
      {truncated ? (
        <p className="border-t border-amber-300/12 px-4 py-2 font-mono text-[8px] uppercase tracking-[0.14em] text-amber-200/60">
          Source preview truncated
        </p>
      ) : null}
    </div>
  );
}

function SourceExplorer({
  selectedRef,
  selectedKey,
  onSelect,
  chrome,
}: {
  selectedRef: string | null;
  selectedKey: string | null;
  onSelect: (key: string) => void;
  chrome: ReaderModuleChrome;
}) {
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [issues, setIssues] = useState<SourceIssue[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [storage, setStorage] = useState<StorageState | null>(null);
  const [checkouts, setCheckouts] = useState<Set<string>>(new Set());
  const [busyCheckouts, setBusyCheckouts] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([
    SOURCE_VIEW.system, SOURCE_VIEW.hardware, SOURCE_VIEW.drives,
    SOURCE_VIEW.volume, SOURCE_VIEW.obsidience, SOURCE_VIEW.applications,
  ]));

  const refresh = useCallback(() => {
    Promise.all([
      api.sourceFiles(),
      api.sourceCheckouts(),
      api.hardware().then((snapshot) => snapshot.storage).catch(() => null),
    ]).then(([result, checkoutSnapshot, storageSnapshot]) => {
      setFiles(result.files);
      setIssues(result.issues);
      setStorage(storageSnapshot);
      setCheckouts(new Set(checkoutSnapshot.assignments.map((assignment) =>
        sourceCheckoutKey(assignment.tree, assignment.agent))));
      setError(null);
    }).catch((cause) => setError(String(cause)));
  }, []);

  useEffect(() => {
    refresh();
    window.addEventListener("obsidience:sources-changed", refresh);
    window.addEventListener("obsidience:knowledge-changed", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      window.removeEventListener("obsidience:sources-changed", refresh);
      window.removeEventListener("obsidience:knowledge-changed", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, [refresh]);

  useEffect(() => {
    if (!error) return;
    const retry = window.setInterval(refresh, 1_000);
    return () => window.clearInterval(retry);
  }, [error, refresh]);

  useEffect(() => {
    setShowAll(false);
  }, [selectedRef]);

  const scopedFiles = useMemo(() => (
    selectedRef && !showAll
      ? files.filter((file) =>
        file.key === selectedKey || sourceMatchesArticle(file, selectedRef))
      : files
  ), [files, selectedKey, selectedRef, showAll]);

  useEffect(() => {
    if (!selectedRef || showAll) return;
    const parents = scopedFiles.flatMap(sourcePresentationAncestors);
    setExpanded((current) => new Set([...current, ...parents]));
  }, [scopedFiles, selectedRef, showAll]);

  const tree = useMemo(() => {
    if (!scopedFiles.length) return [];
    const needle = query.trim().toLowerCase();
    const projected = buildSourceTree(scopedFiles, storage);
    const visible = selectedRef && !showAll ? pruneEmptySourceTree(projected) : projected;
    return filterSourceTree(visible, needle);
  }, [scopedFiles, query, selectedRef, showAll, storage]);

  const toggle = (key: string) => setExpanded((current) => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  const toggleSourceCheckout = (treeKey: string, agent: CheckoutAgent) => {
    const key = sourceCheckoutKey(treeKey, agent);
    if (busyCheckouts.has(key)) return;
    const checkedOut = !checkouts.has(key);
    setBusyCheckouts((current) => new Set(current).add(key));
    api.setSourceCheckout(treeKey, agent, checkedOut).then(() => {
      setCheckouts((current) => {
        const next = new Set(current);
        if (checkedOut) next.add(key); else next.delete(key);
        return next;
      });
      setError(null);
      window.dispatchEvent(new Event("obsidience:knowledge-changed"));
    }).catch((cause) => setError(String(cause))).finally(() => {
      setBusyCheckouts((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    });
  };

  const renderNodes = (nodes: SourceTreeNode[], depth = 0): React.ReactNode => nodes.map((node) => {
    const open = expanded.has(node.key) || Boolean(query.trim());
    if (node.folder) {
      const checkoutPath = node.backingPath;
      const filesystem = node.storage?.filesystem;
      const showCapacity = node.key === SOURCE_VIEW.volume && filesystem;
      return (
        <div key={node.key}>
          <div className={`group/source-row flex w-full items-center rounded hover:bg-violet-300/[0.055] ${node.virtual ? "bg-white/[0.012]" : ""}`}>
          <button type="button" onClick={() => toggle(node.key)}
            title={checkoutPath ?? node.subtitle ?? node.name}
            className={`flex min-w-0 flex-1 items-center gap-1 pr-1 text-left font-mono text-violet-100/60 hover:text-violet-50 ${node.virtual ? "py-1.5 text-[9px]" : "py-1 text-[9px]"}`}
            style={{ paddingLeft: 4 + depth * 12 }}>
            {open ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
            <SourceFolderGlyph node={node} open={open} />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className={`truncate ${node.key === SOURCE_VIEW.system ? "text-[10px] font-semibold tracking-[0.12em] text-cyan-50/90" : node.virtual ? "font-medium tracking-[0.07em] text-violet-50/75" : ""}`}>
                {node.name}
              </span>
              {node.subtitle ? (
                <span className="truncate text-[7px] normal-case tracking-normal text-violet-200/32">{node.subtitle}</span>
              ) : null}
            </span>
          </button>
          {checkoutPath ? (
            <span className="mr-1 flex shrink-0 items-center gap-0.5" aria-label="Agent Source checkouts">
            {SOURCE_CHECKOUT_AGENTS.map(({ id, label }) => {
              const key = sourceCheckoutKey(checkoutPath, id);
              const checked = checkouts.has(key);
              return (
                <button key={id} type="button" aria-pressed={checked}
                  disabled={busyCheckouts.has(key)}
                  title={`${checked ? "Return" : "Check out"} ${checkoutPath} ${checked ? "from" : "to"} ${label}`}
                  onClick={(event) => { event.stopPropagation(); toggleSourceCheckout(checkoutPath, id); }}
                  className={`flex h-[18px] w-[18px] items-center justify-center rounded border transition-all disabled:opacity-30 ${checked
                    ? SOURCE_CHECKED_STYLE[id]
                    : "border-violet-300/10 bg-[#02070c]/65 opacity-45 hover:border-violet-300/35 hover:opacity-100"}`}>
                  <SourceCheckoutGlyph agent={id} />
                </button>
              );
            })}
            </span>
          ) : null}
          </div>
          {showCapacity ? (
            <div className="mb-1.5 mt-0.5 rounded border border-sky-300/10 bg-sky-300/[0.025] px-2 py-1.5"
              style={{ marginLeft: 18 + depth * 12 }}>
              <div className="mb-1 flex items-center justify-between gap-2 font-mono text-[7px] text-sky-100/45">
                <span>{filesystem.filesystem?.toUpperCase() ?? "Filesystem"} · shared by Obsidience and AI Models</span>
                <span>{filesystem.used_percent?.toFixed(1) ?? "—"}%</span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-sky-100/10">
                <div className="h-full rounded-full bg-gradient-to-r from-cyan-400/55 to-violet-400/65"
                  style={{ width: `${Math.min(100, Math.max(0, filesystem.used_percent ?? 0))}%` }} />
              </div>
              <div className="mt-1 flex justify-between font-mono text-[7px] text-sky-100/30">
                <span>{readableBytes(filesystem.used_bytes)} used</span>
                <span>{readableBytes(filesystem.available_bytes)} free · {readableBytes(filesystem.total_bytes)} total</span>
              </div>
            </div>
          ) : null}
          {open ? renderNodes(node.children, depth + 1) : null}
        </div>
      );
    }
    const fileKey = node.file!.key;
    const active = selectedKey === fileKey;
    return (
      <button key={fileKey} type="button" onClick={() => onSelect(fileKey)} title={node.file!.path}
        className={`flex w-full items-center gap-1.5 rounded py-1 pr-1 text-left font-mono text-[9px] ${active
          ? "bg-violet-300/12 text-violet-50"
          : "text-violet-100/55 hover:bg-violet-300/[0.055] hover:text-violet-50"}`}
        style={{ paddingLeft: 17 + depth * 12 }}>
        <FileText size={10} className={node.file?.storage === "code"
          ? "text-cyan-300/60"
          : node.file?.storage === "system"
            ? "text-emerald-300/60"
            : node.file?.storage === "knowledge"
              ? "text-sky-300/60"
              : "text-violet-300/55"} />
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
        <span className="shrink-0 text-[7px] text-violet-300/25">{readableBytes(node.file?.size ?? 0)}</span>
      </button>
    );
  });

  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-[#08050f]/78">
      <div className="border-b border-violet-300/10 p-2">
        <div className="mb-1 flex items-center justify-between font-mono text-[8px] uppercase tracking-[0.18em] text-violet-300/55">
          <ReaderModuleDragHandle chrome={chrome}>
            <span className="flex items-center gap-1.5"><Database size={10} /> Source</span>
          </ReaderModuleDragHandle>
          <span className="flex items-center gap-1.5">
            <span>{scopedFiles.length}{scopedFiles.length !== files.length ? `/${files.length}` : ""}</span>
            <button type="button" title="Refresh Source"
              onClick={() => window.dispatchEvent(new Event("obsidience:sources-changed"))}
              className="rounded p-0.5 text-violet-300/45 hover:bg-violet-300/10 hover:text-violet-100">
              <RefreshCw size={9} />
            </button>
            <ReaderModuleControls chrome={chrome} tint="violet" />
          </span>
        </div>
        <input value={query} onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter files" className={`${FIELD_CLASS} border-violet-300/20 py-1 text-[9px]`} />
        {selectedRef ? (
          <div className="mt-1.5 flex items-center justify-between gap-2 rounded border border-cyan-300/12 bg-cyan-300/[0.025] px-1.5 py-1 font-mono text-[7px] text-cyan-100/55">
            <span className="min-w-0 truncate">{showAll ? "All Source" : `Article · ${selectedRef}`}</span>
            <button type="button" onClick={() => setShowAll((value) => !value)}
              className="shrink-0 rounded border border-cyan-300/15 px-1 py-0.5 uppercase tracking-[0.12em] hover:border-cyan-300/40 hover:text-cyan-50">
              {showAll ? "Article" : "All"}
            </button>
          </div>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {tree.length ? renderNodes(tree) : (
          <p className="p-2 font-mono text-[9px] leading-4 text-violet-100/35">
            {selectedRef && !showAll
              ? "This Article has no linked physical Source files."
              : "No physical Obsidience Source files are available."}
          </p>
        )}
        {issues.map((issue) => (
          <div key={issue.path} className="mt-1 rounded border border-amber-300/20 bg-amber-300/[0.035] p-1.5 font-mono text-[8px] text-amber-200/70">
            {issue.status} · {issue.path}
          </div>
        ))}
        {error ? <p className="mt-2 font-mono text-[8px] text-rose-300/80">{error}</p> : null}
      </div>
    </aside>
  );
}

function SourceDocument({
  source,
  refreshing,
  onRefresh,
}: {
  source: SourceDoc;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="h-full overflow-y-auto px-5 py-4">
      <div className="mx-auto w-full max-w-[1100px] pb-8">
        <header className="mb-4 flex flex-wrap items-start justify-between gap-3 border-b border-violet-300/12 pb-4">
          <div className="min-w-[220px] flex-1">
            <p className="mb-1.5 font-mono text-[8px] uppercase tracking-[0.22em] text-violet-300/50">
              {source.storage === "knowledge"
                ? "Knowledge Article file"
                : source.storage === "code"
                  ? source.articles.length ? "Article-linked application code" : "Application code"
                  : source.storage === "system"
                    ? "System descriptor · read only"
                    : "Immutable raw source"}
            </p>
            <h1 className="font-mono text-[18px] font-semibold leading-snug tracking-[0.025em] text-violet-50">
              {source.name}
            </h1>
            <p className="mt-1 break-all font-mono text-[8px] text-violet-100/35">{source.path}</p>
          </div>
          <div className="flex flex-wrap justify-end gap-1.5">
            <button type="button" title="Reload current file from disk" onClick={onRefresh}
              className="rounded-full border border-violet-300/15 bg-violet-300/[0.035] p-1.5 text-violet-200/55 hover:border-violet-300/35 hover:text-violet-100">
              <RefreshCw size={10} className={refreshing ? "animate-spin" : ""} />
            </button>
            <span className="rounded-full border border-violet-300/15 bg-violet-300/[0.035] px-2 py-0.5 font-mono text-[8px] uppercase tracking-[0.12em] text-violet-200/55">
              {source.media_type || "file"}
            </span>
            <span className="rounded-full border border-violet-300/15 bg-violet-300/[0.035] px-2 py-0.5 font-mono text-[8px] uppercase tracking-[0.12em] text-violet-200/55">
              {readableBytes(source.size)}
            </span>
          </div>
        </header>
        {source.articles.length ? (
          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[8px] uppercase tracking-[0.16em] text-violet-300/40">Article</span>
            {source.articles.map((ref) => (
              <button key={ref} type="button" onClick={() => openReader(ref)}
                className="rounded border border-cyan-300/18 px-2 py-1 font-mono text-[8px] text-cyan-100/65 hover:border-cyan-300/45 hover:text-cyan-50">
                {ref.split("/").pop() ?? ref}
              </button>
            ))}
          </div>
        ) : null}
        {source.content !== null && (source.media_type.includes("python") || source.name.endsWith(".py")) ? (
          <PythonSource content={source.content} truncated={source.truncated} />
        ) : source.content !== null ? (
          <pre className="overflow-x-auto whitespace-pre rounded-lg border border-violet-300/14 bg-[#05070d]/92 p-4 font-mono text-[11px] leading-[1.65] text-violet-50/82 shadow-[0_14px_42px_rgba(0,0,0,0.22)]">
            {source.content}{source.truncated ? "\n\n… source preview truncated" : ""}
          </pre>
        ) : (
          <div className="rounded-lg border border-violet-300/14 bg-violet-300/[0.025] p-5 font-mono text-[10px] leading-5 text-violet-100/55">
            This binary source is stored here, but it does not have a text preview.
          </div>
        )}
      </div>
    </div>
  );
}

function ReaderModuleBody({
  id,
  docking,
  selectedRef,
  selectedSourceKey,
}: {
  id: ReaderModuleId;
  docking: ReaderDockingProps;
  selectedRef: string | null;
  selectedSourceKey: string | null;
}) {
  const chrome = { id, docking };
  return id === "knowledge" ? (
    <KnowledgeExplorer selectedRef={selectedRef} chrome={chrome} />
  ) : (
    <SourceExplorer selectedRef={selectedRef} selectedKey={selectedSourceKey}
      onSelect={openSourceFile} chrome={chrome} />
  );
}

function ReaderDockStack({
  side,
  docking,
  selectedRef,
  selectedSourceKey,
}: {
  side: "left" | "right";
  docking: ReaderDockingProps;
  selectedRef: string | null;
  selectedSourceKey: string | null;
}) {
  const modules = (["knowledge", "source"] as const)
    .filter((id) => docking.layout[id].placement === side)
    .sort((left, right) => docking.layout[left].order - docking.layout[right].order);
  if (!modules.length) return null;
  const active = modules.filter((id) => !docking.layout[id].collapsed);
  const collapsed = modules.filter((id) => docking.layout[id].collapsed);
  const rail = collapsed.length ? (
    <div className={`flex w-7 shrink-0 flex-col items-center gap-1 pt-2 ${side === "left"
      ? "border-r border-cyan-300/12 bg-[#020a12]/75"
      : "border-l border-violet-300/12 bg-[#08050f]/78"}`}>
      {collapsed.map((id) => (
        <button key={id} type="button" onClick={() => docking.onExpand(id)}
          title={`Open ${id}`} aria-label={`Open ${id}`}
          className={`flex h-5 w-5 items-center justify-center rounded border ${id === "knowledge"
            ? "border-cyan-300/15 text-cyan-200/45 hover:border-cyan-300/40 hover:text-cyan-50"
            : "border-violet-300/15 text-violet-200/45 hover:border-violet-300/40 hover:text-violet-50"}`}>
          {id === "knowledge" ? <FileText size={10} /> : <Database size={10} />}
        </button>
      ))}
    </div>
  ) : null;

  return (
    <div className={`flex h-full shrink-0 ${active.length ? "w-[30%] min-w-[240px] max-w-[380px]" : "w-7"}`}>
      {side === "left" ? rail : null}
      {active.length ? (
        <div className={`flex min-h-0 min-w-0 flex-1 flex-col ${side === "left"
          ? "border-r border-cyan-300/12" : "border-l border-violet-300/12"}`}>
          {active.map((id, index) => (
            <div key={id} className={`min-h-0 flex-1 ${index ? "border-t border-cyan-300/10" : ""}`}>
              <ReaderModuleBody id={id} docking={docking} selectedRef={selectedRef}
                selectedSourceKey={selectedSourceKey} />
            </div>
          ))}
        </div>
      ) : null}
      {side === "right" ? rail : null}
    </div>
  );
}

function ReaderDockTargets({ docking }: { docking: ReaderDockingProps }) {
  if (!docking.dragging) return null;
  const zone = (
    side: "left" | "right",
    position: ReaderDockPosition,
    label: string,
    className: string,
  ) => (
    <button type="button" key={`${side}-${position}`}
      onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; }}
      onDrop={(event) => {
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = "move";
        const id = (event.dataTransfer.getData("application/x-obsidience-reader-module") || docking.dragging) as ReaderModuleId;
        if (id === "knowledge" || id === "source") docking.onDock(id, side, position);
      }}
      className={`pointer-events-auto absolute flex items-center justify-center border border-dashed border-cyan-200/45 bg-cyan-300/[0.09] font-mono text-[9px] uppercase tracking-[0.18em] text-cyan-50/80 backdrop-blur-sm ${className}`}>
      {label}
    </button>
  );
  return (
    <div className="pointer-events-none absolute inset-0 z-[70]">
      {zone("left", "top", "Dock left · top", "left-2 top-2 h-[calc(50%_-_12px)] w-[28%] rounded-t-lg")}
      {zone("left", "bottom", "Dock left · bottom", "bottom-2 left-2 h-[calc(50%_-_12px)] w-[28%] rounded-b-lg")}
      {zone("right", "top", "Dock right · top", "right-2 top-2 h-[calc(50%_-_12px)] w-[28%] rounded-t-lg")}
      {zone("right", "bottom", "Dock right · bottom", "bottom-2 right-2 h-[calc(50%_-_12px)] w-[28%] rounded-b-lg")}
    </div>
  );
}

function ReaderShell({
  selectedRef,
  selectedSourceKey,
  docking,
  children,
}: {
  selectedRef: string | null;
  selectedSourceKey: string | null;
  docking: ReaderDockingProps;
  children: React.ReactNode;
}) {
  return (
    <div className="relative flex h-full min-h-0">
      <ReaderDockStack side="left" docking={docking} selectedRef={selectedRef} selectedSourceKey={selectedSourceKey} />
      <div className="min-w-0 flex-1">{children}</div>
      <ReaderDockStack side="right" docking={docking} selectedRef={selectedRef} selectedSourceKey={selectedSourceKey} />
      <ReaderDockTargets docking={docking} />
    </div>
  );
}

export function ReaderKnowledgePaneBody({ docking }: { docking: ReaderDockingProps }) {
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  useEffect(() => onOpenReader(setSelectedRef), []);
  return <KnowledgeExplorer selectedRef={selectedRef} chrome={{ id: "knowledge", docking }} />;
}

export function ReaderSourcePaneBody({ docking }: { docking: ReaderDockingProps }) {
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  useEffect(() => onOpenReader(setSelectedRef), []);
  useEffect(() => onOpenSourceFile(setSelectedKey), []);
  return <SourceExplorer selectedRef={selectedRef} selectedKey={selectedKey}
    onSelect={openSourceFile} chrome={{ id: "source", docking }} />;
}

function ReaderWikiActionControls({
  actions,
  busy,
  onAction,
}: {
  actions: WikiAction[];
  busy: boolean;
  onAction: (ref: string) => void;
}) {
  const groups = actions.reduce<Map<string, WikiAction[]>>((result, action) => {
    const label = action.agent_label || "Executive";
    result.set(label, [...(result.get(label) ?? []), action]);
    return result;
  }, new Map());
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      <span className="font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-200/55">Wiki</span>
      <select value="" disabled={busy || actions.length === 0}
        aria-label="Wiki action"
        title="Dispatch a Wiki Task on this article; it appears immediately in Tasks"
        onChange={(event) => { if (event.target.value) onAction(event.target.value); }}
        className="rounded border border-violet-300/30 bg-[#061019] px-1.5 py-1 font-mono text-[8px] uppercase tracking-[0.12em] text-violet-200/85 outline-none disabled:opacity-40">
        <option value="">{busy ? "starting…" : actions.length ? "action…" : "unavailable"}</option>
        {[...groups].map(([label, rows]) => (
          <optgroup key={label} label={label}>
            {rows.map((action) => (
              <option key={action.ref} value={action.ref} disabled={action.status === "running"}>
                {action.title}{action.status === "running" ? " · running" : ""}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}

function AutoCurateControl({
  enabled,
  busy,
  onChange,
}: {
  enabled: boolean;
  busy: boolean;
  onChange: (enabled: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-1.5 font-mono text-[8px] uppercase tracking-[0.12em] text-cyan-200/65"
      title="Create an ordinary Task that runs after this agent completes a turn, matching Obsidience's memory trigger">
      <input type="checkbox" checked={enabled} disabled={busy}
        onChange={(event) => onChange(event.target.checked)}
        className="h-3 w-3 accent-cyan-400" />
      {busy ? "Updating…" : "Auto-curate"}
    </label>
  );
}

function splitIndexBody(body: string): { summary: string; sections: string } {
  const sectionStart = body.search(/^##\s+/m);
  if (sectionStart < 0) return { summary: body.trim(), sections: "" };
  return {
    summary: body.slice(0, sectionStart).trim(),
    sections: body.slice(sectionStart).trim(),
  };
}

function IndexArticleContent({ note }: { note: NoteDoc }) {
  const { summary, sections } = splitIndexBody(note.body);
  return (
    <div className="space-y-5">
      <section className="relative overflow-hidden rounded-lg border border-cyan-300/16 bg-[linear-gradient(135deg,rgba(8,31,43,0.82),rgba(2,10,18,0.9))] px-4 py-4 shadow-[0_14px_42px_rgba(0,0,0,0.22)]">
        <div className="absolute inset-y-0 left-0 w-px bg-cyan-200/65 shadow-[0_0_14px_rgba(103,232,249,0.65)]" />
        <p className="mb-2 font-mono text-[8px] uppercase tracking-[0.22em] text-cyan-300/50">Summary</p>
        {summary ? (
          <ArticleMarkdown content={summary} variant="reader" onNavigate={openReader} />
        ) : (
          <p className="font-mono text-[13px] leading-6 text-cyan-100/45">No summary has been written for this index yet.</p>
        )}
      </section>
      {sections ? (
        <section className="rounded-lg border border-cyan-300/10 bg-[#03101a]/48 px-4 py-1 shadow-[0_12px_36px_rgba(0,0,0,0.16)]">
          <ArticleMarkdown content={sections} variant="index" onNavigate={openReader} />
        </section>
      ) : null}
    </div>
  );
}

export function ReaderPaneBody({ docking }: { docking: ReaderDockingProps }) {
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const [selectedSourceKey, setSelectedSourceKey] = useState<string | null>(null);
  const [sourceDoc, setSourceDoc] = useState<SourceDoc | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [note, setNote] = useState<NoteDoc | null>(null);
  const [modelDoc, setModelDoc] = useState<ModelOption | null>(null);
  const [modelDraft, setModelDraft] = useState<ModelDraft | null>(null);
  const [benchmarkDevices, setBenchmarkDevices] = useState<string[]>([]);
  const [benchmarkResult, setBenchmarkResult] = useState<ModelBenchmark | null>(null);
  const [benchmarking, setBenchmarking] = useState(false);
  const [articleNode, setArticleNode] = useState<GraphNode | null>(null);
  const [task, setTask] = useState<TaskRow | null>(null);
  const [taskParent, setTaskParent] = useState<TaskRow | null>(null);
  const [agents, setAgents] = useState<GraphNode[]>([]);
  const [runbooks, setRunbooks] = useState<GraphNode[]>([]);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [wikiActions, setWikiActions] = useState<WikiAction[]>([]);
  const [draft, setDraft] = useState<TaskDraft | null>(null);
  const [articleDraft, setArticleDraft] = useState<ArticleDraft | null>(null);
  const [editing, setEditing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [wikiLaunching, setWikiLaunching] = useState(false);
  const [curationBusy, setCurationBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sourceRequest = useRef(0);

  const load = useCallback(async (ref: string) => {
    sourceRequest.current += 1;
    setSelectedRef(ref);
    setSelectedSourceKey(null);
    setSourceDoc(null);
    setSourceLoading(false);
    setSourceError(null);
    setError(null);
    setNotice(null);
    setModelDoc(null);
    setModelDraft(null);
    setBenchmarkResult(null);
    if (ref.startsWith(RUNTIME_MODEL_PREFIX)) {
      setNote(null);
      setTask(null);
      setArticleNode(null);
      setDraft(null);
      setArticleDraft(null);
      try {
        const nextModel = await api.model(ref.slice(RUNTIME_MODEL_PREFIX.length));
        setModelDoc(nextModel);
        setModelDraft({
          allowed_devices: [...nextModel.allowed_devices],
          context_tokens: nextModel.context_tokens,
          max_output_tokens: nextModel.max_output_tokens,
          gpu_memory_utilization: nextModel.gpu_memory_utilization,
          max_num_seqs: nextModel.max_num_seqs,
        });
        const activeLayout = nextModel.device_sets.find((devices) =>
          devices.join("+") === nextModel.active_devices.join("+"));
        const assignedLayout = nextModel.device_sets.find((devices) =>
          devices.join("+") === nextModel.assigned_devices.join("+"));
        const allowedLayouts = nextModel.device_sets.filter((devices) =>
          devices.every((device) => nextModel.allowed_devices.includes(device)));
        setBenchmarkDevices([...(activeLayout ?? assignedLayout ?? allowedLayouts[0] ?? [])]);
        setBenchmarkResult(nextModel.last_benchmark);
        setEditing(true);
        setDirty(false);
      } catch (cause) {
        setError(String(cause));
      }
      return;
    }
    setNote(null);
    try {
      const [nextNote, tasks, graph, nextWikiActions, modelCatalog] = await Promise.all([
        api.article(ref), api.tasks(), api.graph(), api.wikiActions(), api.models(),
      ]);
      const nextAgents = graph.nodes.filter((node) =>
        node.kind === "agent" || node.id === "Agents/Executive/Executive")
        .sort((left, right) => left.title.localeCompare(right.title));
      const nextRunbooks = graph.nodes.filter((node) => node.kind === "runbook")
        .sort((left, right) => left.title.localeCompare(right.title));
      const nextArticleNode = graph.nodes.find((node) => node.id === nextNote.ref) ?? null;
      const nextTask = tasks.find((row) => row.ref === nextNote.ref) ?? null;
      setNote(nextNote);
      setArticleNode(nextArticleNode);
      setTask(nextTask);
      setTaskParent(nextTask ? parentForTask(nextTask.ref, tasks) : null);
      setAgents(nextAgents);
      setRunbooks(nextRunbooks);
      setModels(modelCatalog.models);
      setWikiActions(nextWikiActions);
      setDraft(nextTask ? draftFor(nextNote, nextTask, nextAgents, nextRunbooks) : null);
      setArticleDraft({ title: nextNote.title, body: nextNote.body });
      setEditing(false);
      setDirty(false);
    } catch (cause) {
      setError(String(cause));
    }
  }, []);

  const openSource = useCallback(async (key: string) => {
    const request = sourceRequest.current + 1;
    sourceRequest.current = request;
    setSelectedSourceKey(key);
    setSourceDoc((current) => current?.key === key ? current : null);
    setSourceLoading(true);
    setSourceError(null);
    setNotice(null);
    try {
      const nextSource = await api.sourceFile(key);
      if (sourceRequest.current === request) setSourceDoc(nextSource);
    } catch (cause) {
      if (sourceRequest.current === request) setSourceError(String(cause));
    } finally {
      if (sourceRequest.current === request) setSourceLoading(false);
    }
  }, []);

  useEffect(() => onOpenReader(load), [load]);
  useEffect(() => onOpenSourceFile(openSource), [openSource]);
  useEffect(() => {
    if (!selectedSourceKey) return;
    const refresh = () => { void openSource(selectedSourceKey); };
    window.addEventListener("obsidience:sources-changed", refresh);
    window.addEventListener("obsidience:knowledge-changed", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      window.removeEventListener("obsidience:sources-changed", refresh);
      window.removeEventListener("obsidience:knowledge-changed", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, [openSource, selectedSourceKey]);

  // A task Reader is a live operational view, not a snapshot. Poll only the
  // tiny task projection so running/completion and the next firing stay fresh.
  useEffect(() => {
    if (!note || note.kind !== "task" || articleNode?.synthetic) return;
    let live = true;
    const pull = () => api.tasks().then((rows) => {
      if (!live) return;
      const current = rows.find((row) => row.ref === note.ref);
      if (current) {
        setTask(current);
        setTaskParent(parentForTask(current.ref, rows));
      }
    }).catch(() => undefined);
    const timer = setInterval(pull, 2_000);
    return () => { live = false; clearInterval(timer); };
  }, [articleNode?.synthetic, note]);

  function updateDraft(update: Partial<TaskDraft>) {
    setDraft((current) => current ? { ...current, ...update } : current);
    setDirty(true);
    setNotice(null);
  }

  function updateArticleDraft(update: Partial<ArticleDraft>) {
    setArticleDraft((current) => current ? { ...current, ...update } : current);
    setDirty(true);
    setNotice(null);
  }

  function updateModelDraft(update: Partial<ModelDraft>) {
    setModelDraft((current) => current ? { ...current, ...update } : current);
    setDirty(true);
    setNotice(null);
  }

  function cancelEdit() {
    if (modelDoc) {
      setModelDraft({
        allowed_devices: [...modelDoc.allowed_devices],
        context_tokens: modelDoc.context_tokens,
        max_output_tokens: modelDoc.max_output_tokens,
        gpu_memory_utilization: modelDoc.gpu_memory_utilization,
        max_num_seqs: modelDoc.max_num_seqs,
      });
      setDirty(false);
      setError(null);
      return;
    }
    if (!note) return;
    if (task) setDraft(draftFor(note, task, agents, runbooks));
    setArticleDraft({ title: note.title, body: note.body });
    setDirty(false);
    setEditing(false);
    setError(null);
  }

  async function saveModel(): Promise<boolean> {
    if (!modelDoc || !modelDraft) return false;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.updateModel(modelDoc.id, modelDraft);
      setModelDoc(saved);
      setModelDraft({
        allowed_devices: [...saved.allowed_devices],
        context_tokens: saved.context_tokens,
        max_output_tokens: saved.max_output_tokens,
        gpu_memory_utilization: saved.gpu_memory_utilization,
        max_num_seqs: saved.max_num_seqs,
      });
      setDirty(false);
      setNotice("Model settings saved; Hardware defaults were reconciled.");
      return true;
    } catch (cause) {
      setError(String(cause));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function testModel() {
    if (!modelDoc || !modelDraft || benchmarking) return;
    if (dirty && !(await saveModel())) return;
    setBenchmarking(true);
    setError(null);
    setNotice("Loading the selected hardware and running the standalone 1:1 model benchmark…");
    try {
      const result = await api.benchmarkModel(modelDoc.id, benchmarkDevices);
      setBenchmarkResult(result);
      setNotice(`Benchmark complete: ${result.summary}`);
      setModelDoc(await api.model(modelDoc.id));
    } catch (cause) {
      setError(String(cause));
      setNotice(null);
    } finally {
      setBenchmarking(false);
    }
  }

  async function saveArticle() {
    if (!note || !articleDraft?.title.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateArticle(note.ref, articleDraft);
      await load(selectedRef ?? note.ref);
      window.dispatchEvent(new Event("obsidience:knowledge-changed"));
      setNotice("Article saved.");
    } catch (cause) {
      setError(String(cause));
    } finally {
      setSaving(false);
    }
  }

  async function toggleAutoCurate(enabled: boolean) {
    if (!note) return;
    const target = selectedRef ?? note.ref;
    setCurationBusy(true);
    setError(null);
    try {
      const result = await api.setAutoCurate(target, enabled);
      setNote((current) => current ? {
        ...current,
        auto_curate: result.enabled,
        auto_curate_task: result.task,
      } : current);
      setNotice(enabled
        ? `Auto-curation enabled. ${result.task ?? "The event Task"} now runs after completed turns.`
        : "Auto-curation disabled; its event Task is paused.");
      window.dispatchEvent(new Event("obsidience:knowledge-changed"));
      window.dispatchEvent(new Event("obsidience:graph-refresh"));
    } catch (cause) {
      setError(String(cause));
    } finally {
      setCurationBusy(false);
    }
  }

  async function saveTask(): Promise<boolean> {
    if (!note || !task || !draft || !draft.title.trim()) return false;
    setSaving(true);
    setError(null);
    try {
      await api.updateTask(note.ref, draft);
      await load(note.ref);
      window.dispatchEvent(new Event("obsidience:knowledge-changed"));
      setNotice("Task saved.");
      return true;
    } catch (cause) {
      setError(String(cause));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function runNow() {
    if (!note || !task || !draft) return;
    if (dirty && !(await saveTask())) return;
    setLaunching(true);
    setError(null);
    setTask({ ...task, status: "running" });
    try {
      await api.runTask(note.ref, draft.reasoning_effort);
      setNotice("Run dispatched. Status and Action Trace are now live.");
    } catch (cause) {
      setError(String(cause));
      await load(note.ref);
    } finally {
      setLaunching(false);
    }
  }

  async function runWikiAction(ref: string) {
    if (!note || wikiLaunching) return;
    const action = wikiActions.find((candidate) => candidate.ref === ref);
    if (!action) return;
    setWikiLaunching(true);
    setError(null);
    setNotice(`${action.title} → ${action.agent_label}…`);
    try {
      await api.runTask(action.ref, action.reasoning_effort, {
        action: action.title,
        claim: note.ref,
      });
      setWikiActions((current) => current.map((candidate) =>
        candidate.ref === ref ? { ...candidate, status: "running" } : candidate));
      setNotice(`${action.title} dispatched to ${action.agent_label}. The Task is live in Tasks.`);
      openTasks();
    } catch (cause) {
      setError(String(cause));
      setNotice(null);
    } finally {
      setWikiLaunching(false);
    }
  }

  if (selectedSourceKey) return (
    <ReaderShell selectedRef={selectedRef} selectedSourceKey={selectedSourceKey} docking={docking}>
      {sourceDoc ? (
        <SourceDocument source={sourceDoc} refreshing={sourceLoading}
          onRefresh={() => openSource(sourceDoc.key)} />
      ) : sourceLoading ? (
        <p className="p-4 font-mono text-[11px] text-violet-200/45">Opening source…</p>
      ) : (
        <p className="p-4 font-mono text-[11px] text-rose-300">{sourceError ?? "Source is unavailable."}</p>
      )}
    </ReaderShell>
  );

  if (modelDoc && modelDraft) {
    const benchmarkChoices = modelDoc.device_sets
      .filter((devices) => devices.every((device) => modelDraft.allowed_devices.includes(device)))
      .map((devices) => ({
        label: devices.length > 1
          ? devices.map((device) => GPU_LABELS[device] ?? device).join(" + ")
          : GPU_LABELS[devices[0]] ?? devices[0],
        devices,
      }));
    const benchmarkValue = benchmarkDevices.join("+");
    return (
      <ReaderShell selectedRef={selectedRef} selectedSourceKey={null} docking={docking}>
        <div className="h-full overflow-y-auto px-5 py-4">
          <div className="mx-auto w-full max-w-[860px] pb-8">
            <header className="mb-5 border-b border-cyan-300/12 pb-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-[240px] flex-1">
                  <p className="mb-1.5 font-mono text-[8px] uppercase tracking-[0.24em] text-cyan-300/45">
                    Runtime model settings
                  </p>
                  <h1 className="font-mono text-[20px] font-semibold leading-tight text-cyan-50">{modelDoc.label}</h1>
                  <p className="mt-1 font-mono text-[9px] leading-4 text-cyan-100/52">{modelDoc.purpose}</p>
                </div>
                <span className={`rounded-full border px-2 py-1 font-mono text-[8px] uppercase tracking-[0.13em] ${modelDoc.loaded
                  ? "border-emerald-300/25 bg-emerald-300/[0.04] text-emerald-200"
                  : modelDoc.installed ? "border-cyan-300/18 text-cyan-200/55"
                    : "border-rose-300/22 text-rose-200/70"}`}>
                  {modelDoc.loaded ? `loaded · ${modelDoc.active_devices.map((device) => GPU_LABELS[device] ?? device).join(" + ")}`
                    : modelDoc.installed ? modelDoc.state : "not installed"}
                </span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5 font-mono text-[8px] text-cyan-200/48">
                <span className="rounded border border-cyan-300/12 px-2 py-1">{modelDoc.quantization}</span>
                <span className="rounded border border-cyan-300/12 px-2 py-1">{modelDoc.runtime}</span>
                <span className="rounded border border-cyan-300/12 px-2 py-1">{modelDoc.default_for}</span>
                {modelDoc.capabilities.map((capability) => (
                  <span key={capability} className="rounded border border-violet-300/12 px-2 py-1 text-violet-200/60">
                    {capability}
                  </span>
                ))}
              </div>
              <p className="mt-2 font-mono text-[8px] text-cyan-200/35">
                Source · {modelDoc.source_manifest}
              </p>
            </header>

            <div className="grid gap-3 md:grid-cols-2">
              <section className="rounded-lg border border-cyan-300/14 bg-[#03101a]/68 p-4">
                <h2 className="font-mono text-[9px] uppercase tracking-[0.18em] text-cyan-200/65">Allowed GPUs</h2>
                <p className="mt-1 font-mono text-[8px] leading-4 text-cyan-100/38">
                  {modelDoc.task_capable
                    ? "Tasks may place this model only on checked devices. Hardware defaults are chosen separately."
                    : "Hardware may place this real-time component only on checked devices. It is not a Task reasoning model."}
                </p>
                <div className="mt-3 space-y-2">
                  {modelDoc.supported_devices.map((device) => {
                    const checked = modelDraft.allowed_devices.includes(device);
                    const afterRemoval = modelDraft.allowed_devices.filter((candidate) => candidate !== device);
                    const cannotRemove = checked && !modelDoc.device_sets.some((devices) =>
                      devices.every((candidate) => afterRemoval.includes(candidate)));
                    return (
                      <label key={device} className="flex items-center gap-2 rounded border border-cyan-300/12 px-2.5 py-2 font-mono text-[9px] text-cyan-50/80">
                        <input type="checkbox" checked={checked} disabled={cannotRemove || saving || benchmarking}
                          className="h-3 w-3 accent-cyan-400"
                          onChange={(event) => updateModelDraft({
                            allowed_devices: event.target.checked
                              ? [...modelDraft.allowed_devices, device]
                              : modelDraft.allowed_devices.filter((candidate) => candidate !== device),
                          })} />
                        {GPU_LABELS[device] ?? device}
                      </label>
                    );
                  })}
                </div>
                {modelDoc.min_gpu_count > 1 ? (
                  <p className="mt-2 font-mono text-[8px] text-amber-200/55">This model requires both GPUs.</p>
                ) : null}
              </section>

              <section className="rounded-lg border border-violet-300/14 bg-[#080817]/68 p-4">
                <h2 className="font-mono text-[9px] uppercase tracking-[0.18em] text-violet-200/65">Inference profile</h2>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <label className="font-mono text-[8px] uppercase tracking-[0.12em] text-violet-200/45">
                    Context
                    <input type="number" min={2048} max={modelDoc.max_context_tokens} step={2048}
                      value={modelDraft.context_tokens} disabled={saving || benchmarking}
                      onChange={(event) => updateModelDraft({ context_tokens: Number(event.target.value) })}
                      className={`${FIELD_CLASS} mt-1`} />
                  </label>
                  <label className="font-mono text-[8px] uppercase tracking-[0.12em] text-violet-200/45">
                    Max output
                    <input type="number" min={256} max={32768} step={256}
                      value={modelDraft.max_output_tokens} disabled={saving || benchmarking}
                      onChange={(event) => updateModelDraft({ max_output_tokens: Number(event.target.value) })}
                      className={`${FIELD_CLASS} mt-1`} />
                  </label>
                  <label className="font-mono text-[8px] uppercase tracking-[0.12em] text-violet-200/45">
                    GPU utilization
                    <input type="number" min={0.5} max={0.99} step={0.01}
                      value={modelDraft.gpu_memory_utilization} disabled={saving || benchmarking}
                      onChange={(event) => updateModelDraft({ gpu_memory_utilization: Number(event.target.value) })}
                      className={`${FIELD_CLASS} mt-1`} />
                  </label>
                  <label className="font-mono text-[8px] uppercase tracking-[0.12em] text-violet-200/45">
                    Max sequences
                    <input type="number" min={1} max={32} step={1}
                      value={modelDraft.max_num_seqs} disabled={saving || benchmarking}
                      onChange={(event) => updateModelDraft({ max_num_seqs: Number(event.target.value) })}
                      className={`${FIELD_CLASS} mt-1`} />
                  </label>
                </div>
              </section>
            </div>

            <section className="mt-3 rounded-lg border border-emerald-300/14 bg-emerald-300/[0.025] p-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="font-mono text-[9px] uppercase tracking-[0.18em] text-emerald-200/65">Standalone model benchmark</h2>
                  <p className="mt-1 font-mono text-[8px] leading-4 text-emerald-100/38">
                    Same prompt, 256-token ceiling, one discarded warmup, and three measured samples. TTFT and end-to-end tok/s are directly comparable for every model.
                  </p>
                </div>
                <div className="flex items-end gap-2">
                  <label className="font-mono text-[8px] uppercase tracking-[0.12em] text-emerald-200/45">
                    Test on
                    <select value={benchmarkValue} disabled={benchmarking || benchmarkChoices.length === 0}
                      onChange={(event) => setBenchmarkDevices(event.target.value.split("+").filter(Boolean))}
                      className={`${FIELD_CLASS} mt-1 min-w-[160px] border-emerald-300/20`}>
                      {benchmarkChoices.map((choice) => (
                        <option key={choice.devices.join("+")} value={choice.devices.join("+")}>{choice.label}</option>
                      ))}
                    </select>
                  </label>
                  <button type="button" onClick={() => void testModel()}
                    disabled={!modelDoc.installed || benchmarking || benchmarkDevices.length < modelDoc.min_gpu_count}
                    className="flex h-[30px] items-center gap-1 rounded border border-emerald-300/35 px-2.5 font-mono text-[8px] uppercase tracking-[0.13em] text-emerald-200 hover:bg-emerald-300/10 disabled:opacity-35">
                    <Play size={10} /> {benchmarking ? "Testing…" : "Benchmark"}
                  </button>
                </div>
              </div>
              {benchmarkResult ? (
                <div className="mt-3 flex flex-wrap gap-2 font-mono text-[9px] text-emerald-100/70">
                  <span className="rounded border border-emerald-300/18 px-2 py-1 text-emerald-200">
                    {(benchmarkResult.tokens_per_second ?? 0).toFixed(2)} end-to-end tok/s
                  </span>
                  <span className="rounded border border-emerald-300/12 px-2 py-1">
                    TTFT {(benchmarkResult.ttft_ms ?? 0).toFixed(1)} ms
                  </span>
                  <span className="rounded border border-emerald-300/12 px-2 py-1">
                    {benchmarkResult.completion_tokens ?? 0} tokens · {(benchmarkResult.total_seconds ?? benchmarkResult.seconds ?? 0).toFixed(2)} s total
                  </span>
                  <span className="rounded border border-emerald-300/12 px-2 py-1">
                    {benchmarkResult.devices.map((device) => GPU_LABELS[device] ?? device).join(" + ")}
                  </span>
                </div>
              ) : null}
              {benchmarkResult && Object.keys(benchmarkResult.metrics ?? {}).length > 0 ? (
                <div className="mt-3 flex flex-wrap gap-2 font-mono text-[8px] text-emerald-100/45">
                  {Object.entries(benchmarkResult.metrics ?? {}).map(([name, value]) => (
                    <span key={name} className="rounded border border-emerald-300/10 px-2 py-1">
                      {name.replaceAll("_", " ")} · {typeof value === "number" ? value.toFixed(2) : String(value)}
                    </span>
                  ))}
                </div>
              ) : null}
            </section>

            <div className="mt-4 flex items-center gap-2">
              <button type="button" onClick={() => void saveModel()} disabled={!dirty || saving || benchmarking}
                className="flex items-center gap-1 rounded border border-cyan-300/35 px-2.5 py-1.5 font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-100 hover:bg-cyan-300/10 disabled:opacity-35">
                <Save size={10} /> {saving ? "Saving" : "Save model"}
              </button>
              {dirty ? (
                <button type="button" onClick={cancelEdit} disabled={saving || benchmarking}
                  className="flex items-center gap-1 rounded border border-cyan-300/18 px-2.5 py-1.5 font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-200/55 hover:text-cyan-50 disabled:opacity-35">
                  <X size={10} /> Reset
                </button>
              ) : null}
            </div>
            {error ? <p className="mt-3 font-mono text-[9px] text-rose-300">{error}</p> : null}
            {notice ? <p className="mt-3 font-mono text-[9px] text-emerald-300/75">{notice}</p> : null}
          </div>
        </div>
      </ReaderShell>
    );
  }

  if (error && !note) return (
    <ReaderShell selectedRef={null} selectedSourceKey={null} docking={docking}>
      <p className="p-4 font-mono text-[11px] text-rose-300">{error}</p>
    </ReaderShell>
  );
  if (!note) {
    return (
      <ReaderShell selectedRef={null} selectedSourceKey={null} docking={docking}>
        <p className="p-4 font-mono text-[11px] text-cyan-200/40">
          Select an article in Knowledge or click a graph node to read it here.
        </p>
      </ReaderShell>
    );
  }

  if (note.kind === "task" && task && draft) {
    const taskChildren = articleNode?.children ?? note.children ?? task.subtask_refs ?? [];
    const container = taskChildren.length > 0;
    const running = task.status === "running";
    const trigger = triggerFor(task, taskParent);
    return (
      <ReaderShell selectedRef={note.ref} selectedSourceKey={null} docking={docking}>
      <div className="h-full overflow-y-auto p-3">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-[9px] uppercase tracking-[0.25em] text-cyan-300/40">
              {container ? `task · ${taskChildren.length} subtasks` : "task"} · {note.ref}
            </p>
            <h1 className="mt-1 truncate font-mono text-[15px] uppercase tracking-[0.12em] text-cyan-50">
              {draft.title}
            </h1>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <AutoCurateControl enabled={Boolean(note.auto_curate)} busy={curationBusy}
              onChange={(enabled) => void toggleAutoCurate(enabled)} />
            <button type="button" onClick={() => editing ? cancelEdit() : setEditing(true)} disabled={running}
              className="flex items-center gap-1 rounded border border-cyan-300/25 px-2 py-1 font-mono text-[8px] uppercase tracking-[0.12em] text-cyan-200/70 hover:border-cyan-300/50 hover:text-cyan-50 disabled:opacity-35">
              {editing ? <X size={9} /> : <Pencil size={9} />} {editing ? "Cancel" : "Edit"}
            </button>
            {!container ? (
              <span className={`rounded border px-2 py-1 font-mono text-[9px] uppercase tracking-[0.14em] ${TASK_STATUS_STYLE[task.status] ?? TASK_STATUS_STYLE.draft}`}>
                {task.status === "running" ? "● running" : task.status}
              </span>
            ) : null}
          </div>
        </div>

        <div className={`mb-3 rounded border p-2 ${running ? "border-emerald-300/25 bg-emerald-300/[0.035]" : "border-cyan-300/12 bg-[#020a12]"}`}>
          <p className="font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
            Trigger · {trigger.kind}
          </p>
          <p className={`mt-1 font-mono text-[10px] ${running ? "text-emerald-200" : "text-cyan-100/70"}`}>{trigger.detail}</p>
          {trigger.nextRun ? <p className="mt-1 font-mono text-[8px] text-cyan-300/45">{trigger.nextRun}</p> : null}
          {running ? (
            <p className="mt-1 font-mono text-[8px] text-emerald-300/70">
              {container ? "Task group running — follow the active subtask in Tasks or Action Trace." : "Running now — live actions are in Terminal → Action Trace."}
            </p>
          ) : null}
          {task.last_run ? <p className="mt-1 font-mono text-[8px] text-cyan-300/35">Last run: {task.last_run}</p> : null}
          {task.blocked_reason ? <p className="mt-1 font-mono text-[9px] text-rose-300/80">{task.blocked_reason}</p> : null}
        </div>

        <div className="space-y-2 rounded border border-cyan-300/12 bg-[#03101a]/55 p-2.5">
          <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
            Title
              <input value={draft.title} disabled={running || !editing}
              onChange={(event) => updateDraft({ title: event.target.value })}
              className={`${FIELD_CLASS} mt-1`} />
          </label>

          <div className="grid grid-cols-2 gap-2">
            <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
              Model
              <select value={draft.model} disabled={running || !editing}
                onChange={(event) => updateDraft({ model: event.target.value })}
                className={`${FIELD_CLASS} mt-1`}>
                <option value="auto">Automatic · {task.resolved_model}</option>
                {models.filter((model) => model.task_capable).map((model) => (
                  <option key={model.id} value={model.id} disabled={!model.available}>
                    {model.label} · {model.quantization}{model.loaded ? " · loaded" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
              Reasoning
              <select value={draft.reasoning_effort} disabled={running || !editing}
                onChange={(event) => updateDraft({ reasoning_effort: event.target.value as ReasoningEffort })}
                className={`${FIELD_CLASS} mt-1`}>
                <option value="none">None</option><option value="low">Low</option>
                <option value="medium">Medium</option><option value="high">High</option>
                <option value="xhigh">XHigh</option>
              </select>
            </label>
          </div>

          {!container ? (
            <>
              <div className="grid grid-cols-2 gap-2">
                <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
                  Agent
                  <select value={draft.assignee} disabled={running || !editing}
                    onChange={(event) => updateDraft({ assignee: event.target.value })}
                    className={`${FIELD_CLASS} mt-1`}>
                    <option value="">Unassigned</option>
                    {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.title}</option>)}
                  </select>
                </label>
                <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
                  Runbook
                  <select value={draft.runbook} disabled={running || !editing}
                    onChange={(event) => updateDraft({ runbook: event.target.value })}
                    className={`${FIELD_CLASS} mt-1`}>
                    <option value="">No runbook</option>
                    {runbooks.map((runbook) => <option key={runbook.id} value={runbook.id}>{runbook.title}</option>)}
                  </select>
                </label>
              </div>
            </>
          ) : null}

          <div className="grid grid-cols-2 gap-2">
            <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
              Schedule
              <select value={taskParent ? "parent" : draft.schedule ? "schedule" : "none"}
                disabled={running || !editing || Boolean(taskParent)}
                onChange={(event) => updateDraft({
                  schedule: event.target.value === "schedule" ? "0 * * * *" : "",
                })}
                className={`${FIELD_CLASS} mt-1`}>
                {taskParent ? <option value="parent">Parent task · {taskParent.title}</option> : null}
                <option value="schedule">Scheduled</option>
                <option value="none">No schedule</option>
              </select>
            </label>
            {!taskParent && draft.schedule ? (
              <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
                Schedule
                <input value={draft.schedule} disabled={running || !editing} placeholder="cron, e.g. 0 * * * *"
                  onChange={(event) => updateDraft({ schedule: event.target.value })}
                  className={`${FIELD_CLASS} mt-1`} />
              </label>
            ) : <span />}
          </div>

          {task.triggers.length ? (
            <div className="rounded border border-cyan-300/10 bg-cyan-300/[0.025] px-2 py-1.5">
              <p className="font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">Event triggers</p>
              <p className="mt-1 font-mono text-[10px] text-cyan-100/70">{task.triggers.join(" · ")}</p>
            </div>
          ) : null}

          <label className="block font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">
            Task instructions
            <textarea value={draft.body} disabled={running || !editing} rows={7}
              onChange={(event) => updateDraft({ body: event.target.value })}
              className={`${FIELD_CLASS} mt-1 resize-y leading-4`} />
          </label>

          {container ? (
            <div>
              <p className="mb-1 font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">Subtasks</p>
              <div className="flex flex-wrap gap-1">
                {taskChildren.map((ref) => (
                  <button key={ref} onClick={() => openReader(cleanLink(ref))}
                    className="rounded border border-cyan-300/20 px-2 py-1 font-mono text-[9px] text-cyan-100/70 hover:border-cyan-300/45 hover:text-cyan-50">
                    {cleanLink(ref).split("/").pop()}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {error ? <p className="font-mono text-[9px] text-rose-300">{error}</p> : null}
          {notice ? <p className="font-mono text-[9px] text-emerald-300/75">{notice}</p> : null}
          <div className="flex gap-2 pt-1">
            <button onClick={() => void saveTask()} disabled={!editing || !dirty || saving || running || !draft.title.trim()}
              className="flex items-center gap-1 rounded border border-cyan-300/35 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-100 hover:bg-cyan-300/10 disabled:opacity-35">
              <Save size={10} /> {saving ? "Saving" : "Save task"}
            </button>
            {!container ? (
              <button onClick={() => void runNow()} disabled={launching || running || !draft.runbook}
                className="flex items-center gap-1 rounded border border-emerald-300/35 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.14em] text-emerald-200 hover:bg-emerald-300/10 disabled:opacity-35">
                <Play size={10} /> {running ? "Running" : launching ? "Starting" : dirty ? "Save + run" : "Run now"}
              </button>
            ) : null}
          </div>
        </div>
      </div>
      </ReaderShell>
    );
  }

  const childRefs = note.children ?? articleNode?.children ?? [];
  const childLabel = CHILD_LABELS[note.kind] ?? "Children";
  const indexArticle = childRefs.length > 0;
  const articleCount = Number.parseInt(note.meta.articles ?? "", 10);
  const subnodeCount = Number.parseInt(note.meta.subnodes ?? "", 10);

  return (
    <ReaderShell selectedRef={note.ref} selectedSourceKey={null} docking={docking}>
      <div className="h-full overflow-y-auto px-5 py-4">
        <div className={`mx-auto w-full pb-8 ${indexArticle ? "max-w-[920px]" : "max-w-[78ch]"}`}>
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3 border-b border-cyan-300/10 pb-4">
            <div className="min-w-[220px] flex-1">
              {indexArticle && !editing ? (
                <p className="mb-1.5 font-mono text-[8px] uppercase tracking-[0.24em] text-cyan-300/45">Knowledge index</p>
              ) : null}
              {editing ? (
                <input value={articleDraft?.title ?? ""}
                  onChange={(event) => updateArticleDraft({ title: event.target.value })}
                  className={`${FIELD_CLASS} min-w-0 text-[13px] tracking-[0.04em]`} />
              ) : (
                <h1 className={`font-mono font-semibold text-cyan-50 ${indexArticle
                  ? "text-[22px] leading-tight tracking-[0.025em]"
                  : "text-[18px] leading-snug tracking-[0.04em]"}`}>
                  {note.title}
                </h1>
              )}
              {indexArticle && !editing ? (
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {Number.isFinite(subnodeCount) && subnodeCount > 0 ? (
                    <span className="rounded-full border border-cyan-300/15 bg-cyan-300/[0.035] px-2 py-0.5 font-mono text-[8px] uppercase tracking-[0.12em] text-cyan-200/55">
                      {subnodeCount} {subnodeCount === 1 ? "subnode" : "subnodes"}
                    </span>
                  ) : null}
                  {Number.isFinite(articleCount) ? (
                    <span className="rounded-full border border-cyan-300/15 bg-cyan-300/[0.035] px-2 py-0.5 font-mono text-[8px] uppercase tracking-[0.12em] text-cyan-200/55">
                      {articleCount} {articleCount === 1 ? "article" : "articles"}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
              <AutoCurateControl enabled={Boolean(note.auto_curate)} busy={curationBusy}
                onChange={(enabled) => void toggleAutoCurate(enabled)} />
              {!editing ? (
                <ReaderWikiActionControls
                  actions={wikiActions}
                  busy={wikiLaunching}
                  onAction={(ref) => void runWikiAction(ref)}
                />
              ) : null}
              <button type="button" onClick={() => editing ? cancelEdit() : setEditing(true)}
                className="flex shrink-0 items-center gap-1 rounded border border-cyan-300/25 px-2 py-1 font-mono text-[8px] uppercase tracking-[0.12em] text-cyan-200/70 hover:border-cyan-300/50 hover:text-cyan-50">
                {editing ? <X size={9} /> : <Pencil size={9} />} {editing ? "Cancel" : "Edit"}
              </button>
            </div>
          </div>
          {editing ? (
            <div className="space-y-2">
              <textarea value={articleDraft?.body ?? ""} rows={18}
                onChange={(event) => updateArticleDraft({ body: event.target.value })}
                className={`${FIELD_CLASS} resize-y leading-4`} />
              <div className="flex gap-2">
                <button type="button" onClick={() => void saveArticle()}
                  disabled={!dirty || saving || !articleDraft?.title.trim()}
                  className="flex items-center gap-1 rounded border border-cyan-300/35 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-100 hover:bg-cyan-300/10 disabled:opacity-35">
                  <Save size={10} /> {saving ? "Saving" : "Save article"}
                </button>
                <button type="button" onClick={cancelEdit}
                  className="flex items-center gap-1 rounded border border-cyan-300/20 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.14em] text-cyan-200/60 hover:text-cyan-50">
                  <X size={10} /> Cancel
                </button>
              </div>
            </div>
          ) : indexArticle ? (
            <IndexArticleContent note={note} />
          ) : (
            <ArticleMarkdown content={note.body} variant="reader" onNavigate={openReader} />
          )}
          {error ? <p className="mt-3 font-mono text-[9px] text-rose-300">{error}</p> : null}
          {notice ? <p className="mt-3 font-mono text-[9px] text-emerald-300/75">{notice}</p> : null}
          {!editing && !indexArticle && childRefs.length ? (
            <div className="mt-5 border-t border-cyan-300/10 pt-4">
              <p className="mb-2 font-mono text-[8px] uppercase tracking-[0.16em] text-cyan-300/45">{childLabel}</p>
              <div className="flex flex-wrap gap-1.5">
                {childRefs.map((ref) => (
                  <button key={ref} onClick={() => openReader(cleanLink(ref))}
                    className="rounded border border-cyan-300/20 px-2 py-1 font-mono text-[9px] text-cyan-100/70 hover:border-cyan-300/45 hover:text-cyan-50">
                    {articleNode?.synthetic
                      ? cleanLink(ref).split("/").pop()?.split(".").pop()
                      : cleanLink(ref).split("/").pop()}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </ReaderShell>
  );
}
