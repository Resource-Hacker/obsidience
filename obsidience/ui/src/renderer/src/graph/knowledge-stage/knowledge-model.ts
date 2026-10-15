/** The Knowledge stage's model of one accepted vault snapshot. Structure: root
 *  "Executive" -> knowledge branches -> notes, plus literal agent satellites and
 *  the separate curated Library satellite. Wikilinks render as cross-link
 *  tendrils distinct from hierarchy edges. Pure: no React state or Scene. */

import type {
  Knowledge3dLabelMeta,
  Knowledge3dRenderEdge,
  Knowledge3dRenderNode,
} from "@/graph/knowledge/knowledge-3d-scene";
import { knowledgeAgentNodeId } from "@/graph/knowledge/knowledge-3d";
import { layoutKnowledgeGraph } from "@/graph/knowledge/knowledge-layout";
import type { KnowledgeLayoutAnchor } from "@/graph/knowledge/knowledge-geometry";
import {
  knowledgeAmbientEdgeStroke,
  knowledgeNodeBaseAlpha,
  knowledgeNodeRadius,
  knowledgeSubjectGlowScale,
  knowledgeSubjectRingScale,
  knowledgeSubjectRingWidth,
  nodeCoreColor,
  paletteForAgent,
  paletteForBranch,
} from "@/graph/knowledge/knowledge-paint";
import type { GraphLink, GraphNavigation, GraphNavigationGroup, GraphNode } from "@/lib/api";
import { projectedAutoCuratedRefs } from "./graph-curation";
import { graphArticleIds, projectedArticleLinks, visibleArticleLinks, withoutTaxonomyLinks } from "./graph-links";
import {
  PRIMITIVE_FOLDER_BY_KIND,
  hierarchyParents,
  isArticleEndpoint,
  primitiveKindOf,
  type CloudInputs,
  type ReviewScope,
} from "./cloud-parts";
import { agentSatellite, librarySatellite } from "./satellites";

export const ROOT_ID = "@vault";

/** A label's second line: the branch a node lives in and what it is there. */
function labelNote(node: Knowledge3dRenderNode, branch: string): string | undefined {
  if (node.role === "root") return undefined;
  return `${branch} \u00b7 ${node.role === "section" ? `level ${node.depth ?? 0}` : "article"}`;
}

export interface VaultGraphSnapshot {
  nodes: GraphNode[];
  links: GraphLink[];
  auto_curated: string[];
  auto_curate_resolved: boolean;
  navigation: GraphNavigation;
}

/** Retain live status for node paint as well as durable graph changes.
 * Canonicalize unordered top-level collections; authored child arrays stay
 * ordered. The scene preserves cooling across paint-only refreshes. */
export function graphSnapshotFingerprint(snapshot: VaultGraphSnapshot): string {
  return JSON.stringify({
    nodes: [...snapshot.nodes].sort((left, right) => left.id.localeCompare(right.id)),
    links: [...snapshot.links].sort((left, right) =>
      left.source.localeCompare(right.source) || left.target.localeCompare(right.target)),
    auto_curated: [...snapshot.auto_curated].sort(),
    auto_curate_resolved: snapshot.auto_curate_resolved,
    navigation: snapshot.navigation,
  });
}

export function buildKnowledgeModel(graph: VaultGraphSnapshot, displayAliases: ReadonlyMap<string, string>,
  hub: KnowledgeLayoutAnchor, viewport: { width: number; height: number },
  ringScales: { peers: number; branches: number; articles: number }) {
  const all = graph.nodes;
  const linkPairs = projectedArticleLinks(graph.links, displayAliases);
  const executiveGroup = graph.navigation.groups.find((group) => group.id === "executive");
  const autoCurated = projectedAutoCuratedRefs(
    graph.auto_curate_resolved ? graph.auto_curated : [], all,
    [
      ...graph.navigation.groups.flatMap((group) => group.subjects),
      ...(executiveGroup ? [{ id: ROOT_ID, article_ref: executiveGroup.root_ref }] : []),
    ],
  );
  const executiveSubjects = executiveGroup?.subjects ?? [];
  const executiveName = executiveGroup?.title
    ?? all.find((node) => node.id === "Agents/Executive/Executive")?.title
    ?? "Executive";
  // Literal specialists are discovered from the same navigation manifest
  // that names their Reader cards and graph subjects.
  const agentGroups = graph.navigation.groups.filter((group) =>
    !["executive", "library"].includes(group.id));
  const agentGroupByName = new Map(agentGroups.map((group) => [
    group.root_ref.split("/")[1], group,
  ]));
  const agentNames = [...agentGroupByName.keys()];
  const primitiveNotes = all.filter((n) => Boolean(primitiveKindOf(n)));
  // Shared Tool+Skill pairs and Tasks belong to the curated Library satellite.
  // Runbooks are synthesized per agent; all four primitive kinds project on
  // an agent only when that identity carries them.
  const executiveMembers = graphArticleIds(executiveGroup, displayAliases);
  const executivePrimitives = primitiveNotes.filter((node) => executiveMembers.has(node.id));
  const executiveParents = hierarchyParents(executivePrimitives, displayAliases);
  const executiveContainers = new Set(executiveParents.values());
  const agentIdentities = all.filter((node) => node.kind === "agent"
    && node.id.startsWith("Agents/") && node.id !== "Agents/Executive/Executive");
  // Other Brains remain navigation shortcuts, never membership expansion or
  // cross-link evidence (isArticleEndpoint excludes Agent nodes).
  const notes = [
    ...all.filter((node) => executiveMembers.has(node.id) && !primitiveKindOf(node)
      && !node.navigation_ref && node.id !== "Agents/Executive/Executive"),
    ...agentIdentities,
    ...executivePrimitives,
  ];
  const branchOf = (id: string): string | null => (id.includes("/") ? id.split("/", 1)[0] : null);
  const primitiveFolders = ["Tools", "Skills", "Runbooks", "Tasks"];
  const folders = [...new Set(notes
    .filter((node) => !agentIdentities.includes(node) && !node.id.startsWith("Agents/Executive/")
      && !node.id.startsWith("@"))
    .map((n) => branchOf(n.id)).filter(Boolean))] as string[];
  const branches = folders
    .filter((folder) => folder !== "Library" && folder !== "@library"
      && !primitiveFolders.includes(folder)
      && !executiveSubjects.some((subject) => subject.id === `@branch/${folder}`))
    .sort();
  const folderPaths = [...new Set(notes.flatMap((node) => {
    if (agentIdentities.includes(node) || primitiveKindOf(node) || node.id.startsWith("@")) return [];
    const parts = node.id.split("/").slice(0, -1);
    if (parts.length < 2 || parts[0] === "Agents") return [];
    return parts.slice(1).map((_part, index) => parts.slice(0, index + 2).join("/"));
  }))].filter((path) => !executiveSubjects.some((subject) => subject.id === `@branch/${path}`)).sort();

  const degree = new Map<string, number>();
  const executiveArticleIds = new Set(all.filter(isArticleEndpoint)
    .map((node) => displayAliases.get(node.id) ?? node.id)
    .filter((ref) => executiveMembers.has(ref)));
  const crossLinks = visibleArticleLinks(linkPairs, executiveArticleIds, "Agents/Executive/Executive",
    new Set(executiveGroup?.article_refs ?? []));
  for (const l of crossLinks) {
    degree.set(l.source, (degree.get(l.source) ?? 0) + 1);
    degree.set(l.target, (degree.get(l.target) ?? 0) + 1);
  }

  const executiveParentOf = (node: GraphNode): string => {
    const container = executiveParents.get(node.id);
    if (container) return container;
    const primitiveKind = primitiveKindOf(node);
    if (primitiveKind) return `@branch/${PRIMITIVE_FOLDER_BY_KIND[primitiveKind]}`;
    if (node.kind === "agent") return "@agent/Specialists";
    if (node.parent_id) return node.parent_id;
    if (node.id.startsWith("Agents/Executive/Architecture/")) return "@agent/Architecture";
    if (node.id.startsWith("Agents/Executive/Observations/")) return "@agent/Observations";
    const directory = node.id.split("/").slice(0, -1).join("/");
    if (directory.includes("/")) return `@branch/${directory}`;
    const branch = branchOf(node.id);
    return branch ? `@branch/${branch}` : ROOT_ID;
  };

  // Hierarchy input: the root Agent Brain Article directly owns its agent
  // subjects and world-knowledge branches.
  const layoutNodes = [
    { id: ROOT_ID, degree: branches.length + executiveSubjects.filter((subject) => !subject.parent_id).length,
      kind: "concept" as never, label: executiveName, role: "root" as never, parentId: null, order: 0 },
    ...branches.map((b, i) => ({
      id: `@branch/${b}`, degree: notes.filter((n) => branchOf(n.id) === b).length,
      kind: "concept" as never, label: b, role: "section" as never, parentId: ROOT_ID, order: i,
    })),
    ...executiveSubjects.map((subject, index) => ({
      id: subject.id,
      degree: subject.id === "@agent/Specialists"
        ? agentIdentities.length
        : executivePrimitives.filter((node) =>
          subject.id === `@branch/${PRIMITIVE_FOLDER_BY_KIND[primitiveKindOf(node) ?? ""]}`).length,
      kind: "concept" as never,
      label: subject.title,
      role: "section" as never,
      parentId: subject.parent_id ?? ROOT_ID,
      order: index,
    })),
    ...folderPaths.map((path, index) => ({
      id: `@branch/${path}`,
      degree: notes.filter((node) => node.id.startsWith(`${path}/`)).length,
      kind: "concept" as never,
      label: path.split("/").pop() ?? path,
      role: "section" as never,
      parentId: `@branch/${path.split("/").slice(0, -1).join("/")}`,
      order: index,
    })),
    ...notes.map((n, i) => {
      const isContainer = executiveContainers.has(n.id);
      return {
        id: n.id, degree: degree.get(n.id) ?? 0, kind: "note" as never,
        label: n.title,
        role: (isContainer ? "section" : "claim") as never,
        parentId: executiveParentOf(n),
        order: i,
      };
    }),
  ];
  const taxonomyEdges = layoutNodes
    .filter((n) => n.parentId)
    .map((n, i) => ({ id: `t${i}`, source: n.parentId as string, target: n.id, type: "related_to" as never }));
  const crossEdges = withoutTaxonomyLinks(crossLinks, layoutNodes).map((l, i) => ({
    id: `x${i}`, source: l.source, target: l.target, type: "related_to" as never,
  }));

  const layout = layoutKnowledgeGraph({
    anchor: hub,
    viewport: {
      width: viewport.width,
      height: viewport.height,
      bounds: { left: 0, right: viewport.width, top: 0, bottom: viewport.height },
    },
    nodes: layoutNodes,
    edges: [...taxonomyEdges, ...crossEdges],
    ringScales,
    circularStage: true,
  });
  const pos = new Map(layout.nodes.map((n) => [n.id, n]));
  const meta = new Map(notes.map((n) => [n.id, n]));
  const titles = new Map<string, string>([
    [ROOT_ID, executiveName],
    ...branches.map((b) => [`@branch/${b}`, b] as [string, string]),
    ...executiveSubjects.map((subject) => [subject.id, subject.title] as [string, string]),
    ...folderPaths.map((path) => [`@branch/${path}`, path.split("/").pop() ?? path] as [string, string]),
    ...notes.map((n) => [n.id, n.title] as [string, string]),
  ]);

  const firstLevelBranchOf = (id: string): string | null => {
    if (id === ROOT_ID) return null;
    let cursor = pos.get(id);
    while (cursor?.parentId && cursor.parentId !== ROOT_ID) cursor = pos.get(cursor.parentId);
    if (cursor?.id.startsWith("@branch/")) return cursor.id.slice(8);
    if (cursor?.id.startsWith("@agent/")) return cursor.id.slice(7);
    return branchOf(cursor?.id ?? id);
  };
  const paletteOf = (id: string) => paletteForBranch(firstLevelBranchOf(id));

  // Every node inherits the palette owned by its direct Brain child.
  const renderNodes: Knowledge3dRenderNode[] = layout.nodes.map((p) => {
    const role = p.role as never as ("root" | "section" | "claim" | undefined);
    const palette = paletteOf(p.id);
    const subject = role === "root" || role === "section";
    const noteMeta = meta.get(p.id);
    return {
      id: p.id, x: p.x, y: p.y, depth: p.depth, role, parentId: p.parentId,
      radius: knowledgeNodeRadius(role, degree.get(p.id) ?? 0, false, p.depth),
      subject,
      core: nodeCoreColor(palette, role, noteMeta?.status),
      dark: palette.dark,
      ring: subject || autoCurated.has(p.id) ? palette.ring : "rgba(0,0,0,0)",
      glow: subject ? palette.glow : "rgba(0,0,0,0)",
      ringScale: knowledgeSubjectRingScale(p.depth),
      ringWidth: knowledgeSubjectRingWidth(role, p.depth),
      glowScale: subject ? knowledgeSubjectGlowScale(role, p.depth) : 1,
      alpha: knowledgeNodeBaseAlpha(role, p.depth, "hot"),
      autoCurated: autoCurated.has(p.id),
    };
  });
  const renderEdges: Knowledge3dRenderEdge[] = [
    // Taxonomy beams carry the full-saturation branch hue (original law).
    ...taxonomyEdges.map((e) => ({
      source: e.source, target: e.target, taxonomy: true,
      color: paletteOf(e.target).core,
    })),
    // Cross-links keep the dim 2D stroke and the REVERSED far-end gradient.
    ...crossEdges.map((e) => ({
      source: e.source, target: e.target, taxonomy: false,
      color: knowledgeAmbientEdgeStroke(false, false, paletteOf(e.source)),
      colorEnd: paletteOf(e.target).core,
    })),
  ];
  const reviewScopes = new Map<string, ReviewScope>([["main", { articleIds: executiveArticleIds, agentRef: "Agents/Executive/Executive",
    scopeRefs: new Set(executiveGroup?.article_refs ?? []), links: crossLinks,
    edgeColorEnd: (id) => paletteOf(id).core }]]);
  // ---- satellites: one ball per agent, seeded by its own mini hierarchy ----
  const inputs: CloudInputs = { all, displayAliases, linkPairs, autoCurated, reviewScopes, titles };
  const satellites = [
    ...agentNames.map((name) => agentSatellite(inputs, name, agentGroupByName.get(name) as GraphNavigationGroup)),
    librarySatellite(inputs, graph.navigation.groups.find((group) => group.id === "library")),
  ];
  const labelMetadata = new Map<string, Knowledge3dLabelMeta>();
  for (const node of renderNodes) {
    const branch = firstLevelBranchOf(node.id) ?? "brain";
    const palette = paletteOf(node.id);
    labelMetadata.set(node.id, {
      label: titles.get(node.id) ?? node.id,
      note: labelNote(node, branch),
      role: node.role === "root" || node.role === "section" ? node.role : "claim",
      depth: node.depth ?? 0,
      branch: branch.toLowerCase(),
      radius: node.radius,
      accent: palette.core,
    });
  }
  for (const satellite of satellites) {
    const palette = paletteForAgent(satellite.agentId);
    for (const node of satellite.nodes) {
      const id = knowledgeAgentNodeId(satellite.agentId, node.id);
      labelMetadata.set(id, {
        label: titles.get(id) ?? node.id,
        note: labelNote(node, satellite.agentId === "library" ? "knowledge" : "agent"),
        role: node.role === "root" || node.role === "section" ? node.role : "claim",
        depth: node.depth ?? 0,
        branch: satellite.agentId === "library" ? "knowledge" : "agent",
        radius: node.radius,
        accent: palette.core,
      });
    }
  }
  return { nodes: renderNodes, edges: renderEdges, satellites, labelMetadata, reviewScopes, articleLinks: linkPairs, titles };
}
