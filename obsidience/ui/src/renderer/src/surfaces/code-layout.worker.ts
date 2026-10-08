import {
  createKnowledgeForceSimulation, knowledge3dBallTargets, knowledge3dSimulationNeedsTick,
  type KnowledgeForceNode,
} from "@/components/themes/obsidience/knowledge-3d";
import { codeSphericalHierarchy } from "./code-spherical-layout";
import type { ForceSimulation } from "d3-force-3d";

let simulation: ForceSimulation<KnowledgeForceNode> | null = null;
// Same spherical solver as Knowledge; the visible stage owns the clock.
self.onmessage = (event: MessageEvent) => {
  if (event.data.type === "init") {
    simulation?.stop();
    const {nodes, links} = codeSphericalHierarchy(event.data.graph);
    const seeds = knowledge3dBallTargets(nodes.map(node => ({...node, x: 0, y: 0})), {x: 0, y: 0});
    const previous = new Map<string, KnowledgeForceNode>(event.data.previous.map((node: KnowledgeForceNode) => [node.id, node]));
    nodes.forEach((node, i) => {
      const carried = previous.get(node.id);
      Object.assign(node, carried ? {x: carried.x, y: carried.y, z: carried.z, vx: carried.vx, vy: carried.vy, vz: carried.vz}
        : {x: seeds[i * 3], y: seeds[i * 3 + 1], z: seeds[i * 3 + 2]});
    });
    // Code has thousands of leaves and much deeper containment than Articles.
    // Its parent springs group branches; recursive angular clipping would force
    // deep sibling boundaries onto one bearing and explode the contact fit.
    // Retain the shared radial layers, collision, cooling and root constraint.
    simulation = createKnowledgeForceSimulation(nodes, links)
      .force("branchSeparation", null).alpha(previous.size ? 0.4 : 1);
    // A saved edit must not shuffle the file being read. Only new members
    // settle around the carried, fixed members; the file root remains pinned.
    if (event.data.preserve) for (const node of nodes) if (previous.has(node.id)) {
      // The shared factory projects initial coordinates onto fresh shells.
      // Restore the saved coordinates after acquisition, then pin them.
      const carried = previous.get(node.id)!;
      node.x = node.fx = carried.x; node.y = node.fy = carried.y; node.z = node.fz = carried.z;
      node.vx = node.vy = node.vz = 0;
    }
    if (event.data.preserve && nodes.every(node => previous.has(node.id))) simulation.alpha(0);
  } else if (event.data.type === "step" && simulation && knowledge3dSimulationNeedsTick(simulation)) simulation.tick(1);
  if (!simulation) return;
  const positions = new Float32Array(simulation.nodes().length * 6);
  simulation.nodes().forEach((node, i) => positions.set([
    node.x || 0, node.y || 0, node.z || 0, node.vx || 0, node.vy || 0, node.vz || 0,
  ], i * 6));
  self.postMessage({positions, alpha: knowledge3dSimulationNeedsTick(simulation) ? Math.max(0.007, simulation.alpha()) : 0}, {transfer: [positions.buffer]});
};
