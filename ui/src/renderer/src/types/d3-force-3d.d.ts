// Minimal typings for d3-force-3d (the engine behind vasturiano's
// 3d-force-graph). Only the surface the knowledge scene uses is declared.
declare module "d3-force-3d" {
  export interface ForceSimulationNode {
    index?: number;
    x?: number;
    y?: number;
    z?: number;
    vx?: number;
    vy?: number;
    vz?: number;
    fx?: number | null;
    fy?: number | null;
    fz?: number | null;
  }

  export interface ForceSimulation<N extends ForceSimulationNode> {
    tick(iterations?: number): ForceSimulation<N>;
    alpha(): number;
    alpha(alpha: number): ForceSimulation<N>;
    alphaMin(): number;
    alphaMin(min: number): ForceSimulation<N>;
    alphaDecay(): number;
    alphaDecay(decay: number): ForceSimulation<N>;
    alphaTarget(): number;
    alphaTarget(target: number): ForceSimulation<N>;
    velocityDecay(): number;
    velocityDecay(decay: number): ForceSimulation<N>;
    force(name: string, force: unknown | null): ForceSimulation<N>;
    nodes(): N[];
    nodes(nodes: N[]): ForceSimulation<N>;
    stop(): ForceSimulation<N>;
    restart(): ForceSimulation<N>;
  }

  export function forceSimulation<N extends ForceSimulationNode>(
    nodes?: N[],
    numDimensions?: number,
  ): ForceSimulation<N>;

  export interface ForceLink {
    (alpha: number): void;
    id(accessor: (node: never) => string): ForceLink;
    distance(accessor: number | ((link: never) => number)): ForceLink;
    strength(accessor: number | ((link: never) => number)): ForceLink;
    iterations(iterations: number): ForceLink;
  }
  export function forceLink(links?: unknown[]): ForceLink;

  export interface ForceManyBody {
    (alpha: number): void;
    strength(strength: number | ((node: never) => number)): ForceManyBody;
    distanceMax(distance: number): ForceManyBody;
    theta(theta: number): ForceManyBody;
  }
  export function forceManyBody(): ForceManyBody;

  export interface ForceCollide {
    (alpha: number): void;
    radius(accessor: number | ((node: never) => number)): ForceCollide;
    strength(strength: number): ForceCollide;
    iterations(iterations: number): ForceCollide;
  }
  export function forceCollide(
    radius?: number | ((node: never) => number),
  ): ForceCollide;

  export interface ForceRadial {
    (alpha: number): void;
    radius(accessor: number | ((node: never) => number)): ForceRadial;
    strength(strength: number | ((node: never) => number)): ForceRadial;
  }
  export function forceRadial(
    radius: number | ((node: never) => number),
    x?: number,
    y?: number,
    z?: number,
  ): ForceRadial;

  export function forceCenter(x?: number, y?: number, z?: number): unknown;

  export interface ForceAxis {
    (alpha: number): void;
    x?(accessor: number | ((node: never) => number)): ForceAxis;
    y?(accessor: number | ((node: never) => number)): ForceAxis;
    strength(strength: number | ((node: never) => number)): ForceAxis;
  }
  export function forceX(
    x?: number | ((node: never) => number),
  ): ForceAxis;
  export function forceY(
    y?: number | ((node: never) => number),
  ): ForceAxis;
}
