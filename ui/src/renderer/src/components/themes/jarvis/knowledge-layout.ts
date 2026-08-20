import type { KnowledgeEdge, KnowledgeNode } from "../../../../../shared/knowledge";
import {
  DEFAULT_KNOWLEDGE_HUB_ANCHOR,
  type KnowledgeLayoutAnchor,
  type KnowledgeLayoutBounds,
  type KnowledgeLayoutViewport,
} from "./knowledge-geometry";
import {
  isKnowledgeLeafRole,
  WORKSTATION_SUBJECT_IDS,
  type KnowledgeHierarchyRole,
} from "./knowledge-ontology";

export interface KnowledgeLayoutNode {
  id: string;
  x: number;
  y: number;
  depth?: number;
  parentId?: string | null;
  role?: KnowledgeHierarchyRole;
  z?: number;
  /** Subjects only: the reserved article-cluster distance (normalized by
   *  viewport height) — the radius its own articles would rest at, held
   *  clear of FOREIGN articles even when the subject has none (owner
   *  2026-08-01: Tools orbs crowded right against Coding Context). */
  articleOrbit?: number;
}

export interface KnowledgeLayout {
  nodes: KnowledgeLayoutNode[];
}

export interface KnowledgeLayoutInput {
  anchor?: KnowledgeLayoutAnchor;
  viewport?: KnowledgeLayoutViewport;
  nodes: Array<
    Pick<KnowledgeNode, "id" | "degree" | "kind" | "label"> & {
      parentId?: string | null;
      order?: number;
      role?: KnowledgeHierarchyRole;
    }
  >;
  edges: Array<Pick<KnowledgeEdge, "id" | "source" | "target" | "type">>;
  /** Optional radial distance scales (ambient 2D tuning): Brain→branch
   *  ring, the middle branch rings, and the article ring. Defaults of 1
   *  reproduce the canonical geometry exactly (contract pins unchanged). */
  ringScales?: { peers: number; branches: number; articles: number };
  /** Ambient 2D physics: render the stage as a TRUE CIRCLE — equal px
   *  metric on both axes (owner 2026-08-01: the ultrawide elliptical
   *  stretch reads exactly like a plane tilted away from the camera, so
   *  every circular force motion looked skewed against it). Inspect keeps
   *  the wide elliptical stage. */
  circularStage?: boolean;

}

/**
 * Keep established nodes anchored when a refreshed knowledge snapshot arrives.
 * The force layout still places new nodes, but existing claims do not jump
 * around merely because a relationship was reviewed or promoted.
 */
export function stabilizeKnowledgeLayout(
  previous: KnowledgeLayout | null,
  next: KnowledgeLayout,
): KnowledgeLayout {
  if (!previous || previous.nodes.length === 0 || next.nodes.length === 0) {
    return next;
  }

  const previousById = new Map(
    previous.nodes.map((node) => [node.id, node] as const),
  );
  let retained = 0;
  const nodes = next.nodes.map((node) => {
    const established = previousById.get(node.id);
    if (!established) return node;
    retained += 1;
    return established;
  });

  return retained === 0 ? next : { nodes };
}

function hashUnit(value: string): number {
  let hash = 2_166_136_261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16_777_619);
  }
  return (hash >>> 0) / 0xffff_ffff;
}

/**
 * The current ontology uses the ultrawide stage instead of staying confined
 * to a small perfect circle. Reflow happens only at meaningful capacity
 * thresholds, so adding one memory does not make the whole map twitch.
 */
export function knowledgeHierarchyHorizontalStretch(nodeCount: number): number {
  if (nodeCount <= 48) return 3;
  if (nodeCount <= 96) return 2.65;
  if (nodeCount <= 160) return 2.25;
  return 1.9;
}

/**
 * Keep the current small vault open around the reactor, then tighten only at
 * meaningful capacity thresholds. This gives the ambient map Obsidian-like
 * breathing room without making a single newly attested article move every
 * established subject.
 */
export function knowledgeHierarchyInnerRingProgress(
  nodeCount: number,
): number {
  if (nodeCount <= 48) return 0.42;
  if (nodeCount <= 96) return 0.38;
  if (nodeCount <= 160) return 0.34;
  return 0.3;
}

export function knowledgeHierarchyPeerInnerRingProgress(
  nodeCount: number,
  directPeerCount: number,
): number {
  const base = knowledgeHierarchyInnerRingProgress(nodeCount);
  return directPeerCount > 2 ? Math.max(0.58, base) : base;
}

const DEGREES_TO_RADIANS = Math.PI / 180;
const KNOWLEDGE_RING_SPREAD_EXPONENT = 0.72;
export const KNOWLEDGE_WORKSTATION_ROOT_RADIUS_SCALE = 0.72;
export const KNOWLEDGE_WORKSTATION_SECTOR_SPAN_DEGREES = 140;

interface CanonicalBrainPeerSector {
  id: string;
  angle: number;
  span: number;
  rootRadiusScale?: number;
}

/**
 * Stable screen-space sectors for the seven canonical Brain peers. Canvas
 * angles increase downwards, so the table walks from the west-facing
 * workstation through the lower half and returns through the upper half.
 *
 * Sector area follows structural depth, not semantic rank: every entry is
 * still a depth-one peer. The larger workstation fan prevents its deeper
 * Hardware/Software tree from collapsing when the root has seven children,
 * Agent carries the next-widest arc for its Tools subtree, and the compact
 * leaf domains occupy the tighter east-facing arc.
 */
/**
 * The sectors are DISJOINT by construction: 140 + 42 + 42 + 28 + 20 + 28 +
 * 46 spans plus seven 2-degree gaps total exactly 360. An earlier table
 * allocated 395 degrees, so ADMECH's fan interpenetrated both angular
 * neighbors and their descendants visually mixed into the same region.
 * Workstation [110,250]; games [66,108]; personal [22,64]; news [-8,20];
 * websites [-30,-10]; projects [-60,-32]; agent [-108,-62]; gaps between
 * each.
 */
const CANONICAL_BRAIN_PEER_SECTORS = [
  {
    id: WORKSTATION_SUBJECT_IDS.workstation,
    angle: 180 * DEGREES_TO_RADIANS,
    span:
      KNOWLEDGE_WORKSTATION_SECTOR_SPAN_DEGREES *
      DEGREES_TO_RADIANS,
    rootRadiusScale: KNOWLEDGE_WORKSTATION_ROOT_RADIUS_SCALE,
  },
  {
    id: WORKSTATION_SUBJECT_IDS.gameStrategy,
    angle: 87 * DEGREES_TO_RADIANS,
    span: 42 * DEGREES_TO_RADIANS,
  },
  {
    id: WORKSTATION_SUBJECT_IDS.personal,
    angle: 43 * DEGREES_TO_RADIANS,
    span: 42 * DEGREES_TO_RADIANS,
  },
  {
    id: WORKSTATION_SUBJECT_IDS.news,
    angle: 6 * DEGREES_TO_RADIANS,
    span: 28 * DEGREES_TO_RADIANS,
  },
  {
    id: WORKSTATION_SUBJECT_IDS.websites,
    angle: -20 * DEGREES_TO_RADIANS,
    span: 20 * DEGREES_TO_RADIANS,
  },
  {
    id: WORKSTATION_SUBJECT_IDS.projects,
    angle: -46 * DEGREES_TO_RADIANS,
    span: 28 * DEGREES_TO_RADIANS,
  },
  {
    id: WORKSTATION_SUBJECT_IDS.agent,
    angle: -85 * DEGREES_TO_RADIANS,
    span: 46 * DEGREES_TO_RADIANS,
  },
] as const satisfies readonly CanonicalBrainPeerSector[];

function compareHierarchyNodes(
  left: KnowledgeLayoutInput["nodes"][number],
  right: KnowledgeLayoutInput["nodes"][number],
): number {
  return (
    (left.order ?? Number.MAX_SAFE_INTEGER) -
      (right.order ?? Number.MAX_SAFE_INTEGER) ||
    (left.label ?? left.id).localeCompare(right.label ?? right.id) ||
    left.id.localeCompare(right.id)
  );
}

function hierarchyParentMap(
  nodes: KnowledgeLayoutInput["nodes"],
): Map<string, string> {
  const ids = new Set(nodes.map((node) => node.id));
  const parentById = new Map<string, string>();
  for (const node of nodes) {
    if (
      node.parentId &&
      node.parentId !== node.id &&
      ids.has(node.parentId)
    ) {
      parentById.set(node.id, node.parentId);
    }
  }

  // A malformed presentation tree must never hang the worker. Remove the
  // deterministic lexicographically-last parent edge from each detected
  // cycle, leaving a finite forest that still renders every node.
  for (const node of [...nodes].sort(compareHierarchyNodes)) {
    const path: string[] = [];
    const pathIndex = new Map<string, number>();
    let current: string | undefined = node.id;
    while (current && parentById.has(current)) {
      const existingIndex = pathIndex.get(current);
      if (existingIndex !== undefined) {
        const cycle = path.slice(existingIndex);
        const detached = [...cycle].sort().at(-1);
        if (detached) parentById.delete(detached);
        break;
      }
      pathIndex.set(current, path.length);
      path.push(current);
      current = parentById.get(current);
    }
  }
  return parentById;
}

function boundedAnchor(
  anchor: KnowledgeLayoutAnchor | undefined,
  bounds: KnowledgeLayoutBounds,
): KnowledgeLayoutAnchor {
  const x = anchor?.x;
  const y = anchor?.y;
  return {
    x:
      typeof x === "number" && Number.isFinite(x)
        ? Math.max(bounds.left, Math.min(bounds.right, x))
        : Math.max(
            bounds.left,
            Math.min(bounds.right, DEFAULT_KNOWLEDGE_HUB_ANCHOR.x),
          ),
    y:
      typeof y === "number" && Number.isFinite(y)
        ? Math.max(bounds.top, Math.min(bounds.bottom, y))
        : Math.max(
            bounds.top,
            Math.min(bounds.bottom, DEFAULT_KNOWLEDGE_HUB_ANCHOR.y),
          ),
  };
}

const DEFAULT_HIERARCHY_VIEWPORT: KnowledgeLayoutViewport = {
  width: 1_920,
  height: 1_080,
  bounds: {
    left: 0.05,
    right: 0.95,
    top: 0.06,
    bottom: 0.94,
  },
};

function boundedViewport(
  viewport: KnowledgeLayoutViewport | undefined,
): KnowledgeLayoutViewport {
  const width =
    viewport &&
    Number.isFinite(viewport.width) &&
    viewport.width > 0
      ? viewport.width
      : DEFAULT_HIERARCHY_VIEWPORT.width;
  const height =
    viewport &&
    Number.isFinite(viewport.height) &&
    viewport.height > 0
      ? viewport.height
      : DEFAULT_HIERARCHY_VIEWPORT.height;
  const requested = viewport?.bounds ?? DEFAULT_HIERARCHY_VIEWPORT.bounds;
  const left = Math.max(0, Math.min(0.94, requested.left));
  const right = Math.max(
    left + 0.05,
    Math.min(1, Number.isFinite(requested.right) ? requested.right : 0.95),
  );
  const top = Math.max(0, Math.min(0.94, requested.top));
  const bottom = Math.max(
    top + 0.05,
    Math.min(1, Number.isFinite(requested.bottom) ? requested.bottom : 0.94),
  );
  return {
    width,
    height,
    bounds: { left, right, top, bottom },
  };
}

function hierarchyDepth(
  id: string,
  childrenById: ReadonlyMap<
    string,
    readonly KnowledgeLayoutInput["nodes"][number][]
  >,
): number {
  const structuralChildren = (childrenById.get(id) ?? []).filter(
    (child) => !isKnowledgeLeafRole(child.role),
  );
  return structuralChildren.length === 0
    ? 0
    : 1 +
        Math.max(
          ...structuralChildren.map((child) =>
            hierarchyDepth(child.id, childrenById),
          ),
        );
}

/**
 * Deterministic O(nodes + edges) radial layout for the presentation ontology.
 * The canonical Brain remains fixed over the measured reactor. Its direct
 * peers occupy opposite rays, every structural descendant stays inside a
 * stable claim-independent angular sector, and the rings expand across the
 * ultrawide stage without entering the transcript. Attested semantic
 * cross-links remain visible but cannot pull articles out of their branch.
 */
function layoutKnowledgeHierarchy(
  input: KnowledgeLayoutInput,
): KnowledgeLayout {
  const nodes = [...input.nodes].sort(compareHierarchyNodes);
  const viewport = boundedViewport(input.viewport);
  const anchor = boundedAnchor(input.anchor, viewport.bounds);
  const nodeById = new Map(nodes.map((node) => [node.id, node] as const));
  const parentById = hierarchyParentMap(nodes);
  const childrenById = new Map<string, typeof nodes>();
  for (const node of nodes) childrenById.set(node.id, []);
  for (const [childId, parentId] of parentById) {
    childrenById.get(parentId)?.push(nodeById.get(childId)!);
  }
  for (const children of childrenById.values()) {
    children.sort(compareHierarchyNodes);
  }
  const roots = nodes
    .filter((node) => !parentById.has(node.id))
    .sort(compareHierarchyNodes);
  const leafWeight = new Map<string, number>();
  const measure = (id: string): number => {
    const children = childrenById.get(id) ?? [];
    const structural = children.filter(
      (child) => !isKnowledgeLeafRole(child.role),
    );
    const claimCount = children.length - structural.length;
    // Articles weight their subject's sector share (sqrt-damped so one
    // dense fan widens without starving structural siblings). Counting
    // structure alone gave Agent Tools' ~20-article fan the same share as
    // a two-article subject; its cramped fan then relaxed sideways ACROSS
    // the Temporary Observations cone (owner 2026-08-01: each subnode must
    // be aware of its peer subnodes' articles). With honest shares, the
    // claim fan's ≤95%-of-span bound keeps every fan inside its own cone.
    const weight =
      structural.reduce((sum, child) => sum + measure(child.id), 0) +
      Math.sqrt(claimCount);
    leafWeight.set(id, Math.max(1, weight));
    return Math.max(1, weight);
  };
  for (const root of roots) measure(root.id);

  const primaryRoot =
    roots.find((root) => root.role === "root") ?? roots[0];
  if (!primaryRoot) return { nodes: [] };
  const directPeerCount =
    (childrenById.get(primaryRoot.id)?.length ?? 0) +
    roots.filter((root) => root.id !== primaryRoot.id).length;

  // Reserve the outermost ring for article claims even when the current
  // snapshot has none. Adding a memory can therefore never move an existing
  // subject merely by increasing the hierarchy depth.
  const structuralMaxDepth = Math.max(
    1,
    ...roots.map((root) => hierarchyDepth(root.id, childrenById)),
  );
  const maxDepth = Math.max(2, structuralMaxDepth + 1);
  const availableHorizontalRadius = Math.max(
    0,
    Math.min(
      (anchor.x - viewport.bounds.left) * viewport.width,
      (viewport.bounds.right - anchor.x) * viewport.width,
    ),
  );
  const availableVerticalRadius = Math.max(
    0,
    Math.min(
      (anchor.y - viewport.bounds.top) * viewport.height,
      (viewport.bounds.bottom - anchor.y) * viewport.height,
    ),
  );
  // Preserve the radial/Obsidian reading while taking advantage of the very
  // wide stage. Vertical space remains transcript-safe; horizontal spokes
  // expand into otherwise empty space and contract at large vault capacities.
  const verticalMargin = Math.min(48, availableVerticalRadius * 0.12);
  const horizontalMargin = Math.min(72, availableHorizontalRadius * 0.08);
  const maximumVerticalRingRadius = Math.max(
    0,
    availableVerticalRadius - verticalMargin,
  );
  const maximumHorizontalRingRadius = Math.max(
    0,
    Math.min(
      availableHorizontalRadius - horizontalMargin,
      maximumVerticalRingRadius *
        (input.circularStage
          ? 1
          : knowledgeHierarchyHorizontalStretch(nodes.length)),
    ),
  );
  const ringProgress = (
    depth: number,
    claimParentDepth?: number,
    claimParentScale = 1,
  ): number => {
    if (
      depth <= 0 ||
      maximumVerticalRingRadius <= 0 ||
      maximumHorizontalRingRadius <= 0
    ) {
      return 0;
    }
    const boundedDepth = Math.min(maxDepth, depth);
    // The sub-unity exponent front-loads the ring spacing: the jump from a
    // branch hub to its first child ring is the one the eye reads (and the
    // one the vertical ellipse compresses hardest at the top sectors), so it
    // gets the largest share of the remaining radius.
    const canonical = (ringDepth: number): number =>
      maxDepth <= 1
        ? 0
        : Math.pow(
            Math.max(0, ringDepth - 1) / (maxDepth - 1),
            KNOWLEDGE_RING_SPREAD_EXPONENT,
          );
    const innerRingProgress = knowledgeHierarchyPeerInnerRingProgress(
      nodes.length,
      directPeerCount,
    );
    const scales = input.ringScales ?? { peers: 1, branches: 1, articles: 1 };
    const inner = Math.min(0.9, innerRingProgress * scales.peers);
    // Ring SPACING stays anchored to the canonical inner ring: the peers
    // slider TRANSLATES the whole structure in or out, it never stretches
    // the outer segments. Scaling spacing by the live (1 - inner) made a
    // compressed first ring (ring2dPeers < 1) grow every branch gap and
    // article spoke by the reclaimed radius — the owner's map read as
    // "news articles going way off to the side" (2026-08-01).
    const spacing = 1 - Math.min(0.9, innerRingProgress);
    const branchRing = (ringDepth: number): number =>
      Math.min(
        1.06,
        inner + spacing * canonical(ringDepth) * scales.branches,
      );
    if (claimParentDepth === undefined && boundedDepth < maxDepth) {
      return branchRing(boundedDepth);
    }
    // Articles rest ONE ring beyond THEIR OWN PARENT, not on a global
    // outer rim (owner 2026-08-01: rim placement flung the ~20 Tools
    // articles and the temporary observations to the top-right corner on
    // huge spokes that crossed every other fan — fans must hug their
    // subject, like the 3D ball's shells). The article slider scales this
    // parent-relative SEGMENT, so rings stay strictly monotonic outward
    // and a shrunk article distance can never fold articles back behind
    // their parent toward the Brain. For parents on the deepest structural
    // ring this reproduces the former deepest-ring geometry exactly.
    const parentDepth = Math.max(
      1,
      Math.min(maxDepth - 1, claimParentDepth ?? maxDepth - 1),
    );
    const articleStep =
      spacing *
      (canonical(parentDepth + 1) - canonical(parentDepth)) *
      scales.articles;
    // The article segment rides the parent's ACTUAL ring: a root-radius
    // scaled peer (ADMECH at 0.72) otherwise measured its article ring
    // from the unscaled radius, inflating every child/article floor by
    // the scale gap (owner 2026-08-01: Hardware pinned needlessly far).
    return Math.min(
      1.18,
      branchRing(parentDepth) * claimParentScale + articleStep,
    );
  };
  const pointOnRing = (
    angle: number,
    depth: number,
    radiusScale = 1,
    claimParentDepth?: number,
    claimParentScale = 1,
  ): Pick<KnowledgeLayoutNode, "x" | "y"> => {
    const progress =
      ringProgress(depth, claimParentDepth, claimParentScale) * radiusScale;
    return {
      x:
        anchor.x +
        (Math.cos(angle) * maximumHorizontalRingRadius * progress) /
          viewport.width,
      y:
        anchor.y +
        (Math.sin(angle) * maximumVerticalRingRadius * progress) /
          viewport.height,
    };
  };

  const positions: KnowledgeLayoutNode[] = [];
  const placeBranch = (
    id: string,
    angle: number,
    span: number,
    depth: number,
    nodeRadiusScale = 1,
  ) => {
    const node = nodeById.get(id)!;
    const children = childrenById.get(id) ?? [];
    const structuralChildren = children.filter(
      (child) => !isKnowledgeLeafRole(child.role),
    );
    const claimChildren = children.filter((child) =>
      isKnowledgeLeafRole(child.role),
    );
    const role = node.role;
    const parentId = parentById.get(id);
    const hierarchyZ =
      role === "root"
        ? 1
        : role === "section"
          ? 0.76
          : role === "entity"
            ? 0.48
            : 0.14 + hashUnit(`${id}:z`) * 0.12;
    const position: KnowledgeLayoutNode = {
      id,
      ...pointOnRing(angle, depth, nodeRadiusScale),
      depth,
      parentId: parentId ?? null,
      role,
      z: hierarchyZ,
    };
    if (role === "section" && depth >= 1) {
      // Reserved article orbit: where this subject's articles would rest
      // (computed even with zero claims so the space stays protected).
      const claimPoint = pointOnRing(angle, maxDepth, 1, depth, nodeRadiusScale);
      position.articleOrbit =
        Math.hypot(
          (claimPoint.x - position.x) * viewport.width,
          (claimPoint.y - position.y) * viewport.height,
        ) / viewport.height;
    }
    positions.push(position);

    const totalWeight = structuralChildren.reduce(
      (sum, child) => sum + (leafWeight.get(child.id) ?? 1),
      0,
    );
    let cursor = angle - span / 2;
    for (const child of structuralChildren) {
      const share = span * ((leafWeight.get(child.id) ?? 1) / totalWeight);
      const childAngle = cursor + share / 2;
      placeBranch(
        child.id,
        childAngle,
        Math.max(0.035, share * 0.88),
        depth + 1,
      );
      cursor += share;
    }

    // Claims are terminal article leaves in the presentation ontology. Their
    // positions use only their stable IDs and the fixed parent sector, so
    // inserting another claim cannot perturb subjects or existing articles.
    // The fan never exceeds the parent's own angular allocation, so a
    // branch's articles can never spill into the neighboring branch; a
    // narrow allocation stacks claims radially and the collision relaxation
    // spreads them outward along the spoke.
    const claimFan = Math.min(
      span * 0.95,
      Math.max(0.58, Math.min(Math.PI * 0.5, span * 0.82)),
    );
    for (const claim of claimChildren) {
      const claimAngle =
        angle + (hashUnit(`${claim.id}:claim-angle`) - 0.5) * claimFan;
      const claimRadiusScale =
        1 + hashUnit(`${id}:${claim.id}:claim-radius`) * 0.07;
      // depth stays the deepest ring for rendering tiers/taper; only the
      // RADIUS is parent-relative so the fan hugs its subject.
      const claimDepth = maxDepth;
      positions.push({
        id: claim.id,
        ...pointOnRing(
          claimAngle,
          claimDepth,
          claimRadiusScale,
          depth,
          nodeRadiusScale,
        ),
        depth: claimDepth,
        parentId: id,
        role: claim.role,
        z: 0.14 + hashUnit(`${claim.id}:z`) * 0.12,
      });
    }
  };

  positions.push({
    id: primaryRoot.id,
    x: anchor.x,
    y: anchor.y,
    depth: 0,
    parentId: null,
    role: primaryRoot.role,
    z: 1,
  });

  // The live ontology has one canonical root. Treat malformed additional
  // forest roots as deterministic first-ring peers for finite rendering while
  // preserving their null parent IDs in the result.
  const topLevel = [
    ...(childrenById.get(primaryRoot.id) ?? []),
    ...roots.filter((root) => root.id !== primaryRoot.id),
  ].sort(compareHierarchyNodes);
  const topLevelCount = topLevel.length;
  const fallbackTopLevelSpan =
    topLevelCount <= 1
      ? Math.PI * 1.52
      : Math.min(Math.PI * 0.72, (Math.PI * 2 * 0.72) / topLevelCount);
  const topLevelIds = new Set(topLevel.map((node) => node.id));
  const canonicalSectors =
    topLevelCount === CANONICAL_BRAIN_PEER_SECTORS.length &&
    CANONICAL_BRAIN_PEER_SECTORS.every((sector) =>
      topLevelIds.has(sector.id),
    )
      ? CANONICAL_BRAIN_PEER_SECTORS
      : null;

  if (canonicalSectors) {
    for (const sector of canonicalSectors) {
      placeBranch(
        sector.id,
        sector.angle,
        sector.span,
        1,
        "rootRadiusScale" in sector ? sector.rootRadiusScale : 1,
      );
    }
  } else {
    for (let index = 0; index < topLevelCount; index += 1) {
      const angle =
        topLevelCount === 1
          ? 0
          : Math.PI - (index * Math.PI * 2) / topLevelCount;
      placeBranch(
        topLevel[index].id,
        angle,
        fallbackTopLevelSpan,
        1,
      );
    }
  }

  const placedIds = new Set(positions.map((position) => position.id));
  const unplaced = nodes.filter((node) => !placedIds.has(node.id));
  unplaced.forEach((node, index) => {
    const angle =
      Math.PI - ((topLevelCount + index) * Math.PI * 2) /
        Math.max(1, topLevelCount + unplaced.length);
    placeBranch(node.id, angle, fallbackTopLevelSpan, 1);
  });

  relaxKnowledgeCollisions(positions, viewport, anchor);
  // Interleave line clearance with circle relaxation: the first pass may
  // push a leaf into another circle, and separating circles may nudge a
  // leaf back toward a spoke. Pushing a leaf outward also EXTENDS its own
  // spoke past siblings, so dense fans (Agent Tools carries ~20 articles)
  // need several rounds to converge — loop until a round moves nothing,
  // bounded. Ends on the circle pass: its pinned separation invariants
  // are exact, while any few-px line residue it reintroduces is groomed
  // at runtime by the settle simulation's edge clearance (now feasible,
  // since targets start line-clear).
  for (let round = 0; round < 6; round += 1) {
    const moved = relaxKnowledgeLineClearance(positions, viewport, anchor);
    relaxKnowledgeCollisions(positions, viewport, anchor);
    if (!moved) break;
  }
  compactKnowledgeLayout(positions, viewport, anchor);
  // Compacting sections ignore leaves (subject stability), so a parked
  // section can capture foreign orb targets inside its reservation — one
  // final leaf-side pass moves those targets out before physics ever
  // runs, keeping settle displacement local.
  relaxKnowledgeLineClearance(positions, viewport, anchor);
  relaxKnowledgeCollisions(positions, viewport, anchor);

  return {
    nodes: positions.sort(
      (left, right) =>
        compareHierarchyNodes(nodeById.get(left.id)!, nodeById.get(right.id)!),
    ),
  };
}

/**
 * Collision radii mirror the canvas renderer's full visual footprint — the
 * outer halo ring (up to 1.88x the core for depth-one hubs, 1.4-1.55x for
 * deeper sections), not just the core dot. Using core radii let satellites
 * sit visually on top of their hub's ring.
 */
export function estimateKnowledgeNodeRadius(
  role: KnowledgeHierarchyRole | undefined,
  depth: number | undefined,
): number {
  if (role === "root") return 33;
  if (role === "section") {
    if (depth !== undefined && depth <= 1) return 29;
    if (depth === 2) return 17;
    return 12;
  }
  if (role === "entity") return 10;
  return 7;
}

/** Matches KNOWLEDGE_2D_EDGE_CLEARANCE_PX in knowledge-3d.ts (pinned by a
 *  contract test): the settle simulation enforces the same node↔spoke gap
 *  at runtime, so layout targets and physics equilibrium agree. */
export const KNOWLEDGE_LINE_CLEARANCE_PADDING_PX = 8;
/** Matches KNOWLEDGE_2D_EDGE_SIBLING_CLEARANCE_PX: a node's own fan is
 *  intentional dense geometry — full foreign padding there marched the
 *  Agent Tools articles to the screen edge (owner 2026-08-01). */
export const KNOWLEDGE_LINE_CLEARANCE_SIBLING_PADDING_PX = 3;
const KNOWLEDGE_LINE_CLEARANCE_STEP_PX = 4;
/** Hard cap on how far a leaf may drift from its radial home for line
 *  clearance (px = steps × step). Best-effort beyond this: the runtime
 *  settle force grooms locally, and an unclearable ultra-dense wedge must
 *  never send an article across the map or into the bounds clamp. */
const KNOWLEDGE_LINE_CLEARANCE_MAX_STEPS = 40;

/**
 * Deterministic line-clearance relaxation: article leaves must not rest ON
 * a painted taxonomy spoke (owner 2026-08-01 — dense fans like Today's
 * Top 10 and Agent Tools placed nearer siblings within a couple px of the
 * neighbouring article's spoke, which reads as attached to it). Every leaf
 * within clearance of a segment it does not terminate steps OUTWARD along
 * its own parent ray — matching the crowding contract (article leaves
 * drift only outward, never inward) and monotonically clearing sibling
 * spokes, which diverge from the same hub. Fixed step size, bounded step
 * count, fixed iteration order, no randomness. Subjects never move here.
 */
function relaxKnowledgeLineClearance(
  positions: KnowledgeLayoutNode[],
  viewport: KnowledgeLayoutViewport,
  anchor: KnowledgeLayoutAnchor,
): boolean {
  const { width, height, bounds } = viewport;
  const anchorX = anchor.x * width;
  const anchorY = anchor.y * height;
  const indexById = new Map(positions.map((node, index) => [node.id, index]));
  const x = positions.map((node) => node.x * width);
  const y = positions.map((node) => node.y * height);
  // Painted spokes only: structural parent→child arms. Brain→peer spokes
  // are unpainted in ambient 2D, and article spokes were retired for
  // plasma orbs (owner 2026-08-01) — leaves impose no line of their own.
  const segments: Array<{ child: number; parent: number }> = [];
  positions.forEach((node, child) => {
    if (!node.parentId) return;
    if (
      node.role === "claim" ||
      node.role === "temporary"
    ) {
      return;
    }
    const parent = indexById.get(node.parentId);
    if (parent === undefined) return;
    if (positions[parent].role === "root") return;
    segments.push({ child, parent });
  });
  if (segments.length === 0) return false;
  const minX = bounds.left * width;
  const maxX = bounds.right * width;
  const minY = bounds.top * height;
  const maxY = bounds.bottom * height;
  let anyMoved = false;

  positions.forEach((node, leaf) => {
    // Deep sections step clear of sibling/foreign structural beams too
    // (owner 2026-08-01: Architecture clipped into the fat Agent→
    // Preferences beam) — bounded to a few steps so subjects stay near
    // their sector homes. Depth-1 peers are contract-pinned and never
    // move.
    const deepSection = node.role === "section" && (node.depth ?? 0) >= 2;
    if (
      node.role !== "claim" &&
      node.role !== "temporary" &&
      node.role !== "entity" &&
      !deepSection
    ) {
      return;
    }
    const maxSteps = deepSection ? 10 : KNOWLEDGE_LINE_CLEARANCE_MAX_STEPS;
    const radius = estimateKnowledgeNodeRadius(node.role, node.depth);
    // Outward along the leaf's own spoke ray (hub ray when degenerate).
    const parentIndex = node.parentId
      ? indexById.get(node.parentId)
      : undefined;
    const originX = parentIndex === undefined ? anchorX : x[parentIndex];
    const originY = parentIndex === undefined ? anchorY : y[parentIndex];
    let rayX = x[leaf] - originX;
    let rayY = y[leaf] - originY;
    const rayLength = Math.hypot(rayX, rayY);
    if (rayLength < 0.5) {
      rayX = x[leaf] - anchorX;
      rayY = y[leaf] - anchorY;
      const hubLength = Math.hypot(rayX, rayY) || 1;
      rayX /= hubLength;
      rayY /= hubLength;
    } else {
      rayX /= rayLength;
      rayY /= rayLength;
    }
    const violated = (): boolean => {
      for (const segment of segments) {
        if (segment.child === leaf || segment.parent === leaf) continue;
        // The leaf's own family (its parent's fan, the spoke into its
        // parent) is intentional dense geometry: only keep the line
        // visibly outside the disc there. Foreign lines get the full
        // margin.
        const family =
          parentIndex !== undefined &&
          (segment.parent === parentIndex || segment.child === parentIndex);
        // Structural beams render up to ~10px wide at the first arm — the
        // clearance covers the half-beam so nothing clips into the tube.
        const halfBeam = 5;
        const clearance =
          radius +
          halfBeam +
          (family
            ? KNOWLEDGE_LINE_CLEARANCE_SIBLING_PADDING_PX
            : KNOWLEDGE_LINE_CLEARANCE_PADDING_PX);
        const ax = x[segment.parent];
        const ay = y[segment.parent];
        const bx = x[segment.child];
        const by = y[segment.child];
        const abx = bx - ax;
        const aby = by - ay;
        const lengthSq = abx * abx + aby * aby;
        if (lengthSq < 1e-6) continue;
        let t = ((x[leaf] - ax) * abx + (y[leaf] - ay) * aby) / lengthSq;
        if (t < 0) t = 0;
        else if (t > 1) t = 1;
        const distance = Math.hypot(
          x[leaf] - (ax + abx * t),
          y[leaf] - (ay + aby * t),
        );
        if (distance < clearance) return true;
      }
      return false;
    };
    for (let step = 0; step < maxSteps && violated(); step += 1) {
      x[leaf] += rayX * KNOWLEDGE_LINE_CLEARANCE_STEP_PX;
      y[leaf] += rayY * KNOWLEDGE_LINE_CLEARANCE_STEP_PX;
      x[leaf] = Math.max(minX + radius, Math.min(maxX - radius, x[leaf]));
      y[leaf] = Math.max(minY + radius, Math.min(maxY - radius, y[leaf]));
      anyMoved = true;
    }
  });

  positions.forEach((node, index) => {
    const deepSection = node.role === "section" && (node.depth ?? 0) >= 2;
    if (
      node.role !== "claim" &&
      node.role !== "temporary" &&
      node.role !== "entity" &&
      !deepSection
    ) {
      return;
    }
    node.x = x[index] / width;
    node.y = y[index] / height;
  });
  return anyMoved;
}

/** A subject's full reserved zone from its raw article-ring distance:
 *  the ring itself, the orb footprint that would rest on it, and
 *  breathing room — foreign orbs stay outside the WHOLE would-be cluster,
 *  not merely off the ring's centerline (owner 2026-08-01: Tools orbs at
 *  exactly ring distance still read as crowding Coding Context). */
export function knowledgeReservedOrbitPx(orbitPx: number): number {
  if (orbitPx <= 0) return 0;
  // Floor: deep subjects' ring segments compress with the radial curve,
  // which left Temporary Observations barely repelling anything — every
  // level keeps the same meaningful reservation (owner 2026-08-01).
  return Math.min(190, Math.max(96, orbitPx * 1.25 + 24));
}

/**
 * Deterministic radial COMPACTION (owner 2026-08-01: "if it was actually
 * being pulled toward the center until it hit the stopping point of the
 * min distance of the article it would be a lot closer"). Every node —
 * except the pinned Brain and the contract-pinned depth-1 peers — steps
 * toward the Brain along its own hub ray until a floor stops it: circle
 * separation and reserved orbits against every other node, structural
 * beam clearance, and the article-distance floor from its own parent
 * ("every level has that same rule"). Fixed order (hub distance, then
 * id), fixed step, bounded rounds — no randomness.
 */
function compactKnowledgeLayout(
  positions: KnowledgeLayoutNode[],
  viewport: KnowledgeLayoutViewport,
  anchor: KnowledgeLayoutAnchor,
): void {
  const count = positions.length;
  if (count < 2) return;
  const { width, height, bounds } = viewport;
  const anchorX = anchor.x * width;
  const anchorY = anchor.y * height;
  const x = new Float64Array(count);
  const y = new Float64Array(count);
  const radius = new Float64Array(count);
  const orbitPx = new Float64Array(count);
  const indexById = new Map<string, number>();
  positions.forEach((node, index) => {
    x[index] = node.x * width;
    y[index] = node.y * height;
    radius[index] = estimateKnowledgeNodeRadius(node.role, node.depth);
    orbitPx[index] = (node.articleOrbit ?? 0) * height;
    indexById.set(node.id, index);
  });
  const isLeaf = (index: number) => {
    const role = positions[index].role;
    return role === "claim" || role === "temporary" || role === "entity";
  };
  const mobile = (index: number) => {
    const node = positions[index];
    if (node.role === "root") return false;
    if (node.role === "section" && (node.depth ?? 0) <= 1) return false;
    return true;
  };
  const parentIndexOf = (index: number): number | undefined => {
    const parentId = positions[index].parentId;
    return parentId ? indexById.get(parentId) : undefined;
  };
  const structuralSegments: Array<{ child: number; parent: number }> = [];
  positions.forEach((node, child) => {
    if (isLeaf(child) || !node.parentId) return;
    const parent = indexById.get(node.parentId);
    if (parent === undefined || positions[parent].role === "root") return;
    structuralSegments.push({ child, parent });
  });
  const minX = bounds.left * width;
  const maxX = bounds.right * width;
  const minY = bounds.top * height;
  const maxY = bounds.bottom * height;

  const validAt = (index: number, nx: number, ny: number): boolean => {
    if (
      nx < minX + radius[index] ||
      nx > maxX - radius[index] ||
      ny < minY + radius[index] ||
      ny > maxY - radius[index]
    ) {
      return false;
    }
    const self = positions[index];
    const selfLeaf = isLeaf(index);
    const parentIndex = parentIndexOf(index);
    // Article-distance floor from the OWN parent: the node never comes
    // closer to its parent than the parent's article ring.
    if (parentIndex !== undefined) {
      const floor = Math.max(
        radius[index] + radius[parentIndex] + KNOWLEDGE_COLLISION_PADDING_PX,
        orbitPx[parentIndex],
      );
      if (
        Math.hypot(nx - x[parentIndex], ny - y[parentIndex]) <
        floor - 0.5
      ) {
        return false;
      }
      // Radiating: never closer to the Brain than the parent.
      const parentHub = Math.hypot(
        x[parentIndex] - anchorX,
        y[parentIndex] - anchorY,
      );
      if (Math.hypot(nx - anchorX, ny - anchorY) < parentHub + 2) {
        return false;
      }
    }
    for (let other = 0; other < count; other += 1) {
      if (other === index) continue;
      const otherLeaf = isLeaf(other);
      // A compacting SECTION ignores leaves entirely: inserting an
      // article must never change where a subject rests (the runtime
      // orbit force keeps foreign orbs clear of wherever it parks).
      if (!selfLeaf && otherLeaf) continue;
      let minDistance =
        radius[index] + radius[other] + KNOWLEDGE_COLLISION_PADDING_PX;
      const family =
        positions[index].parentId === positions[other].id ||
        positions[other].parentId === self.id ||
        (positions[index].parentId !== undefined &&
          positions[index].parentId === positions[other].parentId);
      if (!family) {
        if (selfLeaf !== otherLeaf) {
          const subjectOrbit = selfLeaf ? orbitPx[other] : orbitPx[index];
          if (subjectOrbit > 0) {
            minDistance = Math.max(
              minDistance,
              knowledgeReservedOrbitPx(subjectOrbit),
            );
          }
        } else if (!selfLeaf && !otherLeaf) {
          const both = Math.max(orbitPx[index], orbitPx[other]);
          if (both > 0) {
            minDistance = Math.max(
              minDistance,
              knowledgeReservedOrbitPx(both),
            );
          }
        }
      }
      if (Math.hypot(nx - x[other], ny - y[other]) < minDistance) {
        return false;
      }
    }
    // Structural beam clearance for the moving node.
    const halfBeam = 5;
    for (const segment of structuralSegments) {
      if (segment.child === index || segment.parent === index) continue;
      const familySegment =
        parentIndex !== undefined &&
        (segment.parent === parentIndex || segment.child === parentIndex);
      const clearance =
        radius[index] +
        halfBeam +
        (familySegment
          ? KNOWLEDGE_LINE_CLEARANCE_SIBLING_PADDING_PX
          : KNOWLEDGE_LINE_CLEARANCE_PADDING_PX);
      const ax = x[segment.parent];
      const ay = y[segment.parent];
      const bx = x[segment.child];
      const by = y[segment.child];
      const abx = bx - ax;
      const aby = by - ay;
      const lengthSq = abx * abx + aby * aby;
      if (lengthSq < 1e-6) continue;
      let tPos = ((nx - ax) * abx + (ny - ay) * aby) / lengthSq;
      if (tPos < 0) tPos = 0;
      else if (tPos > 1) tPos = 1;
      if (
        Math.hypot(nx - (ax + abx * tPos), ny - (ay + aby * tPos)) <
        clearance - 0.5
      ) {
        return false;
      }
    }
    return true;
  };

  const order = positions
    .map((_, index) => index)
    .filter(mobile)
    .sort((left, right) => {
      const hubLeft = Math.hypot(x[left] - anchorX, y[left] - anchorY);
      const hubRight = Math.hypot(x[right] - anchorX, y[right] - anchorY);
      return (
        hubLeft - hubRight || positions[left].id.localeCompare(positions[right].id)
      );
    });
  // Falling into place: straight down the hub ray first; when a beam or
  // reservation blocks the ray, SLIDE diagonally around it (owner
  // 2026-08-01: Hardware parked far out because its ray grazed a sibling
  // beam). Lateral drift is capped so nodes stay in their sector.
  const homeAngle = new Float64Array(count);
  positions.forEach((_, index) => {
    homeAngle[index] = Math.atan2(y[index] - anchorY, x[index] - anchorX);
  });
  const angleDelta = (left: number, right: number): number => {
    let delta = left - right;
    while (delta > Math.PI) delta -= Math.PI * 2;
    while (delta < -Math.PI) delta += Math.PI * 2;
    return delta;
  };
  for (let round = 0; round < 80; round += 1) {
    let moved = false;
    for (const index of order) {
      const hubX = x[index] - anchorX;
      const hubY = y[index] - anchorY;
      const hubDistance = Math.hypot(hubX, hubY);
      if (hubDistance < 1) continue;
      const angle = Math.atan2(hubY, hubX);
      let done = false;
      for (const step of [6, 3]) {
        if (done) break;
        for (const turn of [0, 0.045, -0.045]) {
          if (turn !== 0) {
            const drift = angleDelta(angle + turn, homeAngle[index]);
            if (Math.abs(drift) > 0.3) continue;
          }
          const nextAngle = angle + turn;
          const radius = hubDistance - step;
          const nx = anchorX + Math.cos(nextAngle) * radius;
          const ny = anchorY + Math.sin(nextAngle) * radius;
          if (validAt(index, nx, ny)) {
            x[index] = nx;
            y[index] = ny;
            moved = true;
            done = true;
            break;
          }
        }
      }
    }
    if (!moved) break;
  }
  positions.forEach((node, index) => {
    if (!mobile(index)) return;
    node.x = x[index] / width;
    node.y = y[index] / height;
  });
}

const KNOWLEDGE_COLLISION_ITERATIONS = 48;
const KNOWLEDGE_COLLISION_PADDING_PX = 14;

/**
 * Deterministic Obsidian-style collision relaxation. The pure radial pass
 * hash-places article leaves inside their parent's fan, so crowded adjacent
 * branches can overlap. This pass separates any colliding pair in screen
 * space with role-weighted mobility (the root never moves, sections barely,
 * claims freely), pulls every node gently back toward its radial home so the
 * hierarchy reading survives, and lets article leaves drift only OUTWARD from
 * the hub — the reserved outer ring stays a floor, and crowding grows the
 * radius instead of collapsing inward. Fixed iteration count, no randomness.
 */
function relaxKnowledgeCollisions(
  positions: KnowledgeLayoutNode[],
  viewport: KnowledgeLayoutViewport,
  anchor: KnowledgeLayoutAnchor,
): void {
  const count = positions.length;
  if (count < 2) return;
  const { width, height, bounds } = viewport;
  const anchorX = anchor.x * width;
  const anchorY = anchor.y * height;
  const x = new Float64Array(count);
  const y = new Float64Array(count);
  const homeX = new Float64Array(count);
  const homeY = new Float64Array(count);
  const radius = new Float64Array(count);
  const mobility = new Float64Array(count);
  const homeSpring = new Float64Array(count);
  const minHubDistance = new Float64Array(count);
  const orbitPx = new Float64Array(count);
  const parentIds: Array<string | null | undefined> = new Array(count);
  const parentIndexOf = new Int32Array(count).fill(-1);

  for (let index = 0; index < count; index += 1) {
    const node = positions[index];
    x[index] = node.x * width;
    y[index] = node.y * height;
    homeX[index] = x[index];
    homeY[index] = y[index];
    radius[index] = estimateKnowledgeNodeRadius(node.role, node.depth);
    orbitPx[index] = (node.articleOrbit ?? 0) * height;
    parentIds[index] = node.parentId;
    if (node.parentId) {
      const found = positions.findIndex((p) => p.id === node.parentId);
      parentIndexOf[index] = found;
    }
    if (node.role === "root") {
      mobility[index] = 0;
      homeSpring[index] = 1;
    } else if (node.role === "section") {
      // Only the depth-one branch hubs are contract-pinned sector anchors;
      // deeper sections may yield so a hub's first child ring can breathe.
      const pinned = (node.depth ?? 0) <= 1;
      mobility[index] = pinned ? 0 : 0.3;
      homeSpring[index] = pinned ? 1 : 0.08;
    } else if (node.role === "entity") {
      mobility[index] = 0.55;
      homeSpring[index] = 0.05;
    } else {
      mobility[index] = 1;
      homeSpring[index] = 0.025;
      minHubDistance[index] = Math.hypot(
        homeX[index] - anchorX,
        homeY[index] - anchorY,
      );
    }
  }

  const minX = bounds.left * width;
  const maxX = bounds.right * width;
  const minY = bounds.top * height;
  const maxY = bounds.bottom * height;

  // The last sweeps run without home springs so the hard separation
  // constraint wins over the aesthetic pull-back; springs otherwise leave
  // pairs asymptotically just inside the minimum distance.
  const springIterations = KNOWLEDGE_COLLISION_ITERATIONS - 8;
  for (
    let iteration = 0;
    iteration < KNOWLEDGE_COLLISION_ITERATIONS;
    iteration += 1
  ) {
    for (let left = 0; left < count; left += 1) {
      for (let right = left + 1; right < count; right += 1) {
        let minDistance =
          radius[left] + radius[right] + KNOWLEDGE_COLLISION_PADDING_PX;
        // Reserved article orbits: a FOREIGN leaf stays outside the ring
        // where a subject's own articles rest — even when that subject has
        // no articles yet (owner 2026-08-01: Tools orbs sat right against
        // the empty Coding Context).
        const leftLeaf = mobility[left] === 1;
        const rightLeaf = mobility[right] === 1;
        if (
          leftLeaf !== rightLeaf &&
          (leftLeaf
            ? orbitPx[right] > 0 && parentIds[left] !== positions[right].id
            : orbitPx[left] > 0 && parentIds[right] !== positions[left].id)
        ) {
          minDistance = Math.max(
            minDistance,
            knowledgeReservedOrbitPx(
              leftLeaf ? orbitPx[right] : orbitPx[left],
            ),
          );
        }
        // Subjects keep the SAME reservation from each other (owner
        // 2026-08-01: Project Observations sat against Reddit). Family
        // pairs are exempt — a parent and its child ring, or siblings
        // under one hub, are canonical geometry.
        if (
          !leftLeaf &&
          !rightLeaf &&
          orbitPx[left] > 0 &&
          orbitPx[right] > 0 &&
          parentIds[left] !== positions[right].id &&
          parentIds[right] !== positions[left].id &&
          parentIds[left] !== parentIds[right]
        ) {
          minDistance = Math.max(
            minDistance,
            knowledgeReservedOrbitPx(
              Math.max(orbitPx[left], orbitPx[right]),
            ),
          );
        }
        let deltaX = x[left] - x[right];
        let deltaY = y[left] - y[right];
        let distance = Math.hypot(deltaX, deltaY);
        if (distance >= minDistance) continue;
        if (distance < 0.5) {
          const seed = `${positions[left].id}:${positions[right].id}`;
          const jitter = hashUnit(seed) * Math.PI * 2;
          deltaX = Math.cos(jitter);
          deltaY = Math.sin(jitter);
          distance = 1;
        }
        // A leaf/entity colliding with a subject yields fully: inserting
        // an article must NEVER move an established subject, even by a
        // pixel of relaxation contact (the contract that adding a memory
        // cannot perturb the map's structure).
        const leftYields =
          mobility[left] === 1 || positions[left].role === "entity";
        const rightYields =
          mobility[right] === 1 || positions[right].role === "entity";
        const leftMobility =
          rightYields && !leftYields ? 0 : mobility[left];
        const rightMobility =
          leftYields && !rightYields ? 0 : mobility[right];
        const share = leftMobility + rightMobility;
        if (share <= 0) continue;
        const push = (minDistance - distance) / distance;
        x[left] += deltaX * push * (leftMobility / share);
        y[left] += deltaY * push * (leftMobility / share);
        x[right] -= deltaX * push * (rightMobility / share);
        y[right] -= deltaY * push * (rightMobility / share);
      }
    }

    for (let index = 0; index < count; index += 1) {
      if (iteration < springIterations || mobility[index] === 0) {
        x[index] += (homeX[index] - x[index]) * homeSpring[index];
        y[index] += (homeY[index] - y[index]) * homeSpring[index];
      }
      // RADIAL ORDERING: a child never rests closer to the Brain than its
      // parent (owner 2026-08-01: reservation pushes shoved Samsung inside
      // Displays — everything radiates outward, at every level).
      if (parentIndexOf[index] >= 0 && mobility[index] > 0) {
        const parentIndex = parentIndexOf[index];
        {
          const parentHub = Math.hypot(
            x[parentIndex] - anchorX,
            y[parentIndex] - anchorY,
          );
          const hubDeltaX = x[index] - anchorX;
          const hubDeltaY = y[index] - anchorY;
          const hubDistance = Math.hypot(hubDeltaX, hubDeltaY);
          const floor = parentHub + 6;
          if (hubDistance > 0.5 && hubDistance < floor) {
            const scale = floor / hubDistance;
            x[index] = anchorX + hubDeltaX * scale;
            y[index] = anchorY + hubDeltaY * scale;
          }
        }
      }
      // Article leaves never collapse inside their reserved outer ring.
      if (minHubDistance[index] > 0) {
        const hubDeltaX = x[index] - anchorX;
        const hubDeltaY = y[index] - anchorY;
        const hubDistance = Math.hypot(hubDeltaX, hubDeltaY);
        if (hubDistance > 0.5 && hubDistance < minHubDistance[index]) {
          const scale = minHubDistance[index] / hubDistance;
          x[index] = anchorX + hubDeltaX * scale;
          y[index] = anchorY + hubDeltaY * scale;
        }
      }
      const clearance = radius[index];
      x[index] = Math.max(minX + clearance, Math.min(maxX - clearance, x[index]));
      y[index] = Math.max(minY + clearance, Math.min(maxY - clearance, y[index]));
    }
  }

  for (let index = 0; index < count; index += 1) {
    if (positions[index].role === "root") continue;
    positions[index].x = x[index] / width;
    positions[index].y = y[index] / height;
  }
}

/**
 * Deterministic bounded force layout. It runs once per snapshot (in a worker
 * in the browser) and never owns an animation/timer loop.
 */
export function layoutKnowledgeGraph(
  input: KnowledgeLayoutInput,
): KnowledgeLayout {
  const count = input.nodes.length;
  if (count === 0) return { nodes: [] };
  if (input.nodes.some((node) => node.role !== undefined)) {
    return layoutKnowledgeHierarchy(input);
  }

  const sorted = [...input.nodes].sort(
    (left, right) =>
      right.degree - left.degree || left.id.localeCompare(right.id),
  );
  const positions = sorted.map((node, index) => {
    const angle =
      index * Math.PI * (3 - Math.sqrt(5)) + hashUnit(node.id) * Math.PI * 2;
    const radius = 0.05 + 0.36 * Math.sqrt((index + 0.5) / count);
    return {
      id: node.id,
      x: 0.5 + Math.cos(angle) * radius,
      y: 0.5 + Math.sin(angle) * radius,
    };
  });
  const indexById = new Map(positions.map((position, index) => [position.id, index]));
  const edges = input.edges
    .map((edge) => [
      indexById.get(edge.source),
      indexById.get(edge.target),
    ] as const)
    .filter(
      (edge): edge is readonly [number, number] =>
        edge[0] !== undefined && edge[1] !== undefined && edge[0] !== edge[1],
    );
  const iterations = count > 1_024 ? 4 : count > 512 ? 7 : count > 256 ? 10 : 16;
  const repel = count > 512 ? 0.000025 : 0.00006;

  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const dx = new Float64Array(count);
    const dy = new Float64Array(count);

    for (let left = 0; left < count; left += 1) {
      for (let right = left + 1; right < count; right += 1) {
        let x = positions[left].x - positions[right].x;
        let y = positions[left].y - positions[right].y;
        let distanceSquared = x * x + y * y;
        if (distanceSquared < 0.0001) {
          x = (hashUnit(`${positions[left].id}:${positions[right].id}`) - 0.5) * 0.02;
          y = (hashUnit(`${positions[right].id}:${positions[left].id}`) - 0.5) * 0.02;
          distanceSquared = Math.max(0.0001, x * x + y * y);
        }
        const force = repel / distanceSquared;
        dx[left] += x * force;
        dy[left] += y * force;
        dx[right] -= x * force;
        dy[right] -= y * force;
      }
    }

    for (const [source, target] of edges) {
      const x = positions[target].x - positions[source].x;
      const y = positions[target].y - positions[source].y;
      const distance = Math.max(0.001, Math.hypot(x, y));
      const force = (distance - 0.12) * 0.025;
      const fx = (x / distance) * force;
      const fy = (y / distance) * force;
      dx[source] += fx;
      dy[source] += fy;
      dx[target] -= fx;
      dy[target] -= fy;
    }

    for (let index = 0; index < count; index += 1) {
      dx[index] += (0.5 - positions[index].x) * 0.012;
      dy[index] += (0.5 - positions[index].y) * 0.012;
      positions[index].x = Math.max(
        0.035,
        Math.min(0.965, positions[index].x + Math.max(-0.025, Math.min(0.025, dx[index]))),
      );
      positions[index].y = Math.max(
        0.035,
        Math.min(0.965, positions[index].y + Math.max(-0.025, Math.min(0.025, dy[index]))),
      );
    }
  }

  return { nodes: positions };
}
