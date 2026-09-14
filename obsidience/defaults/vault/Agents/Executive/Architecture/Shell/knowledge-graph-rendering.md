---
type: knowledge
title: Knowledge graph rendering
sources:
- resource: obsidience/harness/knowledge/scope.py
- resource: obsidience/harness/knowledge/index.py
- resource: obsidience/ui/src/renderer/src/components/themes/obsidience/knowledge-3d.ts
- resource: obsidience/ui/src/renderer/src/components/themes/obsidience/knowledge-3d-cloud.ts
- resource: obsidience/ui/src/renderer/src/components/themes/obsidience/knowledge-3d-scene.tsx
- resource: obsidience/ui/src/renderer/src/panes/graph-backdrop.tsx
- resource: obsidience/harness/interfaces/api/app.py
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

## Scoped graphs and Library

The four separate Agent clouds remain independently populated and retain their
own state, Observations and visual identity. Their shared Knowledge checkouts
resolve to canonical Articles in the complete owner Library. The manifest's
access scope drives search/read behavior as well as displayed membership.
Navigation proxies do not grant access to siblings. The Reader's shared Agent
icon controls change exact checkout or Task assignment; no duplicate assignment
controller remains in the native Library catalog.

## Refresh and activity

Physical topology, parentage, sizes or spacing can resettle the affected graph.
Paint, labels and approval-only refreshes preserve compatible positions,
velocities, cooling and solver state. Accepted activation references drive
thinking paths, with exact instruction/passage provenance in Action Trace.
Successful Article reads/searches add the refs actually returned to that Agent.
These events reveal observable context use and execution, not hidden model
reasoning. New relationships remain proposed until ordinary review accepts them.
Checkout and graph-refresh events are passive, never synthetic thinking. Valid
pending relation proposals may preview their physical link but cannot alter
accepted Task authority or the packet's Knowledge.

See [Native shell and surfaces](/Agents/Executive/Architecture/Shell/native-shell-and-surfaces.md) for the actual
WebKit host and [Activation packet protocol](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md)
for the model-facing activity source.
