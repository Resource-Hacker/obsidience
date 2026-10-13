---
type: knowledge
title: Knowledge graph rendering
sources:
- resource: obsidience/harness/knowledge/scope.py
- resource: obsidience/harness/knowledge/index.py
- resource: obsidience/ui/src/renderer/src/components/themes/obsidience/knowledge-3d.ts
- resource: obsidience/ui/src/renderer/src/components/themes/obsidience/knowledge-3d-cloud.ts
- resource: obsidience/ui/src/renderer/src/components/themes/obsidience/knowledge-3d-shell.ts
- resource: obsidience/ui/src/renderer/src/components/themes/obsidience/knowledge-3d-scene.tsx
- resource: obsidience/ui/src/renderer/src/panes/graph-backdrop.tsx
- resource: obsidience/harness/interfaces/api/app.py
- resource: obsidience/harness/execution/activity.py
- resource: obsidience/ui/src/renderer/src/panes/graph-activity.ts
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

The Executive's subagents keep their satellite orbits on its desktop stage.
Library is an independent Knowledge graph on its own stage, never an Agent.
The Knowledge viewer selects Executive, Library or one subagent without
changing desktop membership. Viewers receive frames and metadata from the
stage; they create no graph or simulation. An individual Knowledge view uses
an isolated camera pass through the stage's existing renderer and actual cloud.
Its transfer buffer and stream exist only while a viewer consumes them.

The Brain is pinned at the origin. All first-level branches start on one
common inner radius. Only the remaining distance is divided by each branch's
depth. With inner radius r, outer radius R, branch depth D and node depth d,
the node uses r + (R-r)*(d-1)/(D-1). A childless first-level Article stays at r.
Intermediate Articles share their actual layer with continuing subnodes;
the deepest descendant layers terminate at the common outer radius.

The radius is automatic. Population, glyph clearance and the requirements of
each branch layer determine the whole sphere's size. Parent-child clearance
supplies a lower bound. On the final ordinary cooling tick, remaining node
contact pressure expands the sphere by the smallest common factor required by
the settled bearings. Pure Article additions retain the previous required
radius and grow as needed; removals, smaller glyphs or reduced clearance can
reclaim space. Branch clearance is the sole Layout slider: it scales padding
around nodes and branches, and the automatic radius follows. Its default 1
preserves the accepted spacing. There is no Graph radius slider or saved
physical-size override. Old radius and Link distance values are ignored by the
3D layout. Glyph sizes, beam widths
and camera scale remain independent of this growth. Saved presentation scale
preserves each graph's visual identity. Camera rotation and role nameplates
belong only to the main graph.

One shared recursive branch rule builds subtree membership and a footprint
profile for each radial layer. A branch inherits its continuing children's
demand; a large inner node stops reserving space beyond its own layer. Sibling
charge and moving boundaries divide the available arc by that layer's inherited
width. Outer Articles use spherical force relaxation: continuous repulsion also
acts beyond contact, with range and strength derived from radius and population.
The radial constraint keeps motion along the sphere and the branch pass keeps it
inside the proper branch. This reduces crowded patches and gaps without fixed
angular targets or a second solver.
Springs, collisions and the final radial constraint use the existing d3-force-3d
cooling schedule. The final contact fit adds no settling pass, idle audit, fixed
bearings, named-branch cases or separate solver clock. Compatible refreshes
retain the fitted radius along with positions, velocities and cooling.
A rotating 3D projection can still put distinct branches in front of each other.

## Layered glass

`knowledge-3d-shell.ts` draws each ball's layout layers as glass shells.
Layers closer than a small tolerance share a shell, at most four per ball. A
shell is a sheen of fine drifting level lines and depth-of-field dust, added
as light behind the node sprites. It creates no force nodes, picking targets
or activity routes, and it follows the solver's positions without changing
them.

Each node presses a crater into its own layer's shell. The node's size and
its number of links set the crater's depth and width, and the crater always
clears the node's icon. A crater holds a seed, an orb of slowly turning dust
in the node's branch color, over a colored glow from the crater floor. The
shell nearest the core is the most solid and the outermost the clearest. The
Glass group in Graph settings sets inner and outer solidity, crater depth,
crater glow, seed glow, sheen lines and dust for each graph.

At rest a pale survey plane crosses every ball from bottom to top and lights
the glass it passes. While a ball's Agent is thinking, every node on the
route drops into its own shell like a stone into water as the thinking front
reaches it, inner layers included: a ripple in the node's color spreads
across that layer, and the glass, its dust and its seeds ride it. The
Articles a route ends on send the strongest ripple, and reached nodes keep
sending softer ones in turn until the thinking ends. A ripple marks the
front's passage, as the route beam does; only the seed of a consulted or
hovered node swells and burns amber. Ripples start only at nodes on the
actual route. Labels are captions in light
capitals inside a thin box in the branch color, with a leader to their node,
drawn last, over the glass. A consulted node also wears a faint disc and a
breathing ring in its branch color.

## Scoped graphs and Library

The four separate Agent clouds remain independently populated and retain their
own state, historical memory and visual identity. Their shared Knowledge checkouts
resolve to canonical Articles in the complete owner Library. The manifest's
access scope drives search/read behavior as well as displayed membership.
Navigation proxies do not grant access to siblings. The Reader's shared Agent
icon controls change exact checkout or Task assignment; no duplicate assignment
controller remains in the native Library catalog.

## Refresh and activity

Physical topology, parentage, radius or individual glyph sizes can resettle
the affected graph.
Paint, labels and approval-only refreshes preserve compatible positions,
velocities, cooling and solver state. Accepted activation references drive
thinking paths, with exact instruction/passage provenance in Action Trace.
The same bounded activity stream also carries actual Tool dispatch/results,
intentional owner Reader loads, committed edits/checkouts, and pending or decided
Article Reviews. Successful reads and searches light their exact returned refs;
listing shows returned titles without claiming their bodies were read. Routine
API reads, status polling and graph refreshes emit no browsing activity.

The existing branch comets retain the packet palette. Cool cyan breathing halos
mark reads/searches, faster violet pulses mark Tool calls, amber marks changes
awaiting Review, green outward pulses mark committed edits/approvals, and red
flashes mark rejection, failure or interruption. A returned Tool result does not
assert that the requested real-world outcome succeeded. A compact activity label
states the operation and outcome. Tool/Skill packet glow still means instructions
were supplied; an operation halo identifies an actual call.

Concurrent operations keep independent identities and exact ref groups. Each
cloud uses the same existing sweep and shader clock. Cross-links may animate only
when both endpoints occur in the same supplied group; hierarchy ancestors carry
route beams without becoming consulted Articles. The Executive packet stays lit
through speech, including its measured voice envelope. Called Tools and their
returned refs remain lit for that run and its queued/playing reply, retaining
their real outcome labels. The conversation owner publishes graph completion
after reply commitment and speech handoff. Playback completion starts a 420 ms
eased fade of the beams and node glow; text-only completion uses the same fade.
Independent edit/Review notices retain their finite six-second display window.
Reconnect restores only current operation state; transport loss clears
unverified running visuals. No additional model call, polling loop, layout
solver or execution authority is introduced.

Selection has its own presentation lifetime. A click or intentional native
Reader selection starts a 340 ms eased sweep immediately, without waiting for
the Article HTTP response or using the thinking-speed slider. The preceding
selection retracts from its current progress while the new route extends;
rapid changes preserve each in-flight position. Selection shares the existing
beam geometry and Scene clock, stays on its exact target, and retracts when
cleared. A late Reader response cannot resurrect a superseded selection.
Selection indicates browsing intent; the read result still attests body access.
Hover remains a separate preview. New Tool calls extend an agent's existing
thinking sweep without restarting already illuminated Tools.

New relationships remain proposed until ordinary Review accepts them. Valid
pending relation proposals retain their existing physical preview and approval
continuity without changing accepted Task authority or packet Knowledge.

See [Native shell and surfaces](/Architecture/Shell/native-shell-and-surfaces.md) for the actual
QtWebEngine host and [Activation packet protocol](/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md)
for the model-facing activity source.
