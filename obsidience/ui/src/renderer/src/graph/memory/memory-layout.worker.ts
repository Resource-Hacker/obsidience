import { memoryLayout } from "./memory-time-layout";
import type { ForceSimulationNode, ForceSimulation } from "d3-force-3d";

type Node = ForceSimulationNode & {id: string};
let simulation: ForceSimulation<Node> | null = null;
// One step in flight, driven by the owning visible stage. No autonomous timer.
self.onmessage = (event: MessageEvent) => {
  if (event.data.type === "init") {
    simulation?.stop();
    const nodes: Node[] = event.data.nodes;
    const pairs: Float32Array = event.data.pairs;
    function* links() {
      for (let i = 0; i < pairs.length; i += 3)
        yield {source: nodes[pairs[i]].id, target: nodes[pairs[i + 1]].id, weight: pairs[i + 2]};
    }
    simulation = memoryLayout(nodes, links(), event.data.alpha);
  } else if (event.data.type === "step") simulation?.tick(1);
  if (!simulation) return;
  const positions = new Float32Array(simulation.nodes().length * 6);
  simulation.nodes().forEach((node, i) => positions.set([
    node.x || 0, node.y || 0, node.z || 0, node.vx || 0, node.vy || 0, node.vz || 0,
  ], i * 6));
  self.postMessage({positions, alpha: simulation.alpha()}, {transfer: [positions.buffer]});
};
