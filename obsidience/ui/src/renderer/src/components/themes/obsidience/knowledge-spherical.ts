// Coupled geometric constraints for one knowledge cloud. No renderer, timer,
// graph authority, or second integrator: the existing d3 tick owns this force.

export interface SphericalNode {
  id: string;
  parentId?: string | null;
  depth?: number;
  role?: string;
  radius: number;
  x?: number; y?: number; z?: number;
  vx?: number; vy?: number; vz?: number;
}

export interface SphericalResiduals {
  maxShellError: number;
  maxOverlap: number;
  maxOutwardViolation: number;
  maxTerritoryViolation: number;
  maxStepDisplacement: number;
}

export type SphericalStatus = "settling" | "settled" | "needs-capacity" | "stalled";

export interface SphericalLayerState {
  depth: number;
  radius: number;
  inputKey: string;
  expansions: number;
}

export interface SphericalState {
  signature: string;
  ticks: number;
  stableTicks: number;
  status: SphericalStatus;
  layers: SphericalLayerState[];
  residuals: SphericalResiduals;
}

export interface SphericalOptions {
  velocityDecay: number;
  alphaMin: number;
  radii: ReadonlyMap<number, number>;
  avoidance: (node: SphericalNode) => number;
  /** Force inputs, excluding paint. Used only to retain solver continuity. */
  signature: string;
  previous?: SphericalState;
}

export interface SphericalConstraint {
  (alpha: number): void;
  capture(): SphericalState;
  needsTick(): boolean;
}

const EPS = 1e-10;
const PASSES = 12;
const MAX_TURN = 0.16;
const STABLE_TICKS = 8;
const MAX_TICKS = 880;
const MAX_EXPANSIONS = 8;
const clamp = (x: number, lo = -1, hi = 1): number => Math.max(lo, Math.min(hi, x));
const finite = (x: number | undefined): number => Number.isFinite(x) ? x! : 0;
const isRoot = (n: SphericalNode): boolean => n.role === "root" || n.depth === 0;
const zeroResiduals = (): SphericalResiduals => ({
  maxShellError: 0, maxOverlap: 0, maxOutwardViolation: 0,
  maxTerritoryViolation: 0, maxStepDisplacement: 0,
});

/** Exact minimum angle between two avoidance spheres on fixed shells.
 * Infinity is an explicitly impossible pair; a zero-radius Brain is handled
 * without dividing by its shell radius. */
export function sphericalClearanceAngle(ri: number, rj: number, distance: number): number {
  if (![ri, rj, distance].every(Number.isFinite) || Math.min(ri, rj, distance) < 0)
    throw new RangeError("Shell radii and separation must be finite and nonnegative");
  if (distance <= Math.abs(ri - rj)) return 0;
  if (distance > ri + rj || ri * rj === 0) return Infinity;
  return Math.acos(clamp((ri * ri + rj * rj - distance * distance) / (2 * ri * rj)));
}

/** Jointly solve contacts, outward edges and recursively nested territories
 * on the spheres themselves. A contact is never repaired radially and then
 * undone by a subsequent normalization. */
export function createSphericalConstraint(
  input: readonly SphericalNode[], options: SphericalOptions,
): SphericalConstraint {
  const nodes = [...input].sort((a, b) => a.id.localeCompare(b.id));
  const n = nodes.length;
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const depth = nodes.map(node => isRoot(node) ? 0 : (node.depth ?? 3));
  const avoid = nodes.map(node => Math.max(EPS, options.avoidance(node)));
  const parent = new Int32Array(n).fill(-1);
  const children: number[][] = Array.from({ length: n }, () => []);
  const members: number[][] = Array.from({ length: n }, () => []);
  const memberships: { fork: number; owner: number }[][] = Array.from({ length: n }, () => []);
  // Only attested, acyclic chains terminating at a Brain own a territory.
  for (let i = 0; i < n; i++) {
    if (isRoot(nodes[i])) continue;
    let current = i;
    const seen = new Set<number>();
    while (current >= 0 && !isRoot(nodes[current]) && !seen.has(current)) {
      seen.add(current);
      const p = index.get(nodes[current].parentId ?? "") ?? -1;
      if (p < 0 || depth[p] + 1 !== depth[current]) { current = -1; break; }
      current = p;
    }
    if (current >= 0 && isRoot(nodes[current])) {
      parent[i] = index.get(nodes[i].parentId!)!;
      children[parent[i]].push(i);
    }
  }
  for (let i = 0; i < n; i++) {
    for (let at = i; at >= 0; at = parent[at]) members[at].push(i);
    let owner = i;
    for (let fork = parent[i]; fork >= 0; owner = fork, fork = parent[fork]) {
      // A branch root owns its direction; its descendants fit the crown.
      if (owner !== i && children[fork].length > 1) memberships[i].push({ fork, owner });
    }
  }
  const forks = children.map((list, i) => list.length > 1 ? i : -1).filter(i => i >= 0)
    .sort((a, b) => depth[a] - depth[b] || a - b);
  const ascending = nodes.map((_, i) => i).sort((a, b) => depth[a] - depth[b] || a - b);
  const layerDepths = [...options.radii.keys()].sort((a, b) => a - b);
  const previousLayers = new Map(options.previous?.layers.map(layer => [layer.depth, layer]) ?? []);
  const layers: SphericalLayerState[] = layerDepths.map(d => {
    // Descendants cannot change an unchanged inner layer's capacity record.
    const inputKey = JSON.stringify([options.radii.get(d), nodes.filter((_, i) => depth[i] <= d)
      .map(node => [node.id, node.parentId, node.depth, node.role, options.avoidance(node)])]);
    const previous = previousLayers.get(d);
    const carry = previous?.inputKey === inputKey && Number.isFinite(previous.radius)
      && previous.radius >= options.radii.get(d)!;
    return { depth: d, inputKey, radius: carry ? previous!.radius : options.radii.get(d)!,
      expansions: carry ? previous!.expansions : 0 };
  });
  const layerByDepth = new Map(layers.map(layer => [layer.depth, layer]));
  const radii = new Float64Array(n);
  const demand = new Float64Array(n);
  const directions = new Float64Array(n * 3);
  const before = new Float64Array(n * 3);
  const damping = clamp(1 - options.velocityDecay, 0, 1);
  const cellSize = avoid.reduce((largest, radius) => Math.max(largest, radius), 1) * 2;
  const tolerance = Math.max(1e-5, avoid.reduce((smallest, radius) => Math.min(smallest, radius), 1) * 1e-3);
  const motionTolerance = Math.max(1e-4, tolerance * 2);
  const signature = options.signature;
  const same = options.previous?.signature === signature;
  let ticks = same ? options.previous!.ticks : 0;
  let stableTicks = same ? options.previous!.stableTicks : 0;
  let status: SphericalStatus = same ? options.previous!.status : "settling";
  let residuals = same ? { ...options.previous!.residuals } : zeroResiduals();
  let capacityDepth = Infinity;

  function updateCapacity(): void {
    let lastRadius = 0, lastSize = 0;
    for (const layer of layers) {
      const size = Math.max(0, ...avoid.filter((_, i) => depth[i] === layer.depth));
      if (layer.depth > 0) layer.radius = Math.max(layer.radius, lastRadius + lastSize + size);
      lastRadius = layer.radius; lastSize = size;
    }
    for (let i = 0; i < n; i++) radii[i] = layerByDepth.get(depth[i])?.radius ?? 0;
    for (let i = 0; i < n; i++) {
      const area = new Map<number, number>();
      for (const j of members[i]) area.set(depth[j], (area.get(depth[j]) ?? 0) + avoid[j] ** 2);
      demand[i] = Math.sqrt(Math.max(EPS, ...[...area].map(([d, a]) =>
        a / Math.max(EPS, layerByDepth.get(d)!.radius ** 2))));
    }
  }
  updateCapacity();

  function normalize(i: number, x: number, y: number, z: number): void {
    let length = Math.hypot(x, y, z);
    if (length < EPS || !Number.isFinite(length)) {
      let hash = 2166136261;
      for (const char of nodes[i].id) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
      const phase = (hash >>> 0) / 4294967296 * Math.PI * 2;
      y = ((Math.imul(hash, 1597334677) >>> 0) / 4294967296) * 2 - 1;
      const span = Math.sqrt(Math.max(0, 1 - y * y));
      x = span * Math.cos(phase); z = span * Math.sin(phase); length = 1;
    }
    directions[i * 3] = x / length;
    directions[i * 3 + 1] = y / length;
    directions[i * 3 + 2] = z / length;
  }
  function dot(i: number, j: number): number {
    return clamp(directions[i * 3] * directions[j * 3]
      + directions[i * 3 + 1] * directions[j * 3 + 1]
      + directions[i * 3 + 2] * directions[j * 3 + 2]);
  }
  function tangent(i: number, x: number, y: number, z: number): [number, number, number] {
    const k = i * 3, along = x * directions[k] + y * directions[k + 1] + z * directions[k + 2];
    x -= along * directions[k]; y -= along * directions[k + 1]; z -= along * directions[k + 2];
    let length = Math.hypot(x, y, z);
    if (length < EPS) {
      const axis = [Math.abs(directions[k]), Math.abs(directions[k + 1]), Math.abs(directions[k + 2])];
      const a = axis.indexOf(Math.min(...axis));
      const u = directions[k + a];
      x = Number(a === 0) - u * directions[k];
      y = Number(a === 1) - u * directions[k + 1];
      z = Number(a === 2) - u * directions[k + 2];
      length = Math.hypot(x, y, z);
    }
    return [x / length, y / length, z / length];
  }
  function turn(i: number, t: readonly number[], angle: number): void {
    const k = i * 3, c = Math.cos(angle), s = Math.sin(angle);
    normalize(i, directions[k] * c + t[0] * s,
      directions[k + 1] * c + t[1] * s, directions[k + 2] * c + t[2] * s);
  }
  function toward(i: number, x: number, y: number, z: number, angle: number): void {
    turn(i, tangent(i, x, y, z), Math.min(MAX_TURN, angle));
  }
  // Rotate a crown together, preserving its internal radii and relative angles.
  function rotateCrown(i: number, t: readonly number[], angle: number): void {
    const k = i * 3, ux = directions[k], uy = directions[k + 1], uz = directions[k + 2];
    const ax = uy * t[2] - uz * t[1], ay = uz * t[0] - ux * t[2], az = ux * t[1] - uy * t[0];
    const c = Math.cos(angle), s = Math.sin(angle);
    for (const j of members[i]) {
      const q = j * 3, x = directions[q], y = directions[q + 1], z = directions[q + 2];
      const along = (ax * x + ay * y + az * z) * (1 - c);
      normalize(j, x * c + (ay * z - az * y) * s + ax * along,
        y * c + (az * x - ax * z) * s + ay * along,
        z * c + (ax * y - ay * x) * s + az * along);
    }
  }
  function spreadCrowns(alpha: number): void {
    // A low-amplitude Thomson-style tangential pressure, not fixed sectors.
    // Descendant demand supplies pressure even when a branch root is small.
    for (const fork of forks) {
      const siblings = children[fork];
      for (const i of siblings) {
        let x = 0, y = 0, z = 0;
        for (const j of siblings) {
          if (i === j) continue;
          const c = dot(i, j), denominator = Math.max(0.04, 2 - 2 * c);
          const weight = clamp(demand[j] / Math.max(EPS, demand[i]), 0.25, 4) / denominator;
          x -= directions[j * 3] * weight;
          y -= directions[j * 3 + 1] * weight;
          z -= directions[j * 3 + 2] * weight;
        }
        const along = x * directions[i * 3] + y * directions[i * 3 + 1] + z * directions[i * 3 + 2];
        const length = Math.hypot(x - along * directions[i * 3],
          y - along * directions[i * 3 + 1], z - along * directions[i * 3 + 2]);
        if (length > EPS) rotateCrown(i, tangent(i, x, y, z),
          Math.min(0.025, alpha * 0.015 * length / Math.sqrt(siblings.length)));
      }
    }
  }
  function boundaries(solve: boolean): void {
    for (const i of ascending) {
      const p = parent[i];
      if (p >= 0 && radii[p] > 0 && radii[i] > 0) {
        const c = dot(i, p), floor = radii[p] / radii[i];
        const missing = Math.max(0, radii[p] - radii[i] * c);
        if (solve && missing > tolerance * 0.1) toward(i, directions[p * 3],
          directions[p * 3 + 1], directions[p * 3 + 2],
          Math.acos(c) - Math.acos(clamp(floor)));
        else if (!solve) {
          residuals.maxOutwardViolation = Math.max(residuals.maxOutwardViolation, missing);
          if (missing > tolerance) capacityDepth = Math.min(capacityDepth, depth[i]);
        }
      }
      for (const { fork, owner } of memberships[i]) for (const other of children[fork]) {
        if (other === owner || radii[i] <= 0) continue;
        let x = directions[owner * 3] - directions[other * 3];
        let y = directions[owner * 3 + 1] - directions[other * 3 + 1];
        let z = directions[owner * 3 + 2] - directions[other * 3 + 2];
        const length = Math.hypot(x, y, z);
        if (length < EPS) continue; // Contacts separate coincident fork roots.
        x /= length; y /= length; z /= length;
        // Capacity-weighted moving bisector. The bounded bias preserves each
        // root's ownership while giving larger crowns more angular area.
        const bias = 0.8 * length * 0.5 * (demand[owner] - demand[other])
          / Math.max(EPS, demand[owner] + demand[other]);
        const marginAngle = Math.asin(clamp(-bias)) + Math.asin(clamp(avoid[i] / radii[i], 0, 1));
        const floor = Math.sin(Math.min(Math.PI / 2, marginAngle));
        const c = clamp(x * directions[i * 3] + y * directions[i * 3 + 1] + z * directions[i * 3 + 2]);
        const missing = Math.max(0, floor - c) * radii[i];
        if (solve && missing > tolerance * 0.1) toward(i, x, y, z, Math.acos(c) - Math.acos(floor));
        else if (!solve) {
          residuals.maxTerritoryViolation = Math.max(residuals.maxTerritoryViolation, missing);
          if (missing > tolerance) capacityDepth = Math.min(capacityDepth, depth[i]);
        }
      }
    }
  }
  function contacts(solve: boolean): void {
    // World-space broad phase only finds candidates. Narrow-phase corrections
    // are great-circle rotations on the assigned shells, never radial pushes.
    const size = cellSize;
    const grid = new Map<string, number[]>();
    const key = (x: number, y: number, z: number): string => `${x},${y},${z}`;
    for (let i = 0; i < n; i++) {
      const k = i * 3, r = radii[i];
      const gx = Math.floor(directions[k] * r / size), gy = Math.floor(directions[k + 1] * r / size);
      const gz = Math.floor(directions[k + 2] * r / size);
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
        for (const j of grid.get(key(gx + dx, gy + dy, gz + dz)) ?? []) {
          const required = avoid[i] + avoid[j];
          if (Math.abs(r - radii[j]) >= required) continue;
          const c = dot(i, j);
          const distance = Math.sqrt(Math.max(0, r * r + radii[j] ** 2 - 2 * r * radii[j] * c));
          const overlap = Math.max(0, required - distance);
          if (!solve) {
            residuals.maxOverlap = Math.max(residuals.maxOverlap, overlap);
            if (overlap > tolerance) capacityDepth = Math.min(capacityDepth, Math.max(depth[i], depth[j]));
          } else if (overlap > tolerance * 0.1) {
            const minimum = sphericalClearanceAngle(r, radii[j], required);
            if (!Number.isFinite(minimum)) continue;
            const angle = Math.min(MAX_TURN, minimum - Math.acos(c) + 1e-7);
            const ti = tangent(i, -directions[j * 3], -directions[j * 3 + 1], -directions[j * 3 + 2]);
            const tj = c > 1 - 1e-10 ? ti.map(value => -value)
              : tangent(j, -directions[i * 3], -directions[i * 3 + 1], -directions[i * 3 + 2]);
            const weight = radii[j] ** 2 / (r * r + radii[j] ** 2);
            turn(i, ti, angle * weight); turn(j, tj, angle * (1 - weight));
          }
        }
      }
      const bin = key(gx, gy, gz), list = grid.get(bin) ?? [];
      list.push(i); grid.set(bin, list);
    }
  }
  function measure(step: number): void {
    residuals = zeroResiduals(); residuals.maxStepDisplacement = step;
    capacityDepth = Infinity;
    contacts(false); boundaries(false);
  }
  function read(initial: boolean): void {
    for (let i = 0; i < n; i++) {
      const node = nodes[i], k = i * 3;
      before[k] = finite(node.x); before[k + 1] = finite(node.y); before[k + 2] = finite(node.z);
      normalize(i, before[k] + (initial ? 0 : finite(node.vx) * damping),
        before[k + 1] + (initial ? 0 : finite(node.vy) * damping),
        before[k + 2] + (initial ? 0 : finite(node.vz) * damping));
    }
  }
  // Initialization projects radius only; valid carried positions AND velocities
  // remain byte-identical through a paint-only rebuild.
  read(true);
  for (let i = 0; i < n; i++) {
    const node = nodes[i], r = radii[i];
    if (Math.abs(Math.hypot(finite(node.x), finite(node.y), finite(node.z)) - r) <= 1e-7) continue;
    node.x = directions[i * 3] * r; node.y = directions[i * 3 + 1] * r; node.z = directions[i * 3 + 2] * r;
  }
  if (!same) measure(Infinity);

  const force = ((alpha: number): void => {
    ticks++;
    read(false);
    spreadCrowns(alpha);
    for (let pass = 0; pass < PASSES; pass++) {
      boundaries(true); contacts(true);
      if (pass % 3 === 2) {
        measure(0);
        if (Math.max(residuals.maxOverlap, residuals.maxOutwardViolation,
          residuals.maxTerritoryViolation) <= tolerance * 0.25) break;
      }
    }
    measure(0);
    // Local capacity failures expand a WHOLE layer, never a single node and
    // never an unchanged inner layer. The finite retry policy is observable.
    if (alpha <= options.alphaMin && ticks % 32 === 0 && capacityDepth < Infinity) {
      const layer = layerByDepth.get(capacityDepth);
      if (layer && layer.depth > 0 && layer.expansions < MAX_EXPANSIONS) {
        layer.radius *= 1.08; layer.expansions++;
        updateCapacity(); stableTicks = 0;
        for (let pass = 0; pass < PASSES; pass++) { boundaries(true); contacts(true); }
        measure(0);
      }
    }
    let step = 0;
    for (let i = 0; i < n; i++) {
      const node = nodes[i], k = i * 3, r = radii[i];
      const x = directions[k] * r, y = directions[k + 1] * r, z = directions[k + 2] * r;
      residuals.maxShellError = Math.max(residuals.maxShellError, Math.abs(Math.hypot(x, y, z) - r));
      step = Math.max(step, Math.hypot(x - before[k], y - before[k + 1], z - before[k + 2]));
      if (damping > EPS) {
        node.vx = (x - before[k]) / damping;
        node.vy = (y - before[k + 1]) / damping;
        node.vz = (z - before[k + 2]) / damping;
      } else {
        node.x = x; node.y = y; node.z = z;
        node.vx = node.vy = node.vz = 0;
      }
    }
    residuals.maxStepDisplacement = step;
    const valid = Math.max(residuals.maxShellError, residuals.maxOverlap, residuals.maxOutwardViolation,
      residuals.maxTerritoryViolation) <= tolerance;
    stableTicks = valid && step <= motionTolerance ? stableTicks + 1 : 0;
    status = alpha <= options.alphaMin && stableTicks >= STABLE_TICKS ? "settled"
      : ticks >= MAX_TICKS && alpha <= options.alphaMin
        ? (valid ? "stalled" : "needs-capacity") : "settling";
  }) as SphericalConstraint;
  force.capture = () => ({ signature, ticks, stableTicks, status,
    layers: layers.map(layer => ({ ...layer })), residuals: { ...residuals } });
  force.needsTick = () => status === "settling";
  return force;
}
