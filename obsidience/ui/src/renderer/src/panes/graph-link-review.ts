import type { GraphLink, GraphLinkProposal, LinkReviewChange } from "../lib/api";
import {
  KNOWLEDGE_LINK_APPROVAL_DURATION_MS,
  type Knowledge3dRelationEffect,
  type Knowledge3dRenderNode,
  type Knowledge3dRenderEdge,
} from "../components/themes/obsidience/knowledge-3d-satellites";
import { knowledgeAmbientEdgeStroke, knowledgeNodeRadius, paletteForBranch } from "../components/themes/obsidience/knowledge-paint";
import { withoutTaxonomyLinks } from "./graph-links";

/** Preview the eventual physical graph only at the Scene boundary. Callers
 * retain the accepted cloud for thinking paths and all semantic use. */
export function previewLinkReviewCloud<T extends {
  nodes: Knowledge3dRenderNode[]; edges: Knowledge3dRenderEdge[];
}>(cloud: T, acceptedLinks: readonly GraphLink[], previewLinks: readonly GraphLink[], degreeSized: boolean, edgeColorEnd: (id: string) => string): T {
  const pair = (source: string, target: string) => JSON.stringify([source, target].sort());
  const acceptedPairs = new Set(acceptedLinks.map((link) => pair(link.source, link.target)));
  const additions = previewLinks.filter((link) => !acceptedPairs.has(pair(link.source, link.target)));
  if (!additions.length) return cloud;
  const byId = new Map(cloud.nodes.map((node) => [node.id, node]));
  const degree = new Map<string, number>();
  for (const link of previewLinks) {
    degree.set(link.source, (degree.get(link.source) ?? 0) + 1);
    degree.set(link.target, (degree.get(link.target) ?? 0) + 1);
  }
  const edges = withoutTaxonomyLinks(additions, cloud.nodes).flatMap((link) => {
    const target = byId.get(link.target);
    if (!byId.has(link.source) || !target) return [];
    return [{ source: link.source, target: link.target, taxonomy: false,
      color: knowledgeAmbientEdgeStroke(false, false, paletteForBranch(null)),
      colorEnd: edgeColorEnd(link.target), preview: true }];
  });
  return { ...cloud,
    nodes: degreeSized ? cloud.nodes.map((node) => ({ ...node,
      radius: knowledgeNodeRadius(node.role as Parameters<typeof knowledgeNodeRadius>[0],
        degree.get(node.id) ?? 0, false, node.depth),
    })) : cloud.nodes,
    edges: [...cloud.edges, ...edges],
  };
}

/** Ephemeral presentation of an authority-confirmed decision, never graph truth. */
export interface LinkApproval {
  id: string;
  proposalId: string;
  startedAt: number;
  links: Array<{ source: string; target: string }>;
}

export function recordLinkApproval(
  current: readonly LinkApproval[], review: LinkReviewChange,
  wallNow: number, frameNow: number,
): LinkApproval[] {
  const live = current.filter((item) => frameNow - item.startedAt < KNOWLEDGE_LINK_APPROVAL_DURATION_MS);
  if (review.state !== "approved") return live;
  const at = review.decided_at;
  if (!review.proposal_id || typeof at !== "number" || !Number.isFinite(at)
    || at > wallNow + 1_000 || wallNow - at >= KNOWLEDGE_LINK_APPROVAL_DURATION_MS) return live;
  const id = JSON.stringify([review.proposal_id, at]);
  if (live.some((item) => item.id === id)) return live;
  const links = (review.links ?? []).slice(0, 64).filter((link) =>
    typeof link.source === "string" && typeof link.target === "string"
    && link.source.length > 0 && link.target.length > 0 && link.source !== link.target);
  if (!links.length) return live;
  return [...live, { id, proposalId: review.proposal_id,
    startedAt: frameNow - Math.max(0, wallNow - at), links }].slice(-64);
}

interface ReviewCloud {
  agentId: string;
  nodes: ReadonlyArray<{ id: string }>;
  edges: ReadonlyArray<{ source: string; target: string; taxonomy?: boolean }>;
}

/** Only exact existing endpoints get Review paint. Preview physics is a
 * separate Scene input; approval paint waits for the accepted snapshot. */
export function projectLinkReviewEffects(
  proposals: readonly GraphLinkProposal[], approvals: readonly LinkApproval[],
  accepted: readonly GraphLink[], aliases: ReadonlyMap<string, string>,
  clouds: readonly ReviewCloud[], frameNow: number,
  proposalStarts: ReadonlyMap<string, number> = new Map(),
): Knowledge3dRelationEffect[] {
  const exactPair = (source: string, target: string) => JSON.stringify([source, target]);
  const visualPair = (source: string, target: string) => JSON.stringify([source, target].sort());
  const acceptedPairs = new Set(accepted.filter((link) => !link.derived)
    .map((link) => exactPair(link.source, link.target)));
  const additions = approvals.filter((item) =>
    frameNow - item.startedAt < KNOWLEDGE_LINK_APPROVAL_DURATION_MS)
    .flatMap((item) => item.links.filter((link) => acceptedPairs.has(exactPair(link.source, link.target)))
      .map((link) => ({ ...link, id: item.id, phase: "approved" as const, startedAt: item.startedAt })));
  const pending = proposals.slice(0, 128).filter((link) =>
    !acceptedPairs.has(exactPair(link.source, link.target)))
    .map((link) => ({ ...link, id: link.proposal_id, phase: "pending" as const,
      startedAt: proposalStarts.get(link.proposal_id) ?? 0 }));
  return clouds.flatMap((cloud) => {
    const nodes = new Set(cloud.nodes.map((node) => node.id));
    const edges = new Set(cloud.edges.filter((link) => !link.taxonomy)
      .map((link) => visualPair(link.source, link.target)));
    const seen = new Set<string>();
    return [...additions, ...pending].flatMap((link) => {
      const source = aliases.get(link.source) ?? link.source;
      const target = aliases.get(link.target) ?? link.target;
      const pair = visualPair(source, target);
      if (source === target || !nodes.has(source) || !nodes.has(target) || seen.has(pair)
        || !edges.has(pair)) return [];
      seen.add(pair);
      return [{ id: JSON.stringify([link.id, pair]), graphId: cloud.agentId,
        source, target, phase: link.phase, startedAt: link.startedAt }];
    });
  });
}
