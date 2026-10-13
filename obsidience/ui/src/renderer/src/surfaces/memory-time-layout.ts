import { forceSimulation, forceLink, forceManyBody, forceCollide, forceCenter, forceY, forceZ, type ForceSimulationNode } from "d3-force-3d";
import type { ProviderNode, ProviderEdge } from "./provider-graph-scene";

export interface MemoryLens { center: number; radius: number }
export interface MemoryTimeAxis {
  start: number; end: number; length: number; origin: number;
  position: (id: string) => number;
  dateAt: (fraction: number) => number;
  range: (from: number, to: number) => string[];
}

function unit(id: string, salt: number): number {
  let hash = 2166136261 ^ salt;
  for (let i = 0; i < id.length; i++) hash = Math.imul(hash ^ id.charCodeAt(i), 16777619);
  hash = Math.imul(hash ^ (hash >>> 16), 0x85ebca6b);
  hash = Math.imul(hash ^ (hash >>> 13), 0xc2b2ae35);
  return ((hash ^ (hash >>> 16)) >>> 0) / 4294967296;
}

/** Strictly increasing magnifier: nearby time expands, distant spacing stays
 * compact. Guides and nodes use exactly the same map; chronology cannot fold. */
export function memoryLensX(x: number, lens: MemoryLens | null): number {
  return lens ? x + 4 * lens.radius * Math.atan((x - lens.center) / lens.radius) : x;
}

export function memoryLens(axis: MemoryTimeAxis, ids: string[]): MemoryLens | null {
  const positions = ids.map(axis.position).filter(x => x >= axis.origin);
  if (!positions.length) return null;
  let start = Infinity, end = -Infinity;
  for (const x of positions) { start = Math.min(start, x); end = Math.max(end, x); }
  return {center: (start + end) / 2, radius: Math.max(45, (end - start) / 2)};
}

/** Original activity-spaced chronology. The native force layout owns y/z;
 * there is no prescribed pitch, radius, phase, or count per revolution. */
export function memoryTimeAxis(nodes: ProviderNode[]): MemoryTimeAxis | null {
  const dated = nodes.map(n => ({id: n.id, time: Date.parse(n.date || "")}))
    .filter(n => Number.isFinite(n.time))
    .sort((a, b) => a.time - b.time || a.id.localeCompare(b.id));
  if (!dated.length) return null;
  const ranks = new Map(dated.map((n, i) => [n.id, i]));
  const length = Math.max(640, Math.sqrt(nodes.length) * 34), origin = -length / 2;
  const position = (id: string) => ranks.has(id)
    ? dated.length === 1 ? 0 : origin + ranks.get(id)! / (dated.length - 1) * length : origin - 100;
  return {start: dated[0].time, end: dated[dated.length - 1].time, length, origin, position,
    dateAt: fraction => dated[Math.round(Math.max(0, Math.min(1, fraction)) * (dated.length - 1))].time,
    range: (from, to) => dated.filter(n => n.time >= from && n.time <= to).map(n => n.id)};
}

export function memoryInitialOffset(id: string) {
  const angle = unit(id, 0) * Math.PI * 2, radius = 96 * Math.sqrt(unit(id, 1));
  return {y: Math.cos(angle) * radius, z: Math.sin(angle) * radius};
}

/** Shared entities are broad context; semantic and evidence links are specific. */
export function memoryRelationshipWeight(edge: ProviderEdge): number {
  const weight = Number.isFinite(edge.weight) ? Math.max(0, Math.min(1, edge.weight!)) : 1;
  const kind = edge.kind === "temporal" ? 0 : edge.kind === "entity" ? 0.06
    : edge.kind === "supports" || edge.kind === "caused_by" ? 1 : 0.8;
  return weight * kind;
}

/** The earlier organic layout, intentionally retained as the owner's preferred
 * shape. The inspection lens never feeds transformed positions into physics. */
export function memoryLayout<N extends ForceSimulationNode & {id: string}>(nodes: N[], edges: Iterable<{source: string; target: string; weight: number}>, alpha: number) {
  const byId = new Map(nodes.map(n => [n.id, n]));
  const pairs = new Map<string, {source: string; target: string; weight: number; distance: number; strength: number}>();
  for (const edge of edges) {
    const weight = edge.weight;
    if (!weight || edge.source === edge.target) continue;
    const [source, target] = [edge.source, edge.target].sort();
    const key = source + "\0" + target;
    if ((pairs.get(key)?.weight || 0) >= weight) continue;
    const timeGap = (byId.get(source)?.fx || 0) - (byId.get(target)?.fx || 0);
    pairs.set(key, {source, target, weight, distance: Math.hypot(timeGap, 38), strength: 0});
  }
  const links = [...pairs.values()].sort((a, b) => a.source.localeCompare(b.source) || a.target.localeCompare(b.target));
  const degree = new Map<string, number>();
  for (const link of links) for (const id of [link.source, link.target]) degree.set(id, (degree.get(id) || 0) + link.weight);
  for (const link of links) link.strength = 0.9 * link.weight
    / Math.max(1, Math.sqrt(degree.get(link.source)! * degree.get(link.target)!));
  const simulation = forceSimulation(nodes, 3).stop()
    .force("charge", forceManyBody().strength(-24).distanceMax(220))
    .force("links", forceLink(links).id((n: N) => n.id)
      .distance((link: typeof links[number]) => link.distance)
      .strength((link: typeof links[number]) => link.strength))
    .force("collision", forceCollide(6).strength(0.8))
    .force("center", forceCenter(0, 0, 0))
    .force("tube-y", forceY(0).strength(0.035))
    .force("tube-z", forceZ(0).strength(0.035))
    .alphaDecay(0.035).alpha(alpha);
  for (const node of nodes) if (node.fx != null) node.x = node.fx;
  return simulation;
}
