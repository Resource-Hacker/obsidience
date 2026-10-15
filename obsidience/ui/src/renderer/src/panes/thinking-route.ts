/** The thinking route over one graph cloud: the refs that ignite, the
 *  waypoints the beam passes and its timing. Shared by the Knowledge and Code stages. */

import type { Knowledge3dRenderEdge, Knowledge3dRenderNode } from "@/components/themes/obsidience/knowledge-3d-scene";
import {
  computeKnowledgeSweepPlan,
  knowledge3dPathSpec,
  type Knowledge3dPathSpec,
} from "@/components/themes/obsidience/knowledge-3d";

export interface GraphCloud {
  nodes: Knowledge3dRenderNode[];
  edges: Knowledge3dRenderEdge[];
}

export interface ThinkingRoute {
  /** Supplied refs: these ignite fully and take their labels. */
  nodeIds: Set<string>;
  /** Hierarchy waypoints and Articles one link from a supplied one: the beam
   *  passes them and they glow softly, without a label. */
  passedIds: Set<string>;
  pathSpec: Knowledge3dPathSpec;
}

/** `refGroups` are the supplied refs again, one group per run: their Articles'
 *  links carry the beam. A route built without them (Reader selection) keeps
 *  to its hierarchy path. */
export function buildThinkingRoute(cloud: GraphCloud, refs: readonly string[], refGroups: readonly (readonly string[])[] = []): ThinkingRoute | null {
  const byId = new Map(cloud.nodes.map((node) => [node.id, node]));
  const targets = [...new Set(refs)].filter((ref) => byId.has(ref));
  if (targets.length === 0) return null;
  const edges = cloud.edges.map((edge, index) => ({
    id: `${index}:${edge.source}|${edge.target}`,
    source: edge.source,
    target: edge.target,
    taxonomy: edge.taxonomy,
  }));
  const taxonomyEdgeByChild = new Map(edges
    .filter((edge) => edge.taxonomy)
    .map((edge) => [edge.target, edge]));
  const nodeIds = new Set(targets);
  const routeNodeIds = new Set<string>();
  const activeEdgeIds = new Set<string>();
  for (const target of targets) {
    let cursor: string | null | undefined = target;
    const seen = new Set<string>();
    while (cursor && byId.has(cursor) && !seen.has(cursor)) {
      seen.add(cursor);
      routeNodeIds.add(cursor);
      const edge = taxonomyEdgeByChild.get(cursor);
      if (edge) activeEdgeIds.add(edge.id);
      cursor = byId.get(cursor)?.parentId;
    }
  }
  const root = cloud.nodes.find((node) => node.role === "root");
  if (!root) return null;
  routeNodeIds.add(root.id);
  // A supplied Article's links carry the beam one hop, to the Articles it is
  // linked with (owner 2026-10-12: the branching tail of the Electron build).
  // Neither such an Article nor a hierarchy waypoint is evidence that it
  // entered the packet: both are passed, never consulted, and a passed node
  // lights no further link.
  const linked = new Set(refGroups.flat().filter((ref) => nodeIds.has(ref)));
  for (const edge of edges) {
    if (edge.taxonomy || (!linked.has(edge.source) && !linked.has(edge.target))) continue;
    activeEdgeIds.add(edge.id);
    routeNodeIds.add(edge.source);
    routeNodeIds.add(edge.target);
  }
  const passedIds = new Set([...routeNodeIds].filter((id) => !nodeIds.has(id)));
  const positions = new Map(cloud.nodes.map((node) => [node.id, { x: node.x, y: node.y }]));
  const plan = computeKnowledgeSweepPlan(
    root.id,
    [...routeNodeIds],
    [...activeEdgeIds],
    edges,
    positions,
    nodeIds,
  );
  const pathSpec = knowledge3dPathSpec(plan, edges);
  // A root-only acknowledgement has no beam to travel before Brain can light.
  // Keep the normal sweep timing for every route that reaches another node.
  if (nodeIds.size === 1 && nodeIds.has(root.id) && activeEdgeIds.size === 0) {
    return { nodeIds, passedIds, pathSpec: { ...pathSpec,
      firstNodeProgress: 0, firstArticleProgress: 0, maxProgress: 0,
    } };
  }
  // Calculate beam timing through the full route first, then restrict full
  // ignition and labels (including satellite sweeps) to the supplied refs. The
  // full timing stays available for what marks the front's passage.
  return { nodeIds, passedIds, pathSpec: { ...pathSpec,
    routeArrival: pathSpec.nodeArrival,
    nodeArrival: new Map([...pathSpec.nodeArrival].filter(([id]) => nodeIds.has(id))),
  } };
}
