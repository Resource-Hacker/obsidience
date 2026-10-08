# Provider graph views

These are presentation adapters, composed with the existing Harness lifespan and
activity stream. They introduce no graph store, agent, Tool grant or scheduler.
Saved-code refreshes update only the existing provider's derived index; memory
and source content remain read-only here.
Samsung's equal thirds hold Hindsight, Library and Code. Computer retains its
orbiting subagents on USB-C. The shared Quickshell/QtWebEngine stage owns each
renderer and graph state. Viewer panes receive its video and metadata over
same-machine WebRTC, signaled through the existing bounded Shell channel. They
contain no graph renderer or simulation. An individual Knowledge selection
uses an isolated camera pass on the actual stage cloud through its existing
renderer, so other orbiting graphs cannot overlap the viewer. Only open viewers
acquire transfer buffers and streams; the final disconnect releases them.
Hindsight's third stacks all configured Agent banks with Knowledge's existing
neon role icons on the left and no captions or date ruler below. One Memory
presentation-channel owner selects among those existing canvases for the viewer;
bank selection never removes another desktop row or starts a viewer simulation.
The transfer canvas copies only the selected bank's rendered frames while a
viewer is connected. Per-bank workers and activity subscriptions pause when
neither the desktop nor a viewer needs that bank.

Knowledge, Memory and Code share one native Graph pane, not three windows.
Header buttons switch the active subscriber through the existing Shell selection
channel without a pane-present or focus action. Memory's dedicated Agent dropdown
selects its configured Hindsight bank; Knowledge retains its own graph selector.
The Graph pane keeps the old `knowledge-graph` placement identity and geometry.
Legacy Memory/Code presentation requests target this same pane. The Knowledge
browser and Reader are distinct content panes and are not consolidated.
The three views share their controls, background and details.
Their actual graph labels also reuse `knowledge-3d-labels.ts`: the same font,
colored plate, dashed leader and overlap placement. Provider labels are bounded
to twelve and update on camera/data/emphasis changes, not an idle animation loop.
Hovered, selected and exact activity records take priority over close-up context.
The Knowledge selector changes only the viewed graph; Computer's subagents keep
orbiting on the desktop. Library is independent, never an Agent. Reader stays a
distinct content pane. Provider settings and camera controls go back to the
stage; closing a viewer does not close or reconstruct the stage graph.

- Memory uses the configured Hindsight 0.10.0 API: native per-bank `/graph` and
  exact `/memories/{id}` reads. Its force layout uses the already pinned
  `d3-force-3d` dependency. Categories are filters, never wiki placement. The complete native relationship
  graph and exact observation-support edges are retained. Stage surfaces show
  only the graphs; controls, backgrounds and detail panels belong to the viewers.
- Code uses codebase-memory-mcp 0.10.8's native `/api/layout` for node identities,
  types and edges. The shared stage presents those records with Knowledge's
  spherical radial/collision solver in one worker; upstream coordinates do not
  dictate the display. Native containment groups branches, while calls/imports
  remain cross-links. Layout-only path/project fallbacks never create provider
  relationships. Its cache remains outside Vault and Source.
  Run the installed MCP provider with its local UI enabled; do not launch a
  second competing MCP owner. The default endpoint is `http://127.0.0.1:9749`.
  Optional local `[graphs]` keys `codebase_url` and `codebase_project` select an
  existing provider and indexed project. The default project identity is the
  repository's absolute path with `/` replaced by `-`, without the leading `-`.
  The Code view reports unavailable when that optional provider is absent.
  Its complete HTTP read and JSON response run in FastAPI's existing worker
  pool: the native provider has a one-second response-send deadline, so sharing
  the conversational event loop could truncate a multi-megabyte graph. One
  lifespan-owned HTTP client closes with the adapter. Stable qualified names
  map to compact display IDs; native identities and positions remain intact.

Code's file lens uses the same renderer, assets, labels and spherical solver.
With Follow enabled, a saved-file event zooms toward its existing project node,
then unfolds that file into a local sphere while the project fades. Clicking a
file (or choosing a symbol from project search) enters the lens manually even
with Follow off. Every indexed member stays available; up to sixteen direct
external call/import/usage/inheritance neighbors add bounded context, marked
with an outward arrow. Native edges remain native edges; layout ancestry is
private placement data, never an assertion of a call or relationship.
Right-click on the desktop Code stage or viewer, Back and Fit return to the
saved project camera and positions. Right mouse is reserved for Back in Code,
not OrbitControls panning. A native Module wrapper named by the same exact file
path shares the central File orb in the file lens; its identities remain aliases
for activity/selection and its native connections are projected onto that orb.
Only resulting self/duplicate display links are omitted. Actual functions and
classes remain separate, and the full provider snapshot is unchanged.
Ordinary saved
updates do not take over an already-inspected file camera. Body-only changes
highlight without rebuilding physics; additions settle around pinned existing
members and removals fade rose. Green marks new symbols and amber marks changed
saved source spans. One bounded outgoing geometry layer owns the cross-fade and
releases its textures/materials afterward, including interrupted transitions.

The existing file-event listener notifies the lifespan-owned `CodeRefresh`
adapter. Save bursts coalesce for 750 ms into a single-flight native
`index_repository` request through the installed CLI and existing coordination
daemon; the native provider owns its incremental parse and index writes.
Saves arriving during that request require one latest pass before publishing a
refresh event. No model is invoked, no index artifact is written into the repo,
and there is no periodic refresh loop. Provider absence or a failed refresh is
shown as stale, not ready. Refresh explicitly requests that same native path.
The API projects native source ranges and bounded, in-root SHA-256 source-span
fingerprints, never source contents. This describes saved files, not unsaved
editor buffers or an execution trace; parser/dynamic-call limitations remain.

Memory timestamps belong to Hindsight. The operational timeline uses native
`mentioned_at`: when the original conversation recorded the memory. Explicit
`occurred_start` / `occurred_end` dates describe the event discussed and remain
available in record details; an old publication cited today must not move today
into that publication year. Import and consolidation time never substitute for
conversation time. Unknown conversation dates remain undated. Native temporal
relationships and underlying occurrence dates are unchanged.

The default view requests the complete bank, sized from the native statistics.
A fixed newest-first `/graph` page would silently drop older days as the bank
grows. Explicit bounded queries still report incomplete coverage. Decode and
serialize large graph responses in the adapter worker pool. The recorded native
Hindsight patch likewise moves detached-row graph projection and schema encoding
off its request loop, preserving its SQL, schemas and relationships. Do not
spread memories across invented dates or conceal missing source history.

The Memory stage spaces records by activity in chronological order. Equal memory
volume gets equal length along the tube: busy periods expand, and quiet date gaps
do not leave empty stretches. Records with the same timestamp share that period's
length, using stable IDs solely to break layout ties. Original dates are unchanged;
the viewer identifies activity spacing and retains native dates in record details
and date-range controls. The desktop deliberately omits ruler text and captions.
The other two coordinates settle through the existing d3 engine, with gentle
transverse gravity keeping the tube coherent. Native semantic,
causal and support links attract more strongly than broad shared-entity links;
degree normalization prevents a densely connected entity from dominating.
Temporal proximity is already represented by the time axis and supplies no
additional spring. The overview renders each record's two strongest native ties;
hover or selection reveals every incident link with visible endpoints. Counts and
details retain the full native graph. Memory dots scale with camera distance so
a full-bank overview does not stack thousands of fixed-size halos into bright
walls. Dates, edge identities and provider weights remain unchanged.

Filters retain the complete snapshot's activity scale. Unknown dates occupy a
separate undated position. Historical intake fills the tube through
ordinary graph updates, with all native records and relationships retained. Equivalent
snapshot refreshes preserve force positions, velocities and cooling. The layout
adds no inference, category assignment or memory-store mutation.

`codex.py` observes new public tool call/result records in local Codex session
journals and Claude Code project journals (including subagent journals) through
watchdog; labels name the observed agent. It supports the installed MCP's grouped JSON and
explicit tree result tables. No historical journal is replayed on startup; only
fixed operation labels and exact returned qualified identities are published.
Calls outside the selected project are ignored. The listener never copies
reasoning, conversation, raw tool arguments, source contents or command output,
and cannot invoke tools or alter Codex configuration. Repository inotify events
highlight exact files as “File changed,” without asserting who edited them,
and notify the separate derived-index refresh adapter.

The journal schema is a local optional adapter, not a promise of a stable Codex
hook API. Unsupported output formats produce activity without guessed symbols.
Calls interrupted without a result settle at the native task boundary or adapter
shutdown. The provider retains index coverage limitations; Qt/QML callbacks and
other dynamic edges may be absent. Refresh the existing index when source changes
require it; opening or animating a view never launches indexing or a model.

The UI consumes the existing `/ws/activity` operations with exact
`memory:<bank>` or `code:<project>` scope. Search results glow green, reads cyan,
changes amber and consolidation violet. Selection reveals actual neighbors;
neighbor edges are not asserted to be agent traversal. Camera following can be
disabled independently. Background Memory intake keeps the complete timeline
framed as it grows; intentional reads, searches and selections can follow their
exact references. Fades use original event times and do not replay stale
activity on reconnect. Snapshot refreshes are event-driven and coalesced.
