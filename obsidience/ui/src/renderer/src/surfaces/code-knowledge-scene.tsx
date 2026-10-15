/** The Code stage drawn by the Knowledge renderer: the Executive graph's glass
 *  layers, orbs, beams and thinking route, fed by the code provider's folders,
 *  files and symbols. The provider graph and its file lens stay the data; this
 *  only maps them onto the renderer's nodes, links and activity. */

import { useEffect, useMemo, useState } from "react";
import type { GraphControl, GraphPublisher } from "./graph-stream";
import type { GraphOperation, ProviderGraph, ProviderNode } from "./provider-graph-scene";
import { codeLayoutAncestry } from "./code-spherical-layout";
import {
  Knowledge3dScene,
  type Knowledge3dLabelMeta,
  type Knowledge3dRenderEdge,
  type Knowledge3dRenderNode,
} from "@/components/themes/obsidience/knowledge-3d-scene";
import { layoutKnowledgeGraph } from "@/components/themes/obsidience/knowledge-layout";
import {
  BRAIN_PALETTE,
  chromaticKnowledgePalette,
  knowledgeAmbientEdgeStroke,
  knowledgeNodeBaseAlpha,
  knowledgeNodeRadius,
  knowledgeSubjectGlowScale,
  knowledgeSubjectRingScale,
  knowledgeSubjectRingWidth,
  type KnowledgeBranchPalette,
} from "@/components/themes/obsidience/knowledge-paint";
import { CODE_GRAPH_ID, loadGraphTuning, onGraphThinkingTest, onGraphTuning } from "@/lib/graph-tuning";
import { claimShellKnowledgePresenter } from "@/lib/shell-client";
import { buildThinkingRoute } from "@/panes/thinking-route";
import { operationAccent, operationDeadline, type GraphOperation as ActivityOperation } from "@/panes/graph-activity";

/** Containment is the hierarchy; every other native relationship is a link. */
const CONTAINMENT = new Set(["HAS_BRANCH", "CONTAINS_FOLDER", "CONTAINS_FILE", "DEFINES", "DEFINES_METHOD"]);
const HUB = { x: 0.5, y: 0.5 } as const;
const TEST_MS = 6_000;

type Role = "root" | "section" | "claim";
interface CodeCloud {
  nodes: Knowledge3dRenderNode[];
  edges: Knowledge3dRenderEdge[];
  labels: Map<string, Knowledge3dLabelMeta>;
  /** Any provider id to the node that shows it (itself, its file or its nearest shown container). */
  shownAs: (id: string) => string | undefined;
}

function codeCloud(data: ProviderGraph, visibleIds: ReadonlySet<string>): CodeCloud {
  const {root, parents} = codeLayoutAncestry(data);
  const byId = new Map(data.nodes.map(node => [node.id, node]));
  // A file's Module wrapper shares the file's orb, as in the file lens.
  const files = new Map(data.nodes.filter(node => node.kind === "File" && node.file).map(node => [node.file!, node.id]));
  const folded = (node: ProviderNode) => node.kind === "Module" && node.name === node.file ? files.get(node.file!) : undefined;
  const shown = new Set(data.nodes.filter(node => visibleIds.has(node.id) && !folded(node)).map(node => node.id));
  if (root) shown.add(root.id);
  const shownAs = (id: string): string | undefined => {
    const node = byId.get(id);
    let cursor: string | undefined = node ? folded(node) ?? id : undefined;
    while (cursor && !shown.has(cursor)) cursor = parents.get(cursor);
    return cursor;
  };
  // Each shown node hangs from its nearest shown container.
  const parentOf = new Map<string, string>();
  for (const id of shown) {
    if (id === root?.id) continue;
    const parent = shownAs(parents.get(id) ?? "") ?? root?.id;
    if (parent && parent !== id) parentOf.set(id, parent);
  }
  const children = new Map<string, string[]>();
  for (const [child, parent] of parentOf) children.set(parent, [...children.get(parent) ?? [], child]);
  // A chain of sole containers below the root (project, branch, package
  // folder) folds into the core, so the first ring holds the real branches.
  let trunk = root?.id;
  for (;;) {
    const below = trunk ? children.get(trunk) ?? [] : [];
    const containers = below.filter(id => children.has(id));
    if (!trunk || containers.length !== 1 || !["Branch", "Folder"].includes(byId.get(containers[0])?.kind ?? "")) break;
    const next = containers[0];
    for (const child of children.get(next) ?? []) parentOf.set(child, trunk);
    children.set(trunk, [...below.filter(id => id !== next), ...children.get(next) ?? []]);
    parentOf.delete(next); shown.delete(next); children.delete(next);
  }
  const depthOf = new Map<string, number>(root ? [[root.id, 0]] : []);
  const depth = (id: string): number => {
    const known = depthOf.get(id);
    if (known !== undefined) return known;
    const parent = parentOf.get(id);
    const value = parent ? depth(parent) + 1 : 0;
    depthOf.set(id, value); return value;
  };
  // Every child of the core owns one hue, spaced around the whole wheel.
  const branches = (root ? children.get(root.id) ?? [] : []).filter(id => children.has(id))
    .sort((a, b) => (byId.get(a)?.name ?? a).localeCompare(byId.get(b)?.name ?? b));
  const palettes = new Map<string, KnowledgeBranchPalette>(branches.map((id, index) =>
    [id, chromaticKnowledgePalette(Math.round(index * 360 / branches.length), 86, 64)]));
  const branchOf = (id: string): string | undefined => {
    let cursor: string | undefined = id;
    while (cursor && parentOf.get(cursor) !== root?.id) cursor = parentOf.get(cursor);
    return cursor;
  };
  const paletteOf = (id: string) => palettes.get(branchOf(id) ?? "") ?? BRAIN_PALETTE;

  const ids = [...shown].sort();
  const links = new Map<string, {source: string; target: string}>();
  for (const edge of data.edges) {
    if (CONTAINMENT.has(edge.kind)) continue;
    const source = shownAs(edge.source), target = shownAs(edge.target);
    if (!source || !target || source === target || parentOf.get(source) === target || parentOf.get(target) === source) continue;
    const key = source < target ? `${source}|${target}` : `${target}|${source}`;
    if (!links.has(key)) links.set(key, {source, target});
  }
  const degree = new Map<string, number>();
  for (const {source, target} of links.values()) {
    degree.set(source, (degree.get(source) ?? 0) + 1); degree.set(target, (degree.get(target) ?? 0) + 1);
  }
  const roleOf = (id: string): Role => id === root?.id ? "root" : children.has(id) ? "section" : "claim";
  const layoutNodes = ids.map((id, order) => ({
    id, order, kind: (children.has(id) ? "concept" : "note") as never, label: byId.get(id)?.name ?? id,
    degree: children.get(id)?.length ?? degree.get(id) ?? 0, role: roleOf(id) as never,
    parentId: parentOf.get(id) ?? null,
  }));
  const layout = layoutKnowledgeGraph({
    nodes: layoutNodes,
    edges: layoutNodes.filter(node => node.parentId).map((node, index) => ({
      id: `c${index}`, source: node.parentId as string, target: node.id, type: "related_to" as never,
    })),
  });
  const positions = new Map(layout.nodes.map(node => [node.id, node]));
  const nodes: Knowledge3dRenderNode[] = ids.map(id => {
    const role = roleOf(id), level = depth(id), point = positions.get(id);
    const subject = role !== "claim", palette = paletteOf(id);
    return {
      id, x: point?.x ?? 0.5, y: point?.y ?? 0.5, depth: level, role, parentId: parentOf.get(id) ?? null,
      radius: knowledgeNodeRadius(role, degree.get(id) ?? 0, false, level),
      subject, core: palette.core, dark: palette.dark,
      ring: subject ? palette.ring : "rgba(0,0,0,0)",
      glow: subject ? palette.glow : "rgba(0,0,0,0)",
      ringScale: knowledgeSubjectRingScale(level),
      ringWidth: knowledgeSubjectRingWidth(role, level),
      glowScale: subject ? knowledgeSubjectGlowScale(role, level) : 1,
      alpha: knowledgeNodeBaseAlpha(role, level, "hot"),
    };
  });
  const edges: Knowledge3dRenderEdge[] = [
    // Taxonomy beams carry the full branch hue; links the dim stroke and the far end's hue.
    ...[...parentOf].map(([child, parent]) => ({
      source: parent, target: child, taxonomy: true, color: paletteOf(child).core,
    })),
    ...[...links.values()].map(({source, target}) => ({
      source, target, taxonomy: false,
      color: knowledgeAmbientEdgeStroke(false, false, paletteOf(source)), colorEnd: paletteOf(target).core,
    })),
  ];
  const labels = new Map<string, Knowledge3dLabelMeta>(nodes.map(node => {
    const native = byId.get(node.id), branch = branchOf(node.id);
    const name = native?.name ?? node.id;
    return [node.id, {
      label: (native?.external ? "↗ " : "") + name.slice(0, 74) + (name.length > 74 ? "…" : ""),
      note: node.role === "root" ? undefined : `${native?.kind ?? "code"} · ${native?.file ?? byId.get(branch ?? "")?.name ?? ""}`,
      role: node.role as Role, depth: node.depth ?? 0,
      branch: (byId.get(branch ?? "")?.name ?? "code").toLowerCase(), radius: node.radius, accent: paletteOf(node.id).core,
    }];
  }));
  return {nodes, edges, labels, shownAs};
}

export function CodeKnowledgeScene({data, visibleIds, operations, selectedId, visible,
  onPick, onHover, onCommand, onPublisher, onConsumers, onBack}: {
  data: ProviderGraph | null; visibleIds: ReadonlySet<string>; operations: readonly GraphOperation[];
  selectedId: string; visible: boolean;
  onPick: (node: ProviderNode | null) => void; onHover: (node: ProviderNode | null) => void;
  onCommand: (command: GraphControl) => void; onPublisher: (publisher: GraphPublisher | null) => void;
  onConsumers: (count: number) => void; onBack: () => void;
}) {
  const [tuning, setTuning] = useState(() => loadGraphTuning(CODE_GRAPH_ID));
  const [hovered, setHovered] = useState<string | null>(null);
  const [sceneKey, setSceneKey] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [test, setTest] = useState<{refs: string[]; key: string; until: number} | null>(null);
  useEffect(() => claimShellKnowledgePresenter("code"), []);
  useEffect(() => onGraphTuning(change => { if (change.graphId === CODE_GRAPH_ID) setTuning(change.tuning); }), []);
  const cloud = useMemo(() => data ? codeCloud(data, visibleIds) : null, [data, visibleIds]);
  const byId = useMemo(() => new Map((data?.nodes ?? []).map(node => [node.id, node])), [data]);
  // Settings' Test thinking lights a handful of files the way an agent's read would.
  useEffect(() => onGraphThinkingTest(graphId => {
    if (graphId !== CODE_GRAPH_ID || !cloud) return;
    const leaves = cloud.nodes.filter(node => node.role === "claim");
    const refs = [...leaves].sort(() => Math.random() - 0.5).slice(0, 6).map(node => node.id);
    setTest({refs, key: `test:${Date.now()}`, until: Date.now() + TEST_MS});
  }), [cloud]);

  // Operations light their nodes until their deadline; one timer per expiry.
  const live = useMemo(() => operations.filter(op => op.refs.length && op.status !== "running"
    && now < operationDeadline(op as unknown as ActivityOperation)), [operations, now]);
  useEffect(() => {
    const deadlines = [...live.map(op => operationDeadline(op as unknown as ActivityOperation)), test?.until ?? Infinity];
    const next = Math.min(...deadlines);
    if (!Number.isFinite(next)) return;
    const timer = window.setTimeout(() => { setNow(Date.now()); if (test && test.until <= Date.now()) setTest(null); },
      Math.max(1, next - Date.now()));
    return () => window.clearTimeout(timer);
  }, [live, test]);
  useEffect(() => setNow(Date.now()), [operations]);
  const activity = useMemo(() => {
    if (!cloud) return null;
    const accents = new Map<string, {color: string; mode: number}>();
    const refs: string[] = [];
    const aliases = new Map<string, string>();
    for (const node of data?.nodes ?? []) {
      if (node.qualified_name) aliases.set("qn:" + node.qualified_name, node.id);
      if (node.kind === "File" && node.file) aliases.set("file:" + node.file, node.id);
    }
    for (const op of live) {
      const accent = operationAccent(op as unknown as ActivityOperation);
      for (const ref of op.refs) {
        const id = cloud.shownAs(aliases.get(ref) ?? ref);
        if (!id) continue;
        refs.push(id);
        if (accent) accents.set(id, accent);
      }
    }
    if (test) refs.push(...test.refs);
    const route = refs.length ? buildThinkingRoute(cloud, refs, [refs]) : null;
    return route ? {route, accents, key: test?.key ?? live[0]?.id ?? "code"} : null;
  }, [cloud, data, live, test]);
  const selection = useMemo(() => {
    const id = selectedId ? cloud?.shownAs(selectedId) : undefined;
    const route = id && cloud ? buildThinkingRoute(cloud, [id]) : null;
    return id && route ? {agentId: "main", id, spec: route.pathSpec} : null;
  }, [cloud, selectedId]);
  const labelIds = useMemo(() => [hovered, selection?.id].filter((id): id is string => !!id), [hovered, selection]);

  return <div className="absolute inset-0" onContextMenu={event => { event.preventDefault(); onBack(); }}>
    <Knowledge3dScene
      key={sceneKey}
      sharePresentation
      presentationSource="code"
      primaryGraphId={CODE_GRAPH_ID}
      onPresentationReady={onPublisher}
      onPresentationConsumers={onConsumers}
      onPresentationCommand={onCommand}
      nodes={cloud?.nodes ?? []}
      edges={cloud?.edges ?? []}
      hub={HUB}
      focusNodeIds={activity?.route.nodeIds ?? new Set<string>()}
      passedNodeIds={activity?.route.passedIds}
      pathSpec={activity?.route.pathSpec ?? null}
      focusActive={Boolean(activity)}
      focusKey={activity?.key ?? 0}
      focusPhase={activity ? "thinking" : null}
      activityAccents={activity?.accents}
      selectionPath={selection}
      visible={visible}
      reducedMotion={false}
      adapterPreference="system"
      animationProfile="maximum"
      hoveredNodeId={hovered}
      labelIds={labelIds}
      showActivityLabels
      labelMetadata={cloud?.labels ?? new Map()}
      tuning={tuning}
      cameraFocus={selection ? {agentId: null, nodeId: selection.id} : null}
      onBackgroundClick={() => onPick(null)}
      onHover={id => { setHovered(id); onHover(id ? byId.get(id) ?? null : null); }}
      onNodeAction={(kind, id) => { if (kind === "click") onPick(byId.get(id) ?? null); }}
      onContextLost={() => setSceneKey(key => key + 1)}
    />
  </div>;
}
