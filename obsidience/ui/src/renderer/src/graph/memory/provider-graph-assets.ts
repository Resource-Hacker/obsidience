import * as THREE from "three";
import {
  POINT_VERTEX_SHADER, POINT_FRAGMENT_SHADER, BEAM_VERTEX_SHADER, CROSS_PATH_FRAGMENT_SHADER,
} from "@/graph/knowledge/knowledge-3d-shaders";
import type { ProviderNode, ProviderEdge } from "@/lib/api";
import { memoryRelationshipWeight } from "./memory-time-layout";

/** Provider data adapted to the Knowledge graph's actual orb and beam shaders. */
export function providerGraphAssets(nodes: ProviderNode[], pixelRatio: number) {
  const geometry = new THREE.BufferGeometry();
  const attribute = (name: string, size: number) => {
    const value = new THREE.BufferAttribute(new Float32Array(nodes.length * size), size);
    geometry.setAttribute(name, value);
    return value;
  };
  attribute("position", 3).setUsage(THREE.DynamicDrawUsage);
  const radius = attribute("aRadius", 1), extent = attribute("aExtent", 1);
  const glowScale = attribute("aGlowScale", 1), core = attribute("aCore", 3);
  const dark = attribute("aDark", 3), ring = attribute("aRing", 4), glow = attribute("aGlow", 4);
  const style = attribute("aStyle", 4);
  attribute("aFocus", 1).setUsage(THREE.DynamicDrawUsage);
  attribute("aActivity", 4);
  attribute("aSeed", 1); attribute("aCurate", 1);
  const textureSize = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
  const positions = new THREE.DataTexture(new Float32Array(textureSize ** 2 * 4), textureSize, textureSize, THREE.RGBAFormat, THREE.FloatType);
  const colors = new THREE.DataTexture(new Float32Array(textureSize ** 2 * 4), textureSize, textureSize, THREE.RGBAFormat, THREE.FloatType);
  nodes.forEach((node, i) => {
    const c = new THREE.Color(node.color);
    // Provider colors/types remain native; only their visual assets are shared.
    radius.setX(i, node.kind === "observation" ? 4.8 : 3.2);
    extent.setX(i, 3.2); glowScale.setX(i, 2.5);
    core.setXYZ(i, c.r, c.g, c.b); dark.setXYZ(i, c.r * 0.2, c.g * 0.2, c.b * 0.2);
    ring.setXYZW(i, c.r, c.g, c.b, 0.5); glow.setXYZW(i, c.r, c.g, c.b, 0.16);
    style.setXYZW(i, 0, 1.3, pixelRatio, 0.8);
    (colors.image.data as Float32Array).set([c.r, c.g, c.b, 1], i * 4);
  });
  colors.needsUpdate = true;
  const pointMaterial = new THREE.ShaderMaterial({
    defines: {KNOWLEDGE_PROVIDER: 1, KNOWLEDGE_MEMORY: 1}, vertexShader: POINT_VERTEX_SHADER, fragmentShader: POINT_FRAGMENT_SHADER,
    uniforms: {uPerspective: {value: 1}, uPulse: {value: 0}, uSpeechLevel: {value: 0}, uTime: {value: 0},
      uGlowScale: {value: 0.7}, uModelScale: {value: 1}, uActivityOpacity: {value: 1}, uProviderOpacity: {value: 1},
      uArticleStyle: {value: 0}, uCoreStyle: {value: 1}, uSubjectStyle: {value: 0}, uSubnodeStyle: {value: 0}, uRingStyle: {value: 0}},
    transparent: true, depthWrite: false, depthTest: false, blending: THREE.NormalBlending,
  });
  const points = new THREE.Points(geometry, pointMaterial);
  points.frustumCulled = false; points.renderOrder = 1;

  // One indexed ribbon is instanced for each native link.
  // Its curve is evaluated on the GPU using the same Knowledge beam extrusion.
  const ribbons = new THREE.InstancedBufferGeometry();
  const vertices: number[] = [], indices: number[] = [];
  const segments = 8;
  for (let s = 0; s < segments; s++) {
    for (const [side, end] of [[-1, 0], [1, 0], [-1, 1], [1, 1]]) vertices.push(s / segments, side, end);
    const base = s * 4; indices.push(base, base + 2, base + 1, base + 2, base + 3, base + 1);
  }
  ribbons.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
  ribbons.setIndex(indices); ribbons.instanceCount = 0;
  const lineMaterial = new THREE.ShaderMaterial({
    defines: {KNOWLEDGE_PROVIDER: 1, KNOWLEDGE_MEMORY_LINKS: 1},
    vertexShader: BEAM_VERTEX_SHADER, fragmentShader: CROSS_PATH_FRAGMENT_SHADER,
    uniforms: {uPositions: {value: positions}, uNodeColors: {value: colors}, uTextureSize: {value: textureSize},
      uSelected: {value: -1}, uHovered: {value: -1}, uCurve: {value: 1}, uOverview: {value: 1},
      // A Memory link is a hairline at rest and a wide dashed tendril while lit.
      uViewportPx: {value: new THREE.Vector2(1, 1)}, uWidthPx: {value: 2.2 * pixelRatio}, uFloorPx: {value: 2.2 * pixelRatio},
      uOpacity: {value: 1}, uDashFreq: {value: 0.085}, uPathOpacity: {value: 1},
      uClock: {value: 0}, uReach: {value: 100}, uLivePx: {value: 7 * pixelRatio},
      uBeamP: {value: -1}, uSolidP: {value: -1}, uGlow: {value: 0}, uFlowAge: {value: -1}, uHeadSpan: {value: 0.06}},
    transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
  });
  const lines = new THREE.Mesh(ribbons, lineMaterial);
  lines.frustumCulled = false;
  return {points, lines, positions, colors};
}

/** The most links a Memory bank draws at rest. */
const MEMORY_REST_LINKS = 1400;

/** Overview is a legible subset, never a truncation of the native graph.
 * Keep each node's two strongest ties; selecting/hovering adds every incident
 * edge. Build the adjacency once, not by scanning the bank on every frame. */
export function providerLinkIndex(nodes: ProviderNode[], edges: ProviderEdge[]) {
  const adjacency = new Map<string, number[]>();
  const scores = edges.map(edge => memoryRelationshipWeight(edge));
  edges.forEach((edge, index) => {
    for (const id of [edge.source, edge.target]) {
      const list = adjacency.get(id) || []; list.push(index); adjacency.set(id, list);
    }
  });
  const overview = new Set<number>();
  // At rest a bank shows its skeleton: each record's strongest specific tie
  // (evidence, cause, meaning), thinned evenly to what a row can carry.
  // Shared entities and the order of time join in on hover, selection and
  // while an operation holds both ends.
  const strongest = new Set<number>();
  for (const node of nodes) {
    let best = -1;
    for (const i of adjacency.get(node.id) || []) if (scores[i] >= 0.5 && (best < 0 || scores[i] > scores[best])) best = i;
    if (best >= 0) strongest.add(best);
  }
  const keep = Math.max(1, Math.ceil(strongest.size / MEMORY_REST_LINKS));
  let at = 0;
  for (const i of strongest) if (at++ % keep === 0) overview.add(i);
  return {adjacency, overview};
}
