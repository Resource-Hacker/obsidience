// THE ONE knowledge-ball cloud implementation (owner 2026-08-04: "we
// should just have the code for the main one and add the orbit stuff and
// satellite stuff … and just flag it off for the main one"). The main
// executive ball and every satellite build through createKnowledge3dSatellite
// with their own tuning records; the ONLY differences are flags:
//   - satellites orbit/spin (updateOrbit) and render SMALLER via a pure
//     group render transform (ballScale × graphScale) — physics run at
//     FULL scale for every cloud, so collision floors, link rests, and
//     the radialout stratification are numerically identical everywhere
//     (the old shrunk-physics satellites let the unscaled collision
//     padding overwhelm the scaled level spacing and destroyed the
//     pattern);
//   - satellites namespace their node ids (agent:<id>/<nodeId>) at the
//     projection/pointer boundary; the main cloud uses raw ids.
// Everything else — sprites, depth prepass, spoke/branch/cross beams,
// shooting-star streaks, subtree hover, focus reveal, path timeline — is
// the same code with per-cloud uniforms fed by that cloud's own tuning
// record from the Graph Tuning pane.
import * as THREE from "three";
import {
  KNOWLEDGE_3D_ALPHA_MIN,
  KNOWLEDGE_3D_HOVER_ARTICLE_LEVEL,
  KNOWLEDGE_3D_REHEAT_ALPHA,
  KNOWLEDGE_3D_WORLD_SPAN,
  knowledge3dRevealWindow,
  knowledge3dShellRadius,
  knowledge3dNodeSizeMultiplier,
  createKnowledgeForceSimulation,
  knowledge3dBallTargets,
  knowledge3dOrbitPointAt,
  knowledge3dOrbitPosition,
  knowledge3dSpinAngle,
  KNOWLEDGE_3D_DELIVERY_BURST_MS,
  KNOWLEDGE_3D_DELIVERY_FLIGHT_MS,
  KNOWLEDGE_3D_DELIVERY_WAIT_MAX_MS,
  knowledgeDeliveryCometPosition,
  knowledgeAgentNodeId,
  seedKnowledge3dPositions,
  type Knowledge3dBallNode,
  type Knowledge3dPathSpec,
  type Knowledge3dTuning,
  type KnowledgeForceLink,
  type KnowledgeForceNode,
} from "./knowledge-3d";
import type { ForceSimulation } from "d3-force-3d";

/** Leaf sprites carry the plasma-orb halo and star flare, so the quad
 *  extends well past the disc (owner 2026-08-02: the 3D articles are the
 *  same jewel-star plasma orbs as the 2D map). */
const LEAF_SPRITE_EXTENT = 3.2;
const CROSS_SEGMENTS = 12;

export interface Knowledge3dRenderNode {
  id: string;
  /** Normalized 2D radial layout position (0..1, y down). */
  x: number;
  y: number;
  depth?: number;
  role?: string;
  parentId?: string | null;
  /** 2D canvas pixel radius from knowledgeNodeRadius. */
  radius: number;
  subject: boolean;
  /** CSS colors from the shared 2D palette pipeline. */
  core: string;
  dark: string;
  ring: string;
  glow: string;
  ringScale: number;
  ringWidth: number;
  glowScale: number;
  alpha: number;
  /** This node's ring is perforated and spins: auto-curation is visible. */
  autoCurated?: boolean;
}

export interface Knowledge3dRenderEdge {
  source: string;
  target: string;
  /** Exact 2D stroke (rgba CSS) from knowledgeAmbientEdgeStroke. */
  color: string;
  /** Cross-links: the TARGET branch color — the gradient is REVERSED so
   *  the color arriving at each node is the OTHER endpoint's (owner
   *  2026-08-02, matching the 2D map). */
  colorEnd?: string;
  /** Taxonomy edges are the strong springs; cross-links tug weakly. */
  taxonomy: boolean;
}

export interface Knowledge3dSatelliteInput {
  agentId: string;
  nodes: Knowledge3dRenderNode[];
  edges: Knowledge3dRenderEdge[];
  tuning: Knowledge3dTuning;
  /** Normalized hub anchor the seed layout radiates from. Satellites lay
   *  out on a centered unit square (default 0.5/0.5); the main graph
   *  passes its live hub so seeds keep the familiar bearing. */
  hub?: { x: number; y: number };
  /** True for the executive ball: no orbit transform, no ballScale
   *  render shrink, raw node ids in projections. */
  main?: boolean;
}

/** Shader sources + helpers handed over by the scene (its module owns the
 *  canonical strings; passing them keeps the dependency one-directional). */
export interface Knowledge3dSatelliteDeps {
  pointVertexShader: string;
  pointFragmentShader: string;
  pointDepthFragmentShader: string;
  beamVertexShader: string;
  taxonomyFragmentShader: string;
  crossFragmentShader: string;
  particleVertexShader: string;
  particleFragmentShader: string;
  /** The scene's one particle clock — every cloud's shooting stars ride
   *  the same time value object. */
  particleTime: { value: number };
  parseColor: (
    css: string,
  ) => { r: number; g: number; b: number; a: number };
  sharedUniforms: {
    uPerspective: { value: number };
    uPulse: { value: number };
    uTime: { value: number };
  };
  viewportUniform: { value: THREE.Vector2 };
}

/** Physics/geometry signature: a change rebuilds ONLY this cloud. */
export function satellitePhysicsSignature(tuning: Knowledge3dTuning): string {
  return [
    tuning.chargeStrength,
    tuning.velocityDecay,
    tuning.lineArticles,
    tuning.lineBranches,
    tuning.linePeers,
    tuning.linkDistance,
    tuning.sizeCore,
    tuning.sizeBranch,
    tuning.sizeSubnode,
    tuning.sizeChild,
    tuning.sizeArticle,
    tuning.streakCount,
  ].join(":");
}

export interface Knowledge3dSatelliteCloud {
  agentId: string;
  group: THREE.Group;
  builtNodes: Knowledge3dRenderNode[];
  builtEdges: Knowledge3dRenderEdge[];
  builtSignature: string;
  builtTuning: Knowledge3dTuning;
  isHot(): boolean;
  tickIfHot(): boolean;
  captureSimNodes(): ReadonlyMap<string, KnowledgeForceNode>;
  applyTuning(tuning: Knowledge3dTuning, pixelRatio: number): void;
  updateOrbit(tuning: Knowledge3dTuning, timeSeconds: number): void;
  distanceTo(cameraPosition: THREE.Vector3): number;
  projectInto(
    map: Map<string, { x: number; y: number }>,
    camera: THREE.Camera,
  ): void;
  /** Raw (un-namespaced) node id, or null to clear. Lights the WHOLE
   *  subtree exactly like the main ball's hover preview. */
  setHovered(rawId: string | null): void;
  applyPathSpec(spec: Knowledge3dPathSpec | null): void;
  drivePathTimeline(
    beamProgress: number,
    solidProgress: number,
    glow: number,
    flowAge: number,
    headSpan?: number,
  ): void;
  /** Node ignition as the SOLID front passes arrivals; the optional
   *  focus set gates which nodes may light at all (main-ball law). */
  applyFocusReveal(
    spec: Knowledge3dPathSpec | null,
    solidFront: number,
    focus?: { active: boolean; nodeIds: ReadonlySet<string> } | null,
  ): void;
  nodeWorldPosition(rawId: string, out: THREE.Vector3): boolean;
  sortSprites(cameraPosition: THREE.Vector3): void;
  dispose(scene: THREE.Scene): void;
}

export function createKnowledge3dSatellite(
  input: Knowledge3dSatelliteInput,
  deps: Knowledge3dSatelliteDeps,
  viewportHeightPx: number,
  pixelRatio: number,
  previous?: ReadonlyMap<string, KnowledgeForceNode>,
  previousTuning?: Knowledge3dTuning,
): Knowledge3dSatelliteCloud {
  const { agentId, nodes, edges } = input;
  const isMain = input.main === true;
  // Physics run at FULL scale for every cloud; satellites shrink only
  // via the render transform below.
  const tuning = input.tuning;
  const renderBallScale = (live: Knowledge3dTuning): number =>
    isMain ? live.graphScale : live.graphScale * live.ballScale;
  const carriedScale = (depth: number | undefined): number => {
    if (!previousTuning) return 1;
    const d = Math.max(1, depth ?? 3);
    const from = knowledge3dShellRadius(d, previousTuning);
    const to = knowledge3dShellRadius(d, tuning);
    return from > 1e-6 ? to / from : 1;
  };
  const group = new THREE.Group();
  const disposables: Array<{ dispose(): void }> = [];

  const worldPerPx = KNOWLEDGE_3D_WORLD_SPAN / Math.max(1, viewportHeightPx);
  const nodeRadius = (node: Knowledge3dRenderNode): number =>
    node.radius * worldPerPx * knowledge3dNodeSizeMultiplier(tuning, node);
  const nodeIds = nodes.map((node) => node.id);
  const indexById = new Map(nodeIds.map((id, index) => [id, index]));
  const ballNodes: Knowledge3dBallNode[] = nodes.map((node) => ({
    id: node.id,
    x: node.x,
    y: node.y,
    depth: node.depth,
    role: node.role,
    parentId: node.parentId,
    radius: nodeRadius(node),
  }));
  const seeded = seedKnowledge3dPositions(
    knowledge3dBallTargets(ballNodes, input.hub ?? { x: 0.5, y: 0.5 }, tuning),
  );
  const simNodes: KnowledgeForceNode[] = nodes.map((node, index) => {
    const carried = previous?.get(node.id);
    const scale = carried ? carriedScale(node.depth) : 1;
    return {
      id: node.id,
      depth: node.depth,
      role: node.role,
      parentId: node.parentId,
      radius: nodeRadius(node),
      x: carried?.x !== undefined ? carried.x * scale : seeded[index * 3],
      y:
        carried?.y !== undefined
          ? carried.y * scale
          : seeded[index * 3 + 1],
      z:
        carried?.z !== undefined
          ? carried.z * scale
          : seeded[index * 3 + 2],
      vx: carried?.vx ?? 0,
      vy: carried?.vy ?? 0,
      vz: carried?.vz ?? 0,
    };
  });
  const links: KnowledgeForceLink[] = edges
    .filter(
      (edge) => indexById.has(edge.source) && indexById.has(edge.target),
    )
    .map((edge) => ({
      source: edge.source,
      target: edge.target,
      taxonomy: edge.taxonomy,
    }));
  const simulation: ForceSimulation<KnowledgeForceNode> =
    createKnowledgeForceSimulation(simNodes, links, tuning);
  if (previous && previous.size > 0) {
    simulation.alpha(
      previousTuning
        ? Math.max(KNOWLEDGE_3D_REHEAT_ALPHA, 0.5)
        : KNOWLEDGE_3D_REHEAT_ALPHA,
    );
  }
  const positions = new Float32Array(nodes.length * 3);
  const copySimPositions = (): void => {
    for (let i = 0; i < simNodes.length; i += 1) {
      positions[i * 3] = simNodes[i].x ?? 0;
      positions[i * 3 + 1] = simNodes[i].y ?? 0;
      positions[i * 3 + 2] = simNodes[i].z ?? 0;
    }
  };
  copySimPositions();

  // --- Node sprite cloud + depth prepass (identical to the main build).
  const positionAttribute = new THREE.BufferAttribute(positions, 3);
  positionAttribute.setUsage(THREE.DynamicDrawUsage);
  const radii = new Float32Array(nodes.length);
  const extents = new Float32Array(nodes.length);
  const glowScales = new Float32Array(nodes.length);
  const cores = new Float32Array(nodes.length * 3);
  const darks = new Float32Array(nodes.length * 3);
  const rings = new Float32Array(nodes.length * 4);
  const glows = new Float32Array(nodes.length * 4);
  const styles = new Float32Array(nodes.length * 4);
  const focusLevels = new Float32Array(nodes.length);
  const seeds = new Float32Array(nodes.length);
  const curates = new Float32Array(nodes.length);
  nodes.forEach((node, index) => {
    seeds[index] = (index * 0.6180339887) % 1;
    radii[index] = nodeRadius(node);
    extents[index] = node.subject
      ? Math.max(node.glowScale, node.ringScale + 0.3)
      : LEAF_SPRITE_EXTENT;
    glowScales[index] = node.glowScale;
    const core = deps.parseColor(node.core);
    const dark = deps.parseColor(node.dark);
    const ring = deps.parseColor(node.ring);
    const glow = deps.parseColor(node.glow);
    cores[index * 3] = core.r;
    cores[index * 3 + 1] = core.g;
    cores[index * 3 + 2] = core.b;
    darks[index * 3] = dark.r;
    darks[index * 3 + 1] = dark.g;
    darks[index * 3 + 2] = dark.b;
    rings[index * 4] = ring.r;
    rings[index * 4 + 1] = ring.g;
    rings[index * 4 + 2] = ring.b;
    rings[index * 4 + 3] = ring.a;
    glows[index * 4] = glow.r;
    glows[index * 4 + 1] = glow.g;
    glows[index * 4 + 2] = glow.b;
    glows[index * 4 + 3] = glow.a;
    styles[index * 4] =
      node.role === "root" || node.depth === 0
        ? 2
        : node.subject
          ? (node.depth ?? 1) > 1
            ? 1.25
            : 1
          : 0;
    styles[index * 4 + 1] = node.ringScale;
    styles[index * 4 + 2] = node.ringWidth * pixelRatio;
    styles[index * 4 + 3] = node.alpha;
    curates[index] = node.autoCurated ? 1 : 0;
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", positionAttribute);
  geometry.setAttribute("aRadius", new THREE.BufferAttribute(radii, 1));
  geometry.setAttribute("aExtent", new THREE.BufferAttribute(extents, 1));
  geometry.setAttribute("aGlowScale", new THREE.BufferAttribute(glowScales, 1));
  geometry.setAttribute("aCore", new THREE.BufferAttribute(cores, 3));
  geometry.setAttribute("aDark", new THREE.BufferAttribute(darks, 3));
  geometry.setAttribute("aRing", new THREE.BufferAttribute(rings, 4));
  geometry.setAttribute("aGlow", new THREE.BufferAttribute(glows, 4));
  geometry.setAttribute("aStyle", new THREE.BufferAttribute(styles, 4));
  const focusAttribute = new THREE.BufferAttribute(focusLevels, 1);
  focusAttribute.setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute("aFocus", focusAttribute);
  geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
  geometry.setAttribute("aCurate", new THREE.BufferAttribute(curates, 1));
  const drawIndex = new THREE.BufferAttribute(
    new Uint32Array(nodes.length),
    1,
  );
  drawIndex.setUsage(THREE.DynamicDrawUsage);
  geometry.setIndex(drawIndex);
  const sortOrder = Array.from({ length: nodes.length }, (_, i) => i);
  const sortDepths = new Float32Array(nodes.length);

  const glowScaleUniform = { value: input.tuning.nodeGlow };
  const modelScaleUniform = { value: renderBallScale(input.tuning) };
  const articleStyleUniform = { value: input.tuning.articleStyle };
  const coreStyleUniform = { value: input.tuning.coreStyle };
  const subjectStyleUniform = { value: input.tuning.subjectStyle };
  const subnodeStyleUniform = { value: input.tuning.subnodeStyle };
  const ringStyleUniform = { value: input.tuning.ringStyle };
  const pointUniforms = {
    uPerspective: deps.sharedUniforms.uPerspective,
    uPulse: deps.sharedUniforms.uPulse,
    uTime: deps.sharedUniforms.uTime,
    uGlowScale: glowScaleUniform,
    uModelScale: modelScaleUniform,
    uArticleStyle: articleStyleUniform,
    uCoreStyle: coreStyleUniform,
    uSubjectStyle: subjectStyleUniform,
    uSubnodeStyle: subnodeStyleUniform,
    uRingStyle: ringStyleUniform,
  };
  const material = new THREE.ShaderMaterial({
    uniforms: pointUniforms,
    vertexShader: deps.pointVertexShader,
    fragmentShader: deps.pointFragmentShader,
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: THREE.NormalBlending,
  });
  disposables.push(geometry, material);
  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  points.renderOrder = 1;
  group.add(points);
  const depthMaterial = new THREE.ShaderMaterial({
    uniforms: pointUniforms,
    vertexShader: deps.pointVertexShader,
    fragmentShader: deps.pointDepthFragmentShader,
    transparent: false,
    depthWrite: true,
    depthTest: true,
    colorWrite: false,
  });
  disposables.push(depthMaterial);
  const depthPoints = new THREE.Points(geometry, depthMaterial);
  depthPoints.frustumCulled = false;
  depthPoints.renderOrder = 1;
  group.add(depthPoints);

  // --- Taxonomy beams: the main ball's TWO-mesh split — root SPOKES
  // (tendril width, dormant per Brain lines) and deeper BRANCHES (depth
  // taper branchWidth→articleWidth, dormant per Branch/Article lines).
  interface BeamSet {
    pairs: Array<[number, number]>;
    keys: string[];
    mesh: THREE.Mesh;
    geometry: THREE.BufferGeometry;
    arcs: THREE.BufferAttribute;
  }
  let maxNodeDepth = 2;
  const rootIndexes = new Set<number>();
  nodes.forEach((node, index) => {
    if (node.role === "root" || node.depth === 0) rootIndexes.add(index);
    maxNodeDepth = Math.max(maxNodeDepth, node.depth ?? 0);
  });

  const buildBeamSet = (
    pairs: Array<[number, number]>,
    keys: string[],
    colors: number[],
    dormant: number[],
    widths: number[] | null,
    uniforms: Record<string, { value: unknown }>,
  ): BeamSet => {
    const segmentCount = pairs.length;
    const beamGeometry = new THREE.BufferGeometry();
    beamGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(new Float32Array(segmentCount * 12), 3),
    );
    for (const name of ["aStart", "aEnd"]) {
      const attribute = new THREE.BufferAttribute(
        new Float32Array(segmentCount * 12),
        3,
      );
      attribute.setUsage(THREE.DynamicDrawUsage);
      beamGeometry.setAttribute(name, attribute);
    }
    const sides = new Float32Array(segmentCount * 4);
    const end01 = new Float32Array(segmentCount * 4);
    for (let i = 0; i < segmentCount; i += 1) {
      sides[i * 4] = -1;
      sides[i * 4 + 1] = 1;
      sides[i * 4 + 2] = -1;
      sides[i * 4 + 3] = 1;
      end01[i * 4 + 2] = 1;
      end01[i * 4 + 3] = 1;
    }
    beamGeometry.setAttribute("aSide", new THREE.BufferAttribute(sides, 1));
    beamGeometry.setAttribute("aEnd01", new THREE.BufferAttribute(end01, 1));
    const arcs = new THREE.BufferAttribute(
      new Float32Array(segmentCount * 4),
      1,
    );
    arcs.setUsage(THREE.DynamicDrawUsage);
    beamGeometry.setAttribute("aArc", arcs);
    const widthTaper = new Float32Array(segmentCount * 4);
    if (widths) {
      widths.forEach((factor, index) => {
        for (let vertex = 0; vertex < 4; vertex += 1) {
          widthTaper[index * 4 + vertex] = factor;
        }
      });
    }
    beamGeometry.setAttribute(
      "aWidth",
      new THREE.BufferAttribute(widthTaper, 1),
    );
    const pathProgress = new THREE.BufferAttribute(
      new Float32Array(segmentCount * 4).fill(-1),
      1,
    );
    pathProgress.setUsage(THREE.DynamicDrawUsage);
    beamGeometry.setAttribute("aP", pathProgress);
    const hoverFlags = new THREE.BufferAttribute(
      new Float32Array(segmentCount * 4),
      1,
    );
    hoverFlags.setUsage(THREE.DynamicDrawUsage);
    beamGeometry.setAttribute("aHover", hoverFlags);
    const dormantAttr = new Float32Array(segmentCount * 4);
    dormant.forEach((value, index) => {
      for (let vertex = 0; vertex < 4; vertex += 1) {
        dormantAttr[index * 4 + vertex] = value;
      }
    });
    beamGeometry.setAttribute(
      "aDormant",
      new THREE.BufferAttribute(dormantAttr, 1),
    );
    const colorArray = new Float32Array(segmentCount * 12);
    colors.forEach((channel, flat) => {
      const segment = Math.floor(flat / 3);
      const axis = flat % 3;
      for (let vertex = 0; vertex < 4; vertex += 1) {
        colorArray[(segment * 4 + vertex) * 3 + axis] = channel;
      }
    });
    beamGeometry.setAttribute(
      "aColor",
      new THREE.BufferAttribute(colorArray, 3),
    );
    const indices = new Uint32Array(segmentCount * 6);
    for (let i = 0; i < segmentCount; i += 1) {
      const v = i * 4;
      indices.set([v, v + 1, v + 2, v + 2, v + 1, v + 3], i * 6);
    }
    beamGeometry.setIndex(new THREE.BufferAttribute(indices, 1));
    const beamMaterial = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: deps.beamVertexShader,
      fragmentShader: deps.taxonomyFragmentShader,
      transparent: true,
      depthWrite: false,
      depthTest: false,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
    });
    disposables.push(beamGeometry, beamMaterial);
    const mesh = new THREE.Mesh(beamGeometry, beamMaterial);
    mesh.frustumCulled = false;
    mesh.renderOrder = 0;
    group.add(mesh);
    return { pairs, keys, mesh, geometry: beamGeometry, arcs };
  };

  const spokePairs: Array<[number, number]> = [];
  const spokeKeys: string[] = [];
  const spokeColors: number[] = [];
  const spokeDormant: number[] = [];
  const branchPairs: Array<[number, number]> = [];
  const branchKeys: string[] = [];
  const branchColors: number[] = [];
  const branchDormant: number[] = [];
  const branchWidths: number[] = [];
  const crossPairs: Array<[number, number]> = [];
  const crossKeys: string[] = [];
  const crossNear: number[] = [];
  const crossFar: number[] = [];
  for (const edge of edges) {
    const a = indexById.get(edge.source);
    const b = indexById.get(edge.target);
    if (a === undefined || b === undefined) continue;
    const rgba = deps.parseColor(edge.color);
    const key = `${edge.source}|${edge.target}`;
    if (edge.taxonomy && (rootIndexes.has(a) || rootIndexes.has(b))) {
      spokePairs.push([a, b]);
      spokeColors.push(rgba.r, rgba.g, rgba.b);
      spokeKeys.push(key);
      spokeDormant.push(tuning.linePeers >= 0.5 ? 1 : 0);
    } else if (edge.taxonomy) {
      const leafSpoke = !nodes[a].subject || !nodes[b].subject;
      branchPairs.push([a, b]);
      branchColors.push(rgba.r, rgba.g, rgba.b);
      branchKeys.push(key);
      branchDormant.push(
        (leafSpoke ? tuning.lineArticles : tuning.lineBranches) >= 0.5
          ? 1
          : 0,
      );
      const childDepth = Math.max(nodes[a].depth ?? 3, nodes[b].depth ?? 3);
      const span = Math.max(1, maxNodeDepth - 2);
      branchWidths.push(Math.min(1, Math.max(0, (childDepth - 2) / span)));
    } else {
      crossPairs.push([a, b]);
      crossKeys.push(key);
      const near = deps.parseColor(edge.colorEnd ?? edge.color);
      const far = rgba;
      crossNear.push(near.r, near.g, near.b);
      crossFar.push(far.r, far.g, far.b);
    }
  }

  const inertPathUniforms = {
    uBeamP: { value: -1 },
    uSolidP: { value: -1 },
    uGlow: { value: 0 },
    uFlowAge: { value: -1 },
    uHeadSpan: { value: 0.06 },
    uDashFreq: { value: 0.28 },
    uViewportPx: deps.viewportUniform,
  };
  const spokeWidthUniform = {
    value: input.tuning.tendrilWidth * pixelRatio,
  };
  const spokes = buildBeamSet(
    spokePairs,
    spokeKeys,
    spokeColors,
    spokeDormant,
    null,
    {
      ...inertPathUniforms,
      uOpacity: { value: input.tuning.branchOpacity },
      uWidthPx: spokeWidthUniform,
      uFloorPx: spokeWidthUniform,
    },
  );
  const branchUniforms = {
    ...inertPathUniforms,
    uOpacity: { value: input.tuning.branchOpacity },
    uWidthPx: { value: input.tuning.branchWidth * pixelRatio },
    uFloorPx: { value: input.tuning.articleWidth * pixelRatio },
  };
  const branches = buildBeamSet(
    branchPairs,
    branchKeys,
    branchColors,
    branchDormant,
    branchWidths,
    branchUniforms,
  );

  // --- Article cross-links: curved checkered gradient beams. ---
  const crossQuadCount = crossPairs.length * CROSS_SEGMENTS;
  const crossGeometry = new THREE.BufferGeometry();
  crossGeometry.setAttribute(
    "position",
    new THREE.BufferAttribute(new Float32Array(crossQuadCount * 12), 3),
  );
  for (const name of ["aStart", "aEnd"]) {
    const attribute = new THREE.BufferAttribute(
      new Float32Array(crossQuadCount * 12),
      3,
    );
    attribute.setUsage(THREE.DynamicDrawUsage);
    crossGeometry.setAttribute(name, attribute);
  }
  {
    const crossSides = new Float32Array(crossQuadCount * 4);
    const crossEnd01 = new Float32Array(crossQuadCount * 4);
    for (let i = 0; i < crossQuadCount; i += 1) {
      crossSides[i * 4] = -1;
      crossSides[i * 4 + 1] = 1;
      crossSides[i * 4 + 2] = -1;
      crossSides[i * 4 + 3] = 1;
      crossEnd01[i * 4 + 2] = 1;
      crossEnd01[i * 4 + 3] = 1;
    }
    crossGeometry.setAttribute(
      "aSide",
      new THREE.BufferAttribute(crossSides, 1),
    );
    crossGeometry.setAttribute(
      "aEnd01",
      new THREE.BufferAttribute(crossEnd01, 1),
    );
  }
  const crossArcs = new THREE.BufferAttribute(
    new Float32Array(crossQuadCount * 4),
    1,
  );
  crossArcs.setUsage(THREE.DynamicDrawUsage);
  crossGeometry.setAttribute("aArc", crossArcs);
  crossGeometry.setAttribute(
    "aWidth",
    new THREE.BufferAttribute(new Float32Array(crossQuadCount * 4).fill(1), 1),
  );
  const crossPathAttribute = new THREE.BufferAttribute(
    new Float32Array(crossQuadCount * 4).fill(-1),
    1,
  );
  crossPathAttribute.setUsage(THREE.DynamicDrawUsage);
  crossGeometry.setAttribute("aP", crossPathAttribute);
  crossGeometry.setAttribute(
    "aHover",
    new THREE.BufferAttribute(new Float32Array(crossQuadCount * 4), 1),
  );
  crossGeometry.setAttribute(
    "aDormant",
    new THREE.BufferAttribute(new Float32Array(crossQuadCount * 4).fill(1), 1),
  );
  {
    const crossColors = new Float32Array(crossQuadCount * 12);
    crossPairs.forEach((_, pair) => {
      for (let segment = 0; segment < CROSS_SEGMENTS; segment += 1) {
        const quad = pair * CROSS_SEGMENTS + segment;
        const t0 = segment / CROSS_SEGMENTS;
        const t1 = (segment + 1) / CROSS_SEGMENTS;
        for (let vertex = 0; vertex < 4; vertex += 1) {
          const tv = vertex >= 2 ? t1 : t0;
          for (let axis = 0; axis < 3; axis += 1) {
            const near = crossNear[pair * 3 + axis];
            const far = crossFar[pair * 3 + axis];
            crossColors[(quad * 4 + vertex) * 3 + axis] =
              near + (far - near) * tv;
          }
        }
      }
    });
    crossGeometry.setAttribute(
      "aColor",
      new THREE.BufferAttribute(crossColors, 3),
    );
  }
  {
    const crossIndices = new Uint32Array(crossQuadCount * 6);
    for (let i = 0; i < crossQuadCount; i += 1) {
      const v = i * 4;
      crossIndices.set([v, v + 1, v + 2, v + 2, v + 1, v + 3], i * 6);
    }
    crossGeometry.setIndex(new THREE.BufferAttribute(crossIndices, 1));
  }
  const crossWidthUniform = { value: input.tuning.crossWidth * pixelRatio };
  const crossUniforms = {
    ...inertPathUniforms,
    uOpacity: { value: input.tuning.crossOpacity },
    uWidthPx: crossWidthUniform,
    uFloorPx: crossWidthUniform,
    uDashFreq: { value: input.tuning.dashFrequency },
  };
  const crossMaterial = new THREE.ShaderMaterial({
    uniforms: crossUniforms,
    vertexShader: deps.beamVertexShader,
    fragmentShader: deps.crossFragmentShader,
    transparent: true,
    depthWrite: false,
    depthTest: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
  });
  disposables.push(crossGeometry, crossMaterial);
  const crossLines = new THREE.Mesh(crossGeometry, crossMaterial);
  crossLines.frustumCulled = false;
  crossLines.renderOrder = 0;
  crossLines.visible = crossPairs.length > 0;
  group.add(crossLines);

  // --- Shooting-star streaks over the cross curves. ---
  const streaksPerLink = Math.max(0, Math.round(input.tuning.streakCount));
  const streakCount = crossPairs.length * streaksPerLink;
  const streakGeometry = new THREE.BufferGeometry();
  streakGeometry.setAttribute(
    "position",
    new THREE.BufferAttribute(new Float32Array(streakCount * 2 * 3), 3),
  );
  for (const name of ["aP0", "aP1", "aP2"]) {
    const attribute = new THREE.BufferAttribute(
      new Float32Array(streakCount * 2 * 3),
      3,
    );
    attribute.setUsage(THREE.DynamicDrawUsage);
    streakGeometry.setAttribute(name, attribute);
  }
  {
    const phases = new Float32Array(streakCount * 2);
    const speeds = new Float32Array(streakCount * 2);
    const tips = new Float32Array(streakCount * 2);
    for (let streak = 0; streak < streakCount; streak += 1) {
      const phase = (streak * 0.37) % 1;
      const speed = 0.09 + ((streak * 0.61) % 1) * 0.1;
      for (let end = 0; end < 2; end += 1) {
        phases[streak * 2 + end] = phase;
        speeds[streak * 2 + end] = speed;
        tips[streak * 2 + end] = end;
      }
    }
    streakGeometry.setAttribute("aPhase", new THREE.BufferAttribute(phases, 1));
    streakGeometry.setAttribute("aSpeed", new THREE.BufferAttribute(speeds, 1));
    streakGeometry.setAttribute("aTip", new THREE.BufferAttribute(tips, 1));
  }
  const streakUniforms = {
    uTime: deps.particleTime,
    uSpeedScale: { value: input.tuning.streakSpeed },
    uStreakSpan: { value: input.tuning.streakSpan },
  };
  const streakMaterial = new THREE.ShaderMaterial({
    uniforms: streakUniforms,
    vertexShader: deps.particleVertexShader,
    fragmentShader: deps.particleFragmentShader,
    transparent: true,
    depthWrite: false,
    depthTest: true,
    blending: THREE.AdditiveBlending,
  });
  disposables.push(streakGeometry, streakMaterial);
  const streakLines = new THREE.LineSegments(streakGeometry, streakMaterial);
  streakLines.frustumCulled = false;
  streakLines.visible = streakCount > 0;
  // Intra-cloud draw slots (beams 0, orbs 1, streaks 2): everything is
  // depthTest:false except the streaks, so draw order IS the front/behind
  // resolution — a streak passing in FRONT of a node must paint after the
  // node sprite (behind is handled by the opaque depth prepass). The
  // scene's inter-cloud ranking preserves these slots via renderOrder % 4.
  streakLines.renderOrder = 2;
  group.add(streakLines);

  let liveCrossCurve = input.tuning.crossCurve;
  const crossControl = new Float32Array(9);
  const bezierAxis = (
    p0: number,
    p1: number,
    p2: number,
    t: number,
  ): number => {
    const inverse = 1 - t;
    return inverse * inverse * p0 + 2 * inverse * t * p1 + t * t * p2;
  };
  const syncStraightBeams = (set: BeamSet): void => {
    const startAttr = set.geometry.getAttribute(
      "aStart",
    ) as THREE.BufferAttribute;
    const endAttr = set.geometry.getAttribute("aEnd") as THREE.BufferAttribute;
    const arcArray = set.arcs.array as Float32Array;
    set.pairs.forEach(([a, b], index) => {
      const length = Math.hypot(
        positions[b * 3] - positions[a * 3],
        positions[b * 3 + 1] - positions[a * 3 + 1],
        positions[b * 3 + 2] - positions[a * 3 + 2],
      );
      const flip = (ballNodes[a].depth ?? 0) > (ballNodes[b].depth ?? 0);
      for (let vertex = 0; vertex < 4; vertex += 1) {
        const atEnd = vertex >= 2;
        startAttr.setXYZ(
          index * 4 + vertex,
          positions[a * 3],
          positions[a * 3 + 1],
          positions[a * 3 + 2],
        );
        endAttr.setXYZ(
          index * 4 + vertex,
          positions[b * 3],
          positions[b * 3 + 1],
          positions[b * 3 + 2],
        );
        arcArray[index * 4 + vertex] = atEnd === flip ? 0 : length;
      }
    });
    startAttr.needsUpdate = true;
    endAttr.needsUpdate = true;
    set.arcs.needsUpdate = true;
  };
  const syncCrossPositions = (): void => {
    if (crossPairs.length === 0) return;
    const startAttr = crossGeometry.getAttribute(
      "aStart",
    ) as THREE.BufferAttribute;
    const endAttr = crossGeometry.getAttribute("aEnd") as THREE.BufferAttribute;
    const arcArray = crossArcs.array as Float32Array;
    const sample = new Float32Array(6);
    crossPairs.forEach(([a, b], pair) => {
      const x0 = positions[a * 3];
      const y0 = positions[a * 3 + 1];
      const z0 = positions[a * 3 + 2];
      const x2 = positions[b * 3];
      const y2 = positions[b * 3 + 1];
      const z2 = positions[b * 3 + 2];
      const mx = (x0 + x2) / 2;
      const my = (y0 + y2) / 2;
      const mz = (z0 + z2) / 2;
      const length = Math.hypot(x2 - x0, y2 - y0, z2 - z0);
      const radial = Math.hypot(mx, my, mz);
      const bulge = Math.max(2.5, length * liveCrossCurve);
      const scale = radial > 1e-3 ? 1 + bulge / radial : 1;
      crossControl[0] = x0;
      crossControl[1] = y0;
      crossControl[2] = z0;
      crossControl[3] = radial > 1e-3 ? mx * scale : mx;
      crossControl[4] = radial > 1e-3 ? my * scale : my + bulge;
      crossControl[5] = radial > 1e-3 ? mz * scale : mz;
      crossControl[6] = x2;
      crossControl[7] = y2;
      crossControl[8] = z2;
      for (let segment = 0; segment < CROSS_SEGMENTS; segment += 1) {
        const t0 = segment / CROSS_SEGMENTS;
        const t1 = (segment + 1) / CROSS_SEGMENTS;
        for (let axis = 0; axis < 3; axis += 1) {
          sample[axis] = bezierAxis(
            crossControl[axis],
            crossControl[3 + axis],
            crossControl[6 + axis],
            t0,
          );
          sample[3 + axis] = bezierAxis(
            crossControl[axis],
            crossControl[3 + axis],
            crossControl[6 + axis],
            t1,
          );
        }
        const quad = pair * CROSS_SEGMENTS + segment;
        for (let vertex = 0; vertex < 4; vertex += 1) {
          startAttr.setXYZ(quad * 4 + vertex, sample[0], sample[1], sample[2]);
          endAttr.setXYZ(quad * 4 + vertex, sample[3], sample[4], sample[5]);
          arcArray[quad * 4 + vertex] = (vertex >= 2 ? t1 : t0) * length;
        }
      }
      if (streaksPerLink > 0) {
        const p0Attr = streakGeometry.getAttribute(
          "aP0",
        ) as THREE.BufferAttribute;
        const p1Attr = streakGeometry.getAttribute(
          "aP1",
        ) as THREE.BufferAttribute;
        const p2Attr = streakGeometry.getAttribute(
          "aP2",
        ) as THREE.BufferAttribute;
        for (let particle = 0; particle < streaksPerLink * 2; particle += 1) {
          const vertex = pair * streaksPerLink * 2 + particle;
          p0Attr.setXYZ(
            vertex,
            crossControl[0],
            crossControl[1],
            crossControl[2],
          );
          p1Attr.setXYZ(
            vertex,
            crossControl[3],
            crossControl[4],
            crossControl[5],
          );
          p2Attr.setXYZ(
            vertex,
            crossControl[6],
            crossControl[7],
            crossControl[8],
          );
        }
        p0Attr.needsUpdate = true;
        p1Attr.needsUpdate = true;
        p2Attr.needsUpdate = true;
      }
    });
    startAttr.needsUpdate = true;
    endAttr.needsUpdate = true;
    crossArcs.needsUpdate = true;
  };
  const syncAllPositions = (): void => {
    syncStraightBeams(spokes);
    syncStraightBeams(branches);
    syncCrossPositions();
  };
  syncAllPositions();

  // --- Hover subtree (main-ball law): flag every taxonomy beam whose
  // BOTH endpoints sit in the hovered node's subtree; subtree articles
  // light at the hover article level.
  const childrenByParent = new Map<string, string[]>();
  for (const node of nodes) {
    if (node.parentId == null) continue;
    const siblings = childrenByParent.get(node.parentId) ?? [];
    siblings.push(node.id);
    childrenByParent.set(node.parentId, siblings);
  }
  const subtreeIds = (rootId: string): Set<string> => {
    const out = new Set<string>([rootId]);
    const queue = [rootId];
    while (queue.length) {
      const current = queue.pop()!;
      for (const child of childrenByParent.get(current) ?? []) {
        if (!out.has(child)) {
          out.add(child);
          queue.push(child);
        }
      }
    }
    return out;
  };
  let hoverSubtree: Set<string> | null = null;
  let hoveredIndex = -1;
  const revealLevels = new Float32Array(nodes.length);
  const fillHoverFlags = (set: BeamSet): void => {
    const attribute = set.geometry.getAttribute(
      "aHover",
    ) as THREE.BufferAttribute;
    const array = attribute.array as Float32Array;
    set.keys.forEach((key, index) => {
      let value = 0;
      if (hoverSubtree) {
        const split = key.indexOf("|");
        if (
          hoverSubtree.has(key.slice(0, split)) &&
          hoverSubtree.has(key.slice(split + 1))
        ) {
          value = 1;
        }
      }
      for (let vertex = 0; vertex < 4; vertex += 1) {
        array[index * 4 + vertex] = value;
      }
    });
    attribute.needsUpdate = true;
  };
  const applyHoverLevels = (): void => {
    let dirty = false;
    for (let i = 0; i < nodeIds.length; i += 1) {
      const inSubtree = hoverSubtree?.has(nodeIds[i]) ?? false;
      const hoverLevel =
        i === hoveredIndex
          ? 0.7
          : inSubtree && !nodes[i].subject
            ? KNOWLEDGE_3D_HOVER_ARTICLE_LEVEL
            : 0;
      const level = Math.max(revealLevels[i], hoverLevel);
      if (Math.abs(focusLevels[i] - level) > 0.01) {
        focusLevels[i] = level;
        dirty = true;
      }
    }
    if (dirty) focusAttribute.needsUpdate = true;
  };

  const localCamera = new THREE.Vector3();
  const projectionVector = new THREE.Vector3();

  return {
    agentId,
    group,
    builtNodes: nodes,
    builtEdges: edges,
    builtSignature: satellitePhysicsSignature(input.tuning),
    builtTuning: input.tuning,
    isHot() {
      return simulation.alpha() > KNOWLEDGE_3D_ALPHA_MIN;
    },
    tickIfHot() {
      if (simulation.alpha() <= KNOWLEDGE_3D_ALPHA_MIN) return false;
      simulation.tick();
      copySimPositions();
      positionAttribute.needsUpdate = true;
      syncAllPositions();
      return true;
    },
    captureSimNodes() {
      return new Map(simNodes.map((node) => [node.id, node]));
    },
    applyTuning(live: Knowledge3dTuning, ratio: number) {
      glowScaleUniform.value = live.nodeGlow;
      const ballFactor = renderBallScale(live);
      modelScaleUniform.value = ballFactor;
      articleStyleUniform.value = live.articleStyle;
      coreStyleUniform.value = live.coreStyle;
      subjectStyleUniform.value = live.subjectStyle;
      subnodeStyleUniform.value = live.subnodeStyle;
      ringStyleUniform.value = live.ringStyle;
      group.scale.setScalar(ballFactor);
      spokeWidthUniform.value = live.tendrilWidth * ratio * ballFactor;
      (spokes.mesh.material as THREE.ShaderMaterial).uniforms.uOpacity.value =
        live.branchOpacity;
      branchUniforms.uOpacity.value = live.branchOpacity;
      branchUniforms.uWidthPx.value = live.branchWidth * ratio * ballFactor;
      branchUniforms.uFloorPx.value = live.articleWidth * ratio * ballFactor;
      crossUniforms.uOpacity.value = live.crossOpacity;
      crossWidthUniform.value = live.crossWidth * ratio * ballFactor;
      crossUniforms.uDashFreq.value = live.dashFrequency;
      // Taxonomy beams' flow-phase dashes ride the same slider (the cross
      // uniforms override this key with their own object above).
      inertPathUniforms.uDashFreq.value = live.dashFrequency;
      if (live.crossCurve !== liveCrossCurve) {
        liveCrossCurve = live.crossCurve;
        syncCrossPositions();
      }
      streakUniforms.uSpeedScale.value = live.streakSpeed;
      streakUniforms.uStreakSpan.value = live.streakSpan;
    },
    updateOrbit(live: Knowledge3dTuning, timeSeconds: number) {
      if (isMain) return;
      const at = knowledge3dOrbitPosition(agentId, live, timeSeconds);
      group.position.set(at.x, at.y, at.z);
      group.rotation.y = knowledge3dSpinAngle(agentId, live, timeSeconds);
    },
    distanceTo(cameraPosition: THREE.Vector3) {
      return cameraPosition.distanceTo(group.position);
    },
    projectInto(map, camera) {
      group.updateMatrixWorld();
      for (let i = 0; i < nodeIds.length; i += 1) {
        projectionVector
          .set(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2])
          .applyMatrix4(group.matrixWorld)
          .applyMatrix4(camera.matrixWorldInverse);
        // An orbiting cloud can pass behind the camera plane, where
        // .project() mirrors the NDC — skip those nodes.
        if (projectionVector.z >= 0) continue;
        projectionVector.applyMatrix4(camera.projectionMatrix);
        map.set(
          isMain ? nodeIds[i] : knowledgeAgentNodeId(agentId, nodeIds[i]),
          {
            x: (projectionVector.x + 1) / 2,
            y: (1 - projectionVector.y) / 2,
          },
        );
      }
    },
    setHovered(rawId) {
      const index = rawId === null ? -1 : (indexById.get(rawId) ?? -1);
      if (
        index === hoveredIndex &&
        (rawId === null) === (hoverSubtree === null)
      ) {
        return;
      }
      hoveredIndex = index;
      hoverSubtree = rawId !== null ? subtreeIds(rawId) : null;
      fillHoverFlags(spokes);
      fillHoverFlags(branches);
      applyHoverLevels();
    },
    applyPathSpec(spec) {
      for (const set of [spokes, branches]) {
        const attribute = set.geometry.getAttribute(
          "aP",
        ) as THREE.BufferAttribute;
        const array = attribute.array as Float32Array;
        set.keys.forEach((key, index) => {
          const span = spec?.edgeSpans.get(key);
          const atSource = span
            ? span.fromSource
              ? span.from
              : span.to
            : -1;
          const atTarget = span
            ? span.fromSource
              ? span.to
              : span.from
            : -1;
          for (let vertex = 0; vertex < 4; vertex += 1) {
            array[index * 4 + vertex] = vertex >= 2 ? atTarget : atSource;
          }
        });
        attribute.needsUpdate = true;
      }
      if (crossPairs.length > 0) {
        const crossArray = crossPathAttribute.array as Float32Array;
        crossKeys.forEach((key, pair) => {
          const span = spec?.edgeSpans.get(key);
          for (let segment = 0; segment < CROSS_SEGMENTS; segment += 1) {
            const quad = pair * CROSS_SEGMENTS + segment;
            const t0 = segment / CROSS_SEGMENTS;
            const t1 = (segment + 1) / CROSS_SEGMENTS;
            for (let vertex = 0; vertex < 4; vertex += 1) {
              const tv = vertex >= 2 ? t1 : t0;
              let value = -1;
              if (span) {
                const shape = span.meet
                  ? 1 - Math.abs(2 * tv - 1)
                  : span.fromSource
                    ? tv
                    : 1 - tv;
                value = span.from + (span.to - span.from) * shape;
              }
              crossArray[quad * 4 + vertex] = value;
            }
          }
        });
        crossPathAttribute.needsUpdate = true;
      }
      if (!spec) this.drivePathTimeline(-1, -1, 0, -1);
    },
    drivePathTimeline(beamProgress, solidProgress, glow, flowAge, headSpan) {
      inertPathUniforms.uBeamP.value = beamProgress;
      inertPathUniforms.uSolidP.value = solidProgress;
      inertPathUniforms.uGlow.value = glow;
      inertPathUniforms.uFlowAge.value = flowAge;
      if (headSpan !== undefined) {
        inertPathUniforms.uHeadSpan.value = headSpan;
      }
    },
    applyFocusReveal(spec, solidFront, focus) {
      const revealWindow = knowledge3dRevealWindow(
        spec?.firstArticleProgress ?? 1,
      );
      let dirty = false;
      for (let i = 0; i < nodeIds.length; i += 1) {
        const gated =
          focus !== undefined && focus !== null
            ? focus.active && focus.nodeIds.has(nodeIds[i])
            : true;
        let reveal = 0;
        if (gated && spec) {
          // Nodes ignite as the SOLID line reaches their plan arrival; a
          // focus-set node the plan never routed (e.g. a relation-reached
          // endpoint) ramps at the route end, never instantly (main-ball
          // law). Without a focus gate (the satellite test sweep) only
          // routed nodes may light.
          const arrival = spec.nodeArrival.get(nodeIds[i]);
          if (arrival !== undefined) {
            reveal = Math.min(
              1,
              Math.max(0, (solidFront - arrival) / revealWindow),
            );
          } else if (focus) {
            reveal = Math.min(
              1,
              Math.max(0, (solidFront - spec.maxProgress) / revealWindow),
            );
          }
        } else if (gated && focus) {
          // Focus without a plan (the path has not arrived yet, or a
          // plan-less selection): lit fully, exactly the pre-plan law.
          reveal = 1;
        }
        if (Math.abs(revealLevels[i] - reveal) > 0.01) {
          revealLevels[i] = reveal;
          dirty = true;
        }
      }
      if (dirty) applyHoverLevels();
    },
    nodeWorldPosition(rawId, out) {
      const index = indexById.get(rawId);
      if (index === undefined) return false;
      group.updateMatrixWorld();
      out
        .set(
          positions[index * 3],
          positions[index * 3 + 1],
          positions[index * 3 + 2],
        )
        .applyMatrix4(group.matrixWorld);
      return true;
    },
    sortSprites(cameraPosition) {
      group.updateMatrixWorld();
      group.worldToLocal(localCamera.copy(cameraPosition));
      for (let i = 0; i < sortOrder.length; i += 1) {
        const dx = positions[i * 3] - localCamera.x;
        const dy = positions[i * 3 + 1] - localCamera.y;
        const dz = positions[i * 3 + 2] - localCamera.z;
        sortDepths[i] = dx * dx + dy * dy + dz * dz;
      }
      sortOrder.sort((a, b) => sortDepths[b] - sortDepths[a]);
      const indexArray = drawIndex.array as Uint32Array;
      for (let i = 0; i < sortOrder.length; i += 1) {
        indexArray[i] = sortOrder[i];
      }
      drawIndex.needsUpdate = true;
    },
    dispose(scene) {
      scene.remove(group);
      for (const disposable of disposables) disposable.dispose();
    },
  };
}

/** Visible orbital ring (owner 2026-08-03): the satellite's ACTUAL path —
 *  the same knowledge3dOrbitPointAt geometry the live orbit rides — drawn
 *  as a closed loop of beam quads with the article links' dashed dormant
 *  styling (aP stays -1 forever). The ring lives at the SCENE root: it is
 *  the path, so it neither orbits nor spins. */
const ORBIT_RING_SEGMENTS = 128;

export interface Knowledge3dOrbitRingDeps {
  beamVertexShader: string;
  crossFragmentShader: string;
  parseColor: (
    css: string,
  ) => { r: number; g: number; b: number; a: number };
  viewportUniform: { value: THREE.Vector2 };
}

export interface Knowledge3dOrbitRing {
  agentId: string;
  object: THREE.Mesh;
  update(live: Knowledge3dTuning, pixelRatio: number): void;
  dispose(scene: THREE.Scene): void;
}

export function createKnowledge3dOrbitRing(
  agentId: string,
  ringColorCss: string,
  deps: Knowledge3dOrbitRingDeps,
): Knowledge3dOrbitRing {
  const segments = ORBIT_RING_SEGMENTS;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.BufferAttribute(new Float32Array(segments * 12), 3),
  );
  const startAttr = new THREE.BufferAttribute(
    new Float32Array(segments * 12),
    3,
  );
  const endAttr = new THREE.BufferAttribute(
    new Float32Array(segments * 12),
    3,
  );
  startAttr.setUsage(THREE.DynamicDrawUsage);
  endAttr.setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute("aStart", startAttr);
  geometry.setAttribute("aEnd", endAttr);
  const sides = new Float32Array(segments * 4);
  const end01 = new Float32Array(segments * 4);
  for (let i = 0; i < segments; i += 1) {
    sides[i * 4] = -1;
    sides[i * 4 + 1] = 1;
    sides[i * 4 + 2] = -1;
    sides[i * 4 + 3] = 1;
    end01[i * 4 + 2] = 1;
    end01[i * 4 + 3] = 1;
  }
  geometry.setAttribute("aSide", new THREE.BufferAttribute(sides, 1));
  geometry.setAttribute("aEnd01", new THREE.BufferAttribute(end01, 1));
  const arcs = new THREE.BufferAttribute(new Float32Array(segments * 4), 1);
  arcs.setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute("aArc", arcs);
  geometry.setAttribute(
    "aWidth",
    new THREE.BufferAttribute(new Float32Array(segments * 4), 1),
  );
  geometry.setAttribute(
    "aP",
    new THREE.BufferAttribute(new Float32Array(segments * 4).fill(-1), 1),
  );
  geometry.setAttribute(
    "aHover",
    new THREE.BufferAttribute(new Float32Array(segments * 4), 1),
  );
  geometry.setAttribute(
    "aDormant",
    new THREE.BufferAttribute(new Float32Array(segments * 4).fill(1), 1),
  );
  const rgba = deps.parseColor(ringColorCss);
  const colors = new Float32Array(segments * 12);
  for (let vertex = 0; vertex < segments * 4; vertex += 1) {
    colors[vertex * 3] = rgba.r;
    colors[vertex * 3 + 1] = rgba.g;
    colors[vertex * 3 + 2] = rgba.b;
  }
  geometry.setAttribute("aColor", new THREE.BufferAttribute(colors, 3));
  const indices = new Uint32Array(segments * 6);
  for (let i = 0; i < segments; i += 1) {
    const v = i * 4;
    indices.set([v, v + 1, v + 2, v + 2, v + 1, v + 3], i * 6);
  }
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  const widthUniform = { value: 2.5 };
  const uniforms = {
    uViewportPx: deps.viewportUniform,
    uWidthPx: widthUniform,
    uFloorPx: widthUniform,
    uOpacity: { value: 0.35 },
    uDashFreq: { value: 0.28 },
    uBeamP: { value: -1 },
    uSolidP: { value: -1 },
    uGlow: { value: 0 },
    uFlowAge: { value: -1 },
    uHeadSpan: { value: 0.06 },
  };
  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: deps.beamVertexShader,
    fragmentShader: deps.crossFragmentShader,
    transparent: true,
    depthWrite: false,
    depthTest: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.frustumCulled = false;
  mesh.renderOrder = -1;

  let builtRadius = Number.NaN;
  let builtTilt = Number.NaN;
  const rewriteLoop = (live: Knowledge3dTuning): void => {
    const startArray = startAttr.array as Float32Array;
    const endArray = endAttr.array as Float32Array;
    const arcArray = arcs.array as Float32Array;
    let arc = 0;
    let previous = knowledge3dOrbitPointAt(agentId, live, 0);
    for (let i = 0; i < segments; i += 1) {
      const theta0 = (i / segments) * Math.PI * 2;
      const theta1 = ((i + 1) / segments) * Math.PI * 2;
      const from = i === 0
        ? previous
        : knowledge3dOrbitPointAt(agentId, live, theta0);
      const to = knowledge3dOrbitPointAt(agentId, live, theta1);
      const length = Math.hypot(to.x - from.x, to.y - from.y, to.z - from.z);
      for (let vertex = 0; vertex < 4; vertex += 1) {
        const flat = (i * 4 + vertex) * 3;
        startArray[flat] = from.x;
        startArray[flat + 1] = from.y;
        startArray[flat + 2] = from.z;
        endArray[flat] = to.x;
        endArray[flat + 1] = to.y;
        endArray[flat + 2] = to.z;
        arcArray[i * 4 + vertex] = vertex >= 2 ? arc + length : arc;
      }
      arc += length;
      previous = to;
    }
    startAttr.needsUpdate = true;
    endAttr.needsUpdate = true;
    arcs.needsUpdate = true;
  };

  return {
    agentId,
    object: mesh,
    update(live, pixelRatio) {
      if (live.orbitRadius !== builtRadius || live.orbitTilt !== builtTilt) {
        builtRadius = live.orbitRadius;
        builtTilt = live.orbitTilt;
        rewriteLoop(live);
      }
      widthUniform.value = live.orbitLineWidth * pixelRatio;
      uniforms.uOpacity.value = live.orbitLineOpacity;
      uniforms.uDashFreq.value = live.dashFrequency;
    },
    dispose(scene) {
      scene.remove(mesh);
      geometry.dispose();
      material.dispose();
    },
  };
}

/** A delivery comet (owner 2026-08-04): when an agent's finished job files
 *  an article into another graph, the article itself flies — a white-hot
 *  head with a fading trail — from the source ball's center to the new
 *  node, then bursts as the node's arrival flash. Scene-root parented like
 *  the orbit rings (both endpoints live in world space on MOVING clouds:
 *  the head re-resolves source and target every frame). */
export interface Knowledge3dDeliveryComet {
  key: string;
  object: THREE.Points;
  /** Advance one frame. `from`/`to` resolve lazily because the target node
   *  may not exist until the refreshed cloud rebuilds; `perspective` is
   *  the scene's shared point-size scale. Returns "active" while animating,
   *  "done" after the arrival burst, "expired" if the target never
   *  materialized inside the wait budget. */
  update(
    nowMs: number,
    resolveFrom: (out: THREE.Vector3) => boolean,
    resolveTo: (out: THREE.Vector3) => boolean,
    perspective: number,
  ): "active" | "done" | "expired";
  dispose(scene: THREE.Scene): void;
}

const DELIVERY_TRAIL_POINTS = 14;

const DELIVERY_VERTEX_SHADER = `
attribute float aTrail;
uniform float uPerspective;
uniform float uBurst;
varying float vTrail;
void main() {
  vTrail = aTrail;
  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  float head = 1.0 - smoothstep(0.0, 0.15, aTrail);
  float size = (10.0 - aTrail * 7.5) * (1.0 + uBurst * 3.0 * head);
  gl_PointSize = clamp(
    size * uPerspective * 0.02 / max(1.0, -mvPosition.z),
    1.5,
    160.0
  );
  gl_Position = projectionMatrix * mvPosition;
}
`;

const DELIVERY_FRAGMENT_SHADER = `
uniform float uBurst;
varying float vTrail;
void main() {
  vec2 p = gl_PointCoord - 0.5;
  float d = length(p) * 2.0;
  float core = 1.0 - smoothstep(0.0, 0.45, d);
  float halo = 1.0 - smoothstep(0.2, 1.0, d);
  vec3 hot = vec3(1.0, 1.0, 1.0);
  vec3 tail = vec3(0.42, 0.86, 1.0);
  vec3 color = mix(hot, tail, smoothstep(0.0, 0.7, vTrail));
  float alpha = (core + halo * 0.5) * (1.0 - vTrail * 0.85);
  alpha *= 1.0 - uBurst * 0.55;
  if (alpha < 0.01) discard;
  gl_FragColor = vec4(color * (1.0 + uBurst * 1.5), alpha);
}
`;

export function createKnowledge3dDeliveryComet(
  key: string,
  scene: THREE.Scene,
): Knowledge3dDeliveryComet {
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(DELIVERY_TRAIL_POINTS * 3);
  const trail = new Float32Array(DELIVERY_TRAIL_POINTS);
  for (let i = 0; i < DELIVERY_TRAIL_POINTS; i += 1) {
    trail[i] = i / (DELIVERY_TRAIL_POINTS - 1);
  }
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("aTrail", new THREE.BufferAttribute(trail, 1));
  const uniforms = {
    uPerspective: { value: 1 },
    uBurst: { value: 0 },
  };
  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: DELIVERY_VERTEX_SHADER,
    fragmentShader: DELIVERY_FRAGMENT_SHADER,
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: THREE.AdditiveBlending,
  });
  const object = new THREE.Points(geometry, material);
  object.frustumCulled = false;
  // Above every cloud block (occlusion ranks run rank*4 + [0..3]); a comet
  // between graphs cannot honestly z-sort against either, so it draws last.
  object.renderOrder = 200;
  object.visible = false;
  scene.add(object);

  const fromPoint = new THREE.Vector3();
  const toPoint = new THREE.Vector3();
  const head = new THREE.Vector3();
  let createdAt = -1;
  let flightStartedAt = -1;
  let burstStartedAt = -1;
  let trailPrimed = false;

  const writeHead = (point: THREE.Vector3, catchUp: boolean) => {
    if (catchUp || !trailPrimed) {
      for (let i = 0; i < DELIVERY_TRAIL_POINTS; i += 1) {
        positions[i * 3] = point.x;
        positions[i * 3 + 1] = point.y;
        positions[i * 3 + 2] = point.z;
      }
      trailPrimed = true;
    } else {
      for (let i = DELIVERY_TRAIL_POINTS - 1; i >= 1; i -= 1) {
        positions[i * 3] = positions[(i - 1) * 3];
        positions[i * 3 + 1] = positions[(i - 1) * 3 + 1];
        positions[i * 3 + 2] = positions[(i - 1) * 3 + 2];
      }
      positions[0] = point.x;
      positions[1] = point.y;
      positions[2] = point.z;
    }
    (geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate =
      true;
  };

  return {
    key,
    object,
    update(nowMs, resolveFrom, resolveTo, perspective) {
      if (createdAt < 0) createdAt = nowMs;
      uniforms.uPerspective.value = perspective;
      const hasFrom = resolveFrom(fromPoint);
      const hasTo = resolveTo(toPoint);
      if (flightStartedAt < 0) {
        if (!hasFrom || !hasTo) {
          return nowMs - createdAt > KNOWLEDGE_3D_DELIVERY_WAIT_MAX_MS
            ? "expired"
            : "active";
        }
        flightStartedAt = nowMs;
        object.visible = true;
      }
      if (burstStartedAt < 0) {
        const t = (nowMs - flightStartedAt) / KNOWLEDGE_3D_DELIVERY_FLIGHT_MS;
        const at = knowledgeDeliveryCometPosition(fromPoint, toPoint, t);
        head.set(at.x, at.y, at.z);
        writeHead(head, false);
        if (t >= 1) burstStartedAt = nowMs;
        return "active";
      }
      const burstT = (nowMs - burstStartedAt) / KNOWLEDGE_3D_DELIVERY_BURST_MS;
      // The burst holds on the (still-moving) target node: the arrival
      // flash IS the node igniting, so it must ride the node's position.
      if (resolveTo(toPoint)) writeHead(toPoint, true);
      uniforms.uBurst.value = Math.min(1, burstT);
      return burstT >= 1 ? "done" : "active";
    },
    dispose(scene) {
      scene.remove(object);
      geometry.dispose();
      material.dispose();
    },
  };
}
