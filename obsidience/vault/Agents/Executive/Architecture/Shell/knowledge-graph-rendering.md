---
type: knowledge
title: Knowledge graph rendering
sources:
- resource: obsidience/ui/src/renderer/src/components/themes/obsidience/knowledge-3d.ts
- resource: obsidience/ui/src/renderer/src/components/themes/obsidience/knowledge-3d-cloud.ts
- resource: obsidience/ui/src/renderer/src/components/themes/obsidience/knowledge-3d-scene.tsx
- resource: obsidience/ui/src/renderer/src/panes/graph-backdrop.tsx
- resource: obsidience/harness/interfaces/api/app.py
obsidience:
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
  approved_at: '2026-09-10T23:49:22.333585+00:00'
---

The knowledge graph is a presentation of accepted Articles and relationships,
not another knowledge store or execution engine. The Harness graph/navigation
API supplies exact identities, titles and parentage. Folder condensations are
represented once as their branch Article. Source files do not become graph
nodes merely because they exist on disk.

## One renderer and one layout

`knowledge-3d-scene.tsx` owns the Three.js scene, camera and graph-instance
lifecycle. `knowledge-3d-cloud.ts` implements `createKnowledge3dCloud()` for the
executive, Library and satellites. Each instance has its own data and force
state but calls the same geometry and layout in `knowledge-3d.ts`. Satellite
orbit, self-spin and scale are presentation transforms, not different physics.
The separate 2D layout remains independent.

The Brain is pinned at the local origin. Physical depth follows exact
placement-parent ancestry; equal-depth nodes share one concentric spherical
layer. One coupled constraint stage resolves angular avoidance, outward
parent-child edges and recursive moving crown territories on those layers.
Capacity can expand an affected whole layer, never give a crowded node its own
private depth radius. Brain-level angular relaxation continues after spring
cooling and can escape a planar arrangement; nested crowns retain elastic
settling. All of this runs inside the existing scene-owned D3 tick.

Cooling alone is not success. Settling checks geometry and motion; bounded
unresolved cases report `needs-capacity` or `stalled`. A sparse or unbalanced
tree need not fill every viewing direction equally. Front/back projection
occlusion is not necessarily a world-space collision.

## Refresh and activity

Physical topology, parentage, sizes or spacing can resettle the affected graph.
Paint, labels and approval-only refreshes preserve compatible positions,
velocities, cooling and solver state. Accepted activation references drive
thinking paths. Valid pending relation proposals may preview their physical
link, but cannot alter accepted Task authority or the packet's Knowledge.

See [Native shell and surfaces](/Agents/Executive/Architecture/Shell/native-shell-and-surfaces.md) for the actual
WebKit host and [Activation packet protocol](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md)
for the model-facing activity source.
