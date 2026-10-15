/** The Knowledge stage's satellite clouds: one ball per specialist Agent,
 *  seeded by its own mini hierarchy, and the shared green Library. The Library
 *  never enters the Executive article tree. */

import type { GraphNavigationGroup, GraphNode } from "@/lib/api";
import type { Knowledge3dRenderEdge, Knowledge3dRenderNode } from "@/graph/knowledge/knowledge-3d-scene";
import { layoutKnowledgeGraph } from "@/graph/knowledge/knowledge-layout";
import {
  knowledgeAmbientEdgeStroke,
  knowledgeNodeBaseAlpha,
  knowledgeNodeRadius,
  knowledgeSubjectGlowScale,
  knowledgeSubjectRingScale,
  knowledgeSubjectRingWidth,
  nodeCoreColor,
  paletteForAgent,
} from "@/graph/knowledge/knowledge-paint";
import { graphArticleIds, visibleArticleLinks, withoutTaxonomyLinks } from "./graph-links";
import { PRIMITIVE_FOLDER_BY_KIND, hierarchyParents, isArticleEndpoint, primitiveKindOf, type CloudInputs } from "./cloud-parts";

export interface SatelliteCloud {
  agentId: string;
  nodes: Knowledge3dRenderNode[];
  edges: Knowledge3dRenderEdge[];
}

/** One specialist's ball from its navigation group. */
export function agentSatellite(inputs: CloudInputs, name: string, navigationGroup: GraphNavigationGroup): SatelliteCloud {
  const { all, displayAliases, linkPairs, autoCurated, reviewScopes, titles } = inputs;
  const identityRef = navigationGroup.root_ref;
  const satelliteSubjects = navigationGroup.subjects;
  const subjectArticleRefs = new Set(satelliteSubjects.flatMap((subject) =>
    subject.article_ref ? [subject.article_ref] : []));
  const satelliteSubjectByKey = new Map(satelliteSubjects.map((subject) => [
    subject.id.slice(subject.id.lastIndexOf("/") + 1), subject,
  ]));
  const satelliteSubjectId = (key: string): string =>
    satelliteSubjectByKey.get(key)?.id ?? identityRef;
  const satelliteMembers = graphArticleIds(navigationGroup, displayAliases);
  const localMembers = all.filter((node) => satelliteMembers.has(node.id)
    && !subjectArticleRefs.has(node.id) && node.id !== identityRef);
  const otherAgentMembers = [
    ...all.filter((node) => node.kind === "agent" && node.id !== identityRef),
  ];
  // These Brain shortcuts preserve Other Agents navigation, not its scope.
  const members = [...localMembers, ...otherAgentMembers.filter((node) => !localMembers.includes(node))];
  const primitiveMembers = members.filter((member) => Boolean(primitiveKindOf(member)));
  const primitiveParents = hierarchyParents(primitiveMembers, displayAliases);
  const primitiveContainers = new Set(primitiveParents.values());
  const satelliteArticleIds = new Set(all.filter(isArticleEndpoint)
    .map((node) => displayAliases.get(node.id) ?? node.id)
    .filter((ref) => satelliteMembers.has(ref)));
  const satelliteParentOf = (node: GraphNode): string => {
    const primitiveParent = primitiveParents.get(node.id);
    if (primitiveParent) return primitiveParent;
    const primitiveKind = primitiveKindOf(node);
    if (primitiveKind) return satelliteSubjectId(PRIMITIVE_FOLDER_BY_KIND[primitiveKind].toLowerCase());
    if (otherAgentMembers.includes(node)) return satelliteSubjectId("other-agents");
    if (node.parent_id) return node.parent_id;
    const folder = node.id.split("/").slice(0, -1).join("/");
    const subject = satelliteSubjects.find((item) => item.path === folder);
    if (subject) return subject.id;
    if (name === "Darwin" && node.id.startsWith("Sources/")) {
      return satelliteSubjectId("sources");
    }
    return satelliteSubjectId("observations");
  };
  const satLayoutNodes = [
    { id: identityRef, degree: members.length, kind: "concept" as never, label: navigationGroup.title, role: "root" as never, parentId: null as string | null, order: 0 },
    ...satelliteSubjects.map((subject, index) => ({
      id: subject.id,
      degree: primitiveMembers.filter((member) => {
        const kind = primitiveKindOf(member);
        return Boolean(kind) && subject.id === satelliteSubjectId(
          PRIMITIVE_FOLDER_BY_KIND[kind as string].toLowerCase(),
        );
      }).length,
      kind: "concept" as never,
      label: subject.title,
      role: "section" as never,
      parentId: subject.parent_id ?? identityRef,
      order: index,
    })),
    ...members.map((n, i) => ({
      id: n.id, degree: 0, kind: "note" as never,
      label: n.title,
      role: (primitiveContainers.has(n.id) ? "section" : "claim") as never,
      parentId: satelliteParentOf(n),
      order: i,
    })),
  ];
  const satLayout = layoutKnowledgeGraph({
    nodes: satLayoutNodes,
    edges: satLayoutNodes.filter((n) => n.parentId)
      .map((n, i) => ({ id: `s${i}`, source: n.parentId as string, target: n.id, type: "related_to" as never })),
  });
  const satPos = new Map(satLayout.nodes.map((n) => [n.id, n]));
  const pal = paletteForAgent(name);
  const memberSet = new Set(satLayoutNodes.map((n) => n.id));
  const satNodes: Knowledge3dRenderNode[] = satLayoutNodes.map((ln) => {
    const pp = satPos.get(ln.id);
    const role = ln.role as never as ("root" | "section" | "claim");
    const subject = role === "root" || role === "section";
    const noteMeta = all.find((n) => n.id === ln.id);
    return {
      id: ln.id, x: pp?.x ?? 0.5, y: pp?.y ?? 0.5, depth: pp?.depth,
      role, parentId: pp?.parentId,
      radius: knowledgeNodeRadius(role, 1, false, pp?.depth),
      subject,
      core: nodeCoreColor(pal, subject ? role : undefined, noteMeta?.status),
      dark: pal.dark,
      ring: subject || autoCurated.has(ln.id) ? pal.ring : "rgba(0,0,0,0)",
      glow: subject ? pal.glow : "rgba(0,0,0,0)",
      ringScale: knowledgeSubjectRingScale(pp?.depth),
      ringWidth: knowledgeSubjectRingWidth(subject ? role : undefined, pp?.depth),
      glowScale: subject ? knowledgeSubjectGlowScale(role, pp?.depth) : 1,
      alpha: knowledgeNodeBaseAlpha(subject ? role : undefined, pp?.depth, "hot"),
      autoCurated: autoCurated.has(ln.id),
    };
  });
  const satelliteLinks = visibleArticleLinks(linkPairs, satelliteArticleIds, identityRef,
    new Set(navigationGroup.article_refs ?? []));
  reviewScopes.set(name, { articleIds: satelliteArticleIds, agentRef: identityRef,
    scopeRefs: new Set(navigationGroup.article_refs ?? []), links: satelliteLinks,
    edgeColorEnd: () => pal.core });
  const satEdges: Knowledge3dRenderEdge[] = [
    ...satLayoutNodes.filter((n) => n.parentId)
      .map((n) => ({ source: n.parentId as string, target: n.id, taxonomy: true, color: pal.core })),
    ...withoutTaxonomyLinks(satelliteLinks, satLayoutNodes)
      .map((l) => ({ source: l.source, target: l.target, taxonomy: false,
                     color: knowledgeAmbientEdgeStroke(false, false, pal), colorEnd: pal.core })),
  ];
  for (const ref of memberSet) {
    const n = all.find((x) => x.id === ref);
    titles.set(`agent:${name}/${ref}`,
      n ? n.title
        : (ref === identityRef ? navigationGroup.title
          : satelliteSubjects.find((subject) => subject.id === ref)?.title ?? ref));
  }
  return {
    agentId: name,
    nodes: satNodes,
    edges: satEdges,
  };
}

/** The shared green Library. Tool nodes represent the one-to-one Tool+Skill
 *  pairs beside Tasks; synthesized Runbooks remain on their owning agents. */
export function librarySatellite(inputs: CloudInputs, libraryGroup: GraphNavigationGroup | undefined): SatelliteCloud {
  const { all, displayAliases, linkPairs, autoCurated, reviewScopes, titles } = inputs;
  const libraryMembers = graphArticleIds(libraryGroup, displayAliases);
  const absorbedLibraryRefs = new Set((libraryGroup?.subjects ?? []).flatMap((subject) =>
    subject.article_ref ? [subject.article_ref] : []));
  const libraryNotes = all.filter((node) => libraryMembers.has(displayAliases.get(node.id) ?? node.id)
    && !absorbedLibraryRefs.has(node.id)
    && node.kind !== "skill");
  const libraryRoot = libraryGroup?.root_ref ?? "@library";
  const libraryTitle = libraryGroup?.title ?? "Library";
  const librarySubjects = libraryGroup?.subjects ?? [];
  const librarySubjectByKind = new Map<string, string>([
    ["tool", librarySubjects.find((subject) => subject.id === "@library/Tools")?.id ?? libraryRoot],
    ["task", librarySubjects.find((subject) => subject.id === "@library/Tasks")?.id ?? libraryRoot],
    ["runbook", librarySubjects.find((subject) => subject.id === "@library/Runbooks")?.id ?? libraryRoot],
    ["agent", librarySubjects.find((subject) => subject.id === "@library/Agents")?.id ?? libraryRoot],
  ]);
  const libraryParents = hierarchyParents(libraryNotes, displayAliases);
  const libraryContainers = new Set(libraryParents.values());
  const libraryArticleIds = new Set(all.filter(isArticleEndpoint)
    .map((node) => displayAliases.get(node.id) ?? node.id).filter((id) => libraryMembers.has(id)));
  const libraryLayoutNodes = [
    { id: libraryRoot, degree: libraryNotes.length, kind: "concept" as never, label: libraryTitle, role: "root" as never, parentId: null as string | null, order: 0 },
    ...librarySubjects.map((subject, index) => ({
      id: subject.id,
      degree: libraryNotes.filter((node) =>
        librarySubjectByKind.get(primitiveKindOf(node) ?? "") === subject.id).length,
      kind: "concept" as never,
      label: subject.title,
      role: "section" as never,
      parentId: subject.parent_id ?? libraryRoot,
      order: index,
    })),
    ...libraryNotes.map((node, index) => ({
      id: node.id,
      degree: 0,
      kind: "note" as never,
      label: node.title,
      role: (libraryContainers.has(node.id) ? "section" : "claim") as never,
      parentId: libraryParents.get(node.id) ?? node.parent_id ??
        librarySubjects.find((subject) => subject.path === node.id.split("/").slice(0, -1).join("/"))?.id ??
        librarySubjectByKind.get(primitiveKindOf(node) ?? node.kind) ?? libraryRoot,
      order: index,
    })),
  ];
  const libraryLayout = layoutKnowledgeGraph({
    nodes: libraryLayoutNodes,
    edges: libraryLayoutNodes.filter((node) => node.parentId).map((node, index) => ({
      id: `l${index}`, source: node.parentId as string, target: node.id, type: "related_to" as never,
    })),
  });
  const libraryPositions = new Map(libraryLayout.nodes.map((node) => [node.id, node]));
  const libraryPalette = paletteForAgent("library");
  const librarySet = new Set(libraryLayoutNodes.map((node) => node.id));
  const libraryRenderNodes: Knowledge3dRenderNode[] = libraryLayoutNodes.map((node) => {
    const point = libraryPositions.get(node.id);
    const role = node.role as never as ("root" | "section" | "claim");
    const subject = role === "root" || role === "section";
    const noteMeta = libraryNotes.find((note) => note.id === node.id);
    return {
      id: node.id, x: point?.x ?? 0.5, y: point?.y ?? 0.5, depth: point?.depth,
      role, parentId: point?.parentId,
      radius: knowledgeNodeRadius(role, 1, false, point?.depth),
      subject,
      core: nodeCoreColor(libraryPalette, subject ? role : undefined, noteMeta?.status),
      dark: libraryPalette.dark,
      ring: subject || autoCurated.has(node.id) ? libraryPalette.ring : "rgba(0,0,0,0)",
      glow: subject ? libraryPalette.glow : "rgba(0,0,0,0)",
      ringScale: knowledgeSubjectRingScale(point?.depth),
      ringWidth: knowledgeSubjectRingWidth(subject ? role : undefined, point?.depth),
      glowScale: subject ? knowledgeSubjectGlowScale(role, point?.depth) : 1,
      alpha: knowledgeNodeBaseAlpha(subject ? role : undefined, point?.depth, "hot"),
      autoCurated: autoCurated.has(node.id),
    };
  });
  const libraryLinks = visibleArticleLinks(linkPairs, libraryArticleIds);
  reviewScopes.set("library", { articleIds: libraryArticleIds, scopeRefs: libraryArticleIds,
    links: libraryLinks, edgeColorEnd: () => libraryPalette.core });
  const libraryRenderEdges: Knowledge3dRenderEdge[] = [
    ...libraryLayoutNodes.filter((node) => node.parentId).map((node) => ({
      source: node.parentId as string, target: node.id, taxonomy: true, color: libraryPalette.core,
    })),
    ...withoutTaxonomyLinks(libraryLinks, libraryLayoutNodes).map((link) => ({
      source: link.source, target: link.target, taxonomy: false,
      color: knowledgeAmbientEdgeStroke(false, false, libraryPalette), colorEnd: libraryPalette.core,
    })),
  ];
  for (const ref of librarySet) {
    const note = libraryNotes.find((node) => node.id === ref);
    const subject = librarySubjects.find((candidate) => candidate.id === ref);
    titles.set(`agent:library/${ref}`, note
      ? note.title
      : (ref === libraryRoot ? libraryTitle : subject?.title ?? ref));
  }
  return {
    agentId: "library",
    nodes: libraryRenderNodes,
    edges: libraryRenderEdges,
  };
}
