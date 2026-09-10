# Obsidience design

Obsidience is a standalone, graph-native agent harness built first for small
local models on consumer hardware. Its central premise is simple:

> The knowledge graph is the harness, and each activation should give the model
> the smallest complete packet needed to succeed.

The durable brain instantiates [Andrej Karpathy's LLM-wiki
pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
immutable raw sources, an agent-maintained Markdown wiki, and its schema are
ordinary files. The
runtime combines its recursive article summaries, typed graph relations,
fast hybrid retrieval, and bounded graph expansion into an activation packet.
The model does not need to memorize the harness, rediscover its Tool interfaces,
or infer procedures from a giant system prompt.

## Design laws

1. **One graph is authoritative.** The vault defines knowledge, work,
   procedure, Tool authority, tool guidance, and agent identity. UI trees, menus,
   schedules, and prompts are projections of that graph. The graph API's
   navigation manifest resolves Agent card names and generated subject Articles
   once; every UI consumes those exact IDs, titles, parents, and roles rather
   than reconstructing labels from paths.
2. **Every graph node is an Article.** A parent Article is the readable index
   and condensation of its descendants. A leaf is the complete local article.
   `index`, `folder`, and `domain` are therefore presentation roles, not kinds.
   Generated index titles are human-facing and begin uppercase; terminal
   executable identifiers such as `vault.read` retain their exact spelling.
3. **Edges dispatch; retrieval informs.** Fast retrieval may nominate a Task
   candidate, but the harness must select one exact accepted Task Article.
   That Task's typed links select Runbooks, Skills, Tools, assignees, and
   hierarchy. Similarity never grants executable authority.
4. **Definitions and execution are separate.** Articles define reusable
   objects. Schedules, event occurrences, attempts, status, traces, and results
   live in runtime state and the bounded execution ledger.
5. **Shallow is the default.** Prefer one meaningful level below a family.
   Add depth only when every child is independently useful and explainable.
6. **No fictional Tool.** A Tool exists only when the harness has one real
   `capability:<exact Tool title>` binding and one matching Source-linked
   entrypoint. Documentation, a package name, or remembered behavior is not a
   Capability and cannot make a Tool executable.
7. **Optimize for small models.** Prefer explicit contracts, narrow choices,
   stable names, short articles, closed tool sets, and deterministic validation
   over prompt cleverness or hidden convention.
8. **Disk paths are literal.** The wiki and raw sources are the durable files;
   indexes, graph DTOs, embeddings, and UI trees are disposable derivations.
   A Source path shown in the UI is the exact project-relative path opened by
   the Reader, never a copied file or synthetic alias.

## Canonical Article types

Accepted frontmatter uses exactly six semantic types through Open Knowledge
Format v0.2 and the Obsidience profile. The six meanings do not change.

| Type | Meaning |
| --- | --- |
| `knowledge` | Facts, constraints, context, explanations, indexes, domains, and observations |
| `task` | A reusable outcome with inputs and acceptance conditions |
| `runbook` | The ordered or branching process for completing a Task |
| `tool` | One executable interface with declared arguments, effects, and failures |
| `skill` | Exact practical instructions for using one Tool correctly |
| `agent` | An accountable executor with a role, assigned Tasks, Knowledge, and Observations |

One physical Markdown Article carries the native OKF document, not an export
copy. `type` is required; optional common fields such as `title`, `description`,
`resource`, `sources`, `generated`, and `verified` retain their upstream shapes.
Application-specific fields such as `runbook`, `tool`, `skills`, `assignee`,
`triggers`, and `auto_curate` live under `obsidience`. The shared codec adapts
this to internal DTOs; `kind` is only an internal alias. Unknown imported fields
round-trip without acquiring trust. Local admission still enforces six types,
exact accepted bindings, review, and Source-backed executable contracts.

Root `status` is document lifecycle (`draft`, `stable`, `deprecated`). The
existing SQLite ledger alone stores Task operational status, pending inputs,
event FIFO, last execution and result. Updating execution state does not alter
the Article or invalidate retrieval embeddings. Runtime state is projected
fresh into task views rather than written into reusable definitions.

Execution success and diagnostic findings are separate. Check completes when
it obtains and reports a valid health snapshot, including a degraded finding;
an unavailable or invalid inspection fails. The health Tool and Task API share
the execution ledger's current-issue projection: unresolved event commitments
or waiting queues, blocked configuration, and scheduled drafts. A terminal
failed attempt with no outstanding work remains history rather than a current
fault. Prior failed runs and their findings are never rewritten to make health
appear recovered.

A completed degraded Check activates Heimdall's ordinary Repair Task through
`harness.degraded`. The controller persists the actual status finding in the
Check trace and records its handoff in the existing ledger; model prose cannot
activate recovery. Repair reads current status and uses only the paired
`harness.repair` interface. It may requeue one exact failed occurrence only when
complete durable dispatch receipts rule out effects, pending Review and
continuations. One controller receipt commits atomically with the existing
pending-state transition and limits automatic retry to once per original
Task/event/activation key. A new run ID never resets that limit. Unsupported
faults remain explicit blockers. Repair cannot retry itself, edit Source, alter
models, or approve changes. Each attempted recovery consumes its inspection;
completion requires a fresh status read and either no remaining eligible
operation or the completed eight-attempt pass budget. Eligible entries precede
blocked entries in the bounded plan so unsupported faults cannot hide work.
The pass counts existing controller Tool trace entries, without another store.
Remaining eligible work is explicitly deferred to a later pass.
A completed Repair pass reports its disposition, including unresolved blockers
or a queued outcome that has not yet executed. It does not assert universal
health or replace independent acceptance of consequential changes.

Runbook refinement preserves the researcher/verifier split. Darwin's existing
Generate / Runbook Task may revise the body of one accepted leaf procedure from
an explicitly registered regression case. Its title, applicability, Skills,
Tools and Task model settings remain frozen. The existing `vault.propose`
boundary stages the candidate, and `runbook.proposed` activates Heimdall Audit
through its ordinary durable FIFO. This is a handoff between sibling outcomes,
not a new Task family or a Repair operation.

Heimdall's `harness.evaluate` uses the ordinary activation packet builder and
executor with a private frozen Tool boundary. Every trial action, including
completion, stays inside its fixed fixtures; there is no fallback to live Tool
dispatch, ordinary trial receipt, Task state mutation or knowledge writeback.
The target Task's model and reasoning settings, existing model lease, context
accounting and foreground/STOP cancellation remain authoritative. Trial trace
rows carry a bounded case, variant and repetition identity within the one Audit
execution. The popup labels simulations and correlates their own actions and
measurements without combining them with the outer Audit response. This evaluates a procedure against
reconstructed inputs, not exact historical execution or live workstation effects.

Developer-authored fixtures include independent grading criteria and held-out
cases. Darwin receives training cases only. Internal evaluation artifacts live
as immutable, content-addressed Source files under `evidence/evaluations/`;
they are derived execution evidence, not external intake and do not emit
`source.added`. The existing execution ledger attests handoff and actual Audit
Tool receipts. There is no second scheduler, database, provider or graph.
Both sides must cover every frozen case/repetition. Acceptance requires every
candidate case to pass, no regression, and a strict training improvement.
Missing observations and execution errors remain incomplete. Total trial time,
Tool count and prompt-token measurements are reported separately; time includes
model admission and is not TTFT or a statistically established speed improvement.

Review rechecks the exact complete proposal hash, accepted dependency selection
and bytes, model profile, evaluator revision, full suite coverage, and a completed
independent Audit with its exact returned Tool receipt. A model-authored verdict
or a changed candidate cannot satisfy that gate. Ordinary approval still owns
publication; successful evaluation never promotes a Runbook automatically.
Review listing reuses its one accepted-Article snapshot while holding the existing
Article lock; it does not rescan the entire Vault for every candidate. Actual
approval independently revalidates current state. No stale acceptance cache exists.
Check continues diagnosis and Repair continues receipt-safe recovery. Refining
implementation code or expanding Tool authority remains developer work.

Register a bounded case with `python -m obsidience.scripts.runbook_evaluation
prepare <fixture.json> --origin-run <exact-run-id>` from the project root, then
`python -m obsidience.scripts.runbook_evaluation start <case-id>` to admit the
existing Generate Task. The first fixture reconstructs the historical Check
error where a valid degraded inspection was marked failed; it does not assume
that the current accepted procedure still has that defect. These patterns refer
to pinned AutoSaddler v2 in `artifacts.lock.json`; no upstream engine or code was
imported.

Bodies use standard Markdown links, including relative and bundle-root paths;
one CommonMark parser supplies graph edges and review locations. Code examples,
images, and external URLs are not Article edges. Parent Articles use the
ordinary same-named `Folder/Folder.md` path, preserving every index node as an
Article without abusing OKF's reserved `index.md` and `log.md` documents.

OKF is the portable document base, not another executor. Darwin's existing
`web.fetch` uses maintained HTML-to-Markdown extraction to preserve document
structure and outgoing URLs in Source. Linked pages are not fetched implicitly.
Obsidience still owns research, Inbox handoff, ingestion, review and publication;
neither the ADK reference agent nor its trust ordering controls this harness.

Knowledge is the descriptive default. A domain such as Games or a subject such
as Architecture is a Knowledge Article. It becomes an index by having children;
it does not become a separate Domain or Index object.

Source is intentionally outside this kind list:

- **Source** is one typed, read-only view over the real Obsidience project tree:
  `obsidience/vault/` contains wiki Markdown; `obsidience/evidence/` contains
  immutable raw material; `obsidience/harness/`, `obsidience/ui/`,
  `obsidience/scripts/`, and `obsidience/tests/` contain application code; and
  `obsidience/state/system/` is the physical System inventory. Its real folders
  are `hardware/{compute,drives,devices,network}` and `applications/`;
  every descriptor remains an exact readable file. Source follows those
  folders: `SYSTEM` owns peer `HARDWARE` and `APPLICATIONS` branches, while
  Drives stays inside Hardware and describes its actual storage locations.
  Project files and wiki Markdown retain their physical roots. Private
  `@view/` keys stabilize UI identity but cannot invent a
  branch or replace a leaf's exact path. These folders are not Article kinds.
  Live sensor values stay on the Hardware API.
  Source supports Articles but is not a second knowledge graph or mutation
  authority.
- The Source explorer exposes four physical roots: **System**, **Knowledge
  Markdown** (`obsidience/vault/`), **Evidence** (`obsidience/evidence/`), and
  **Project Files**. Knowledge Markdown exposes the actual graph Article
  folders. Evidence starts collapsed: `incoming/` is the manual text import
  dropfolder, `raw/` contains immutable captured references, `inbox/` contains
  Darwin's cited handoffs to Alexandria, and `system/` holds immutable System
  captures. Every file retains its exact Reader path. Raw is evidence storage;
  it is not the location of the graph's compiled Markdown Articles.
- The Harness records stable, observed System facts in immutable, deduplicated
  Source versions under `evidence/system/`. One shared catalog derives both
  Source labels and ordinary Knowledge Articles from the actual System
  descriptors and folder hierarchy. It absorbs `system.json` into **ADMECH
  Workstation** and each `application.json` into its application hub. The
  generated branches are **Hardware** and **Applications**. **Drives** contains
  physical drive Articles directly, selected by serial/model and attested WWN
  from util-linux's read-only block inventory. Partitions and mount points are
  details within each Article; configured application directories belong to
  Obsidience's application Article. A standalone application descriptor is a
  direct leaf; only applications with meaningful subsubjects need a folder.
  Host network
  interfaces belong under
  the single **Hardware / Network** Article; third-party Connection configuration remains in
  Settings. Existing authored workstation contracts and history belong under
  the separate **Workstation Observations** branch as direct Article children,
  with accepted links repaired through the ordinary Vault move owner. This
  branch has no repeated hardware, application, or incident hierarchy: native
  Article links express subject associations. Redundant folder condensations
  are archived while substantive observation content and provenance are retained.
  Publication runs on Harness startup and explicit **Refresh System**. It
  does not call a model, enqueue a Task, or create a Review. The existing
  Source ledger owns evidence attestation and `source://` identity; these
  controller captures do not emit general research intake events.
  Generated Articles cite their exact evidence version and observation time.
  Unchanged facts preserve Article bytes and graph state. An unavailable
  collector retains the last successful Article and reports degraded coverage;
  it never turns a failed read into a claim that hardware disappeared.
  Schema-derived publication destinations and controller receipts protect
  generated content through Reader, proposal, Review, move and maintenance
  paths. The ADMECH namespace outside Workstation Observations is reserved for
  this deterministic mirror; authored Articles cannot create competing branches.
  Arbitrary imported `generated` metadata cannot claim that ownership.
- Obsidience is an ordinary directory on `/home`; `/var/lib/ai` is the Models
  storage location. `/home` and `/var/lib/ai` are separate Btrfs subvolume
  mounts on one shared filesystem and therefore share free space. There is no
  dedicated Obsidience partition or quota.
- A newly created immutable raw Source emits one `source.added` event after its
  bytes and ledger identity are durable. The event is one trigger on Darwin's
  Learn Task for general intake or Distill for Feed items. Darwin writes one cited handoff through
  `source.handoff` into the physical `obsidience/evidence/inbox/`; that durable
  transition emits `source.inbox` for Alexandria's centralized Ingest Task. Duplicate
  capture or handoff emits nothing. Source never becomes accepted Knowledge or
  an intermediate Review object.

### Source intake and News & Research

Source's explicit `evidence/incoming/` folder accepts finished UTF-8 text
files via upstream watchdog's Linux closed-write and atomic-move events.
The same immutable Source ledger owns capture, deduplication and replay;
startup reconciliation covers files delivered while the harness was offline.
This is not a watch over the entire Source explorer or system. Partial,
hidden, binary, symlinked and oversized files are excluded, and original
files remain present. Existing Research acquisitions carry their controller
Task/run identity so supporting captures do not trigger redundant research.

Connections provide access; Feeds select provider items and collection policy.
New Feed items enter immutable Source and activate Darwin's existing Distill
Task. Its cited handoff activates Alexandria's existing Ingest Task. There is
no separate News Task, hourly briefing job, fixed ten-story compiler or
News-specific Tool mode. `News & Research/Top Stories` is an ordinary Knowledge
destination selectable in Feed settings. The former Top 10 edition is archived;
new or changed items from the BBC Top Stories Feed route to Top Stories.
Historical Feed publications remain at their captured paths and count toward
normal Feed retention across destinations. Sources, Articles and historical
execution receipts retain their identities and native OKF freshness fields.

Acquisition and contextual examination use the existing Tool boundaries.
`web.fetch` applies pinned Trafilatura 2.2.0 to already acquired article HTML,
retaining available bylines, dates and safe outgoing references; generic or
sparse pages keep Markdownify. HTTPX still owns public-address, redirect and
size validation, and the Source authority captures the immutable extraction.
Up to ten URLs share four joined workers and one ordered JSON result capped at
60,000 serialized characters. `source.read`, `vault.search` and `vault.read`
also accept bounded batches through their existing paired Skills. Each item
retains its own success or failure, identity, hash and recoverable page range.
The existing TaskContext projects eligible older pages independently without
discarding failures, the current observation or effect receipts.

Darwin owns research and summary accuracy. Alexandria reads the complete bound
Inbox and handles ingestion and useful contextual relationships without
repeating Darwin's research or rewriting his summaries. Feed Ingest compiles
that immutable summary into the owner-selected destination and applies the
Feed's active-Article limit through the same atomic publication and archival
Review path. Other research handoffs use Ingest's general procedure.

The existing Scheduler admits only currently available configured execution
capacity, counting direct-owner claims and externally running Task identities.
It does not preclaim unstarted periodic Tasks into a semaphore or model-lease
backlog. Ready Source Inbox heads precede other bound events, which precede
unstarted periodic work. This lets completed research reach Ingest before
waiting maintenance starts. Each class remains chronological and each Task keeps
its own FIFO; a newly ready handoff never preempts an active Task.
Deferred cron retains its original due time; sustained event delivery can defer
periodic maintenance. Active continuations and foreground/resource checks remain
authoritative. These are admission rules over existing Tasks, not new work objects
or a second queue.

Auto-curate is the owner-authored `auto_curate` boolean on an actual Article.
The nearest explicit selection wins, including a child's false override. An
Agent Brain scopes its own Knowledge folder; shared Library definitions
never inherit that permission. The checkbox changes permission, not Task
triggers. The Reader, graph rings, ordinary Knowledge publication, Immediate
disk projection and Temporary append all consult the same policy resolver.

The author may maintain its own permitted Knowledge; Alexandria may maintain an
owner-enabled destination through the existing proposal validator and review
ledger. Auto-curate does not change Agent identity, Tool/Skill/Task/Runbook
authority, generally archive Articles, resolve conflicts, or turn inference into truth.
Feed publication independently attests the captured item, Distill execution,
Inbox and selected destination. Its explicit retention policy may retain
excess Feed-owned Articles as deprecated archives only after validating their
provenance, current policy, exact revisions and surviving inbound references.
It cannot archive unrelated Knowledge or immutable Source. Proposed metadata,
Source prose and model output cannot grant permission. Broken links, stale
bases, unsupported evidence and disabled scopes remain reviewable. Dotted node
rings show the backend's effective selection, never a second client-side policy.

Capability and Module are also intentionally outside the Article-kind list:

- **Capability** is executable machinery behind a Tool interface. Each accepted
  leaf Tool binds one thin entrypoint at
  `obsidience/harness/capabilities/<dotted Tool segments>/<leaf>.py`; its code
  and provenance live in Source. It is not checked out or selected by a Task;
  the Tool and paired Skill are the graph-facing authorization and guidance.
- **Module** is a top-level Obsidience product component with a physical folder
  and bounded contract: Harness, Shell, UI, Vault, or Tests. Execution, retrieval,
  models, realtime, and the other Harness folders are Harness subsystems, not
  Modules. Modules are neither Capabilities nor model-facing authority, and
  their Source projection never manufactures Module Articles in the graph.

The filesystem package hierarchy is the code-side projection of function just
as the Article hierarchy is the knowledge-side projection of meaning. Packages
stay shallow around real logical subsystems and declare a comprehensible import
direction. No first-party folder is named `modules`, and speculative
architectural layers are forbidden.

Obsidience is the agent harness and the visible shell of an Arch Linux system.
Hyprland is the compositor boundary: it owns composition, outputs, windows,
input routing, VRR, fullscreen behavior, and XWayland; Obsidience owns shell
surfaces, panes, providers, and agent interaction. Linux remains the plumbing:
kernel drivers, filesystems, systemd, udev, PipeWire/WirePlumber,
NetworkManager, and compositor protocols are reused rather than reimplemented.
A function moves into Obsidience only when one real Module slice passes a
bounded cutover with rollback. This direction never creates a fictional
Capability or a second authority path.

greetd launches the Hyprland UWSM session as the live default. One Hyprland
process owns Samsung through the RTX 4080 and USB-C plus logical DP-4 through
the AMD iGPU. One Quickshell host instantiates the shared pane registry on all
three logical Surfaces; native compositor input, clipboard, focus, and window
movement replace the former Xorg bridges. All live state uses the ordinary
`obsidience-shell` namespace. KWin, Plasma Shell, Plasma Login Manager,
KScreenLocker, SDDM, the isolated Xorg hosts, and Electron are archive-only and
never parallel runtime owners.

Desired architecture and observed state stay distinct. The System Application
record reports Hyprland as the live compositor. The existing Quickshell host
owns secure active-session locking through the upstream Wayland session-lock
protocol and PAM. A native Polkit UI, fullscreen HDR application behavior,
fullscreen VRR, and WoW remain explicit acceptance gates. Samsung desktop HDR
is active only on `HDMI-A-1` through the `hdr` preset and 10-bit scanout; a
225-nit SDR mapping restores the physically accepted desktop appearance.

The native knowledge desktop is a Shell component rather than a pane or
separate Module. One `graph_surface_id` inside the existing revisioned Surface
layout selects Samsung, USB-C, or DP-4 for the whole graph. The selected host
alone presents the existing standalone `GraphBackdrop` bundle from the
harness's loopback origin, preserving the one canonical Three.js and
`d3-force-3d` implementation without running Electron. This global selector is
presentation state, not per-Agent graph state or a second settings store.
The selected host retains the top-left Obsidience identity mark and places the
Executive root at the exact center of its own Surface.

Node selection sends one bounded `pane.present` command over the loopback
`obsidience.shell.v1` WebSocket to the primary host's `ShellCommandServer`.
The command carries a generic `pane_id` plus the exact Article selection; the
current allowlist admits Reader Article and exact Source selections. The server validates
the typed command, updates Reader's ordinary pane state, and broadcasts one
typed `pane.state` event. One global `PaneWorkspace` owns module definitions,
Reader docking, and one authoritative persisted placement record per pane. Each
undocked module is one Quickshell `FloatingWindow`, which is a real Wayland
`xdg_toplevel`. Its `screen` property expresses Surface intent; Hyprland maps
and places the native pane. There is no shared window canvas, QML focus ring, or
QML z-order authority.

Every undocked module toplevel has the exact initial app ID
`io.obsidience.shell` and exact immutable initial title
`obsidience-pane:<pane_id>`. The Hyprland adapter classifies a module only when
both initial fields match and never trusts a later mutable display title as
identity. Module clients remain in the native window inventory so the same
focus, close, layout, transfer, and geometry paths apply to applications and
modules. The Applications taskbar list alone filters rows carrying `pane_id`,
because the shell's pane buttons already represent them.

Hyprland is the only focus, z-order, outer border/shadow/rounding, interactive
move/resize, `Alt+Tab`, and tile authority. `input.follow_mouse = 0` makes focus
click-driven rather than hover-driven. Native `cycle_next` handles forward
`Alt+Tab`, and its reverse form handles `Alt+Shift+Tab`; the shell does not build
a mixed ring or activate a module separately. `PaneFrame` supplies only module
content and internal title-bar controls. Its title bar asks the `FloatingWindow`
for the standard Wayland interactive move and does not implement a second drag
or outer-chrome system.

Reader consumes the typed selection, reads either
the exact Article through `/api/articles/{ref}` or the exact Source bytes
through `/api/source-files/{key}`, and renders the result in a translucent
native Qt Quick pane. The WebKit surface is
graph-only: the shell has no `?surface=reader` route, Reader web view, or
React Reader wrapper. This preserves one graph implementation and one generic
shell placement contract without Electron IPC or a second coordinator.

Source listings use bounded, scoped keyset pages of at most 2,000 entries.
Coverage states whether a further live page exists; pagination is not an
integrity fault or a claim of snapshot consistency. Exact Reader lookup and
Source-tree checkout resolve the same allowed physical roots and explicit
accepted resource links independently of a listing page. Both clients assemble
all pages before replacing their visible inventory and retain the previous
view on failure. Accepted resource references are audited independently of the
page, so missing or invalid evidence remains a real integrity issue.

Reader also owns the native docking composition preserved from the archived
Electron interface. Knowledge defaults to its cyan left explorer and Source to
its violet right explorer; either can collapse into a 28-pixel rail, stack
above or below the other on one side, or detach back into its generic floating
pane. `PaneWorkspace` owns one atomic `obsidience.pane-dock-layout.v1` record.
A docked explorer renders only inside Reader's dock tree, with no standalone
toplevel. It follows Reader across Surfaces while its last floating
`PanePlacement` remains untouched. Detaching creates and maps exactly one module
toplevel with its intended `screen`; Hyprland places it and `PanePlacement`
mirrors the settled result. Reader stays the only Article and Source document
surface.

The native Terminal is another ordinary Surface-aware pane. It uses the
installed QML terminal emulator to attach to the existing `obsidience-ui`
linked tmux session as its sizing owner. The emulator fills the pane at a fixed
readable font, and tmux uses its largest attached client so rows and columns
reflow with the pane rather than leaving an out-of-grid field. DP-4 remains a
passive mirror and no longer constrains the native Terminal's dimensions. Pane
transfer replaces only the terminal view; the user tmux service continues to
keep the live Codex process persistent.
The prior Electron PTY bridge and xterm renderer are removed after this native
cutover; they are preserved only on the archived Electron branch and rollback
backup, never as a concurrent terminal path.

## Shell and Surface architecture

The stable boundary is:

```text
Arch Linux services
  -> Hyprland
  -> adapter/hyprland
  -> stable Obsidience Shell API
  -> one Quickshell shell host
  -> panes, providers, widgets, and AI surfaces
```

Only a compositor adapter may call Hyprland-specific event sockets or command
interfaces. It translates compositor state into stable Shell objects and keeps
observations separate from validated commands. No adapter contains graph
retrieval, model reasoning, pane presentation, or Task logic. Standard Wayland
protocols are preferred.

The adapter also publishes one bounded, revisioned **Shell Scene** covering
focused and unfocused native applications and module panes on every Surface,
including each Surface's current DPMS state. Every activation receives its
semantic projection in Thinking Packet Bindings; compositor identifiers,
geometry, and revisions remain private controller state. The scene is ephemeral
runtime context, not durable Knowledge and not a second graph.

`computer.observe` resolves one exact semantic scene target and uses the pinned
Wayshot Capability to capture that toplevel directly without activating or
moving it. One PNG is attached only to the next in-memory message for the
Task-selected vision model, then discarded; pixels and private identities never
enter the packet, ledger, trace, Source, or Vault. A sleeping target Surface
fails immediately as `target_not_visible` and is never woken implicitly.
`window.activate` and `window.place` are separate explicit effects through the
same Shell API and exact scene lease. Shell events may trigger an existing Task
only when that Task declares the event; focus churn does not manufacture Tasks.

One scene resolver owns the public target contract for all three Tools. A scene
row names an application by its registered ID, falling back to exact app_id;
module panes use exact pane_id. Display title stays separate. Observation
returns the concrete `target: {kind, name, surface}` for reuse, including when
the input selected the focused window. Registered aliases use the existing
application registry; arbitrary title matching and first-match selection are
not permitted. Registry matching requires the application's actual app_id/class;
a registered title discriminator may refine it, never replace it. An ambiguous
target fails without capture or effects. Placement
and activation supply their own verified post-state and need no extra screenshot.

A **Surface** is a runtime presentation endpoint, not an Article kind, Tool,
Capability, or synonym for a Wayland `wl_surface`. A Surface binds one physical
display workspace to the shell host and records backend, output identity,
geometry, scale, capabilities, and adjacency. The live Hyprland session admits
Samsung `HDMI-A-1` on the RTX 4080 at `5120x1440@240`, scale 1, 10-bit,
with fullscreen-only VRR, plus AMD `DP-8` and `HDMI-A-2` for USB-C and logical
DP-4. The RTX 4080 stays first in `AQ_DRM_DEVICES`; the RTX 4000 remains
compute-only. Samsung desktop HDR is physically accepted. Fullscreen HDR
application behavior, fullscreen WoW, and mixed-GPU presentation under gaming
load remain explicit physical acceptance gates.

Every module pane has one generic persisted `PanePlacement`:

```text
pane_id + surface_id + local_rect + open + optional tile_bounds
```

`PaneWorkspace` owns that one record beneath the user's XDG state directory.
`FloatingWindow.screen` expresses Surface intent. When an open module receives
a new native Wayland address, the shell sends its saved semantic `tile_bounds`
through the existing adapter exactly once before admitting native observation.
After that restore, or after a real move, resize, tile, or transfer settles,
Hyprland's observed Surface and geometry are runtime truth and `PanePlacement`
mirrors them. A failed or stale restore leaves the saved record untouched. QML
never computes a competing live geometry, focus order, or z-order, and process
teardown is never interpreted as an explicit close.

Pane-specific cross-display bridges and pane-specific outer drag authorities
are forbidden. `SurfaceLayout` defines the shared Surface-local logical-pixel
grid, defaulting to 10 px, plus minimum-size and usable-bound rules consumed by
the native layout. Settings > Workspace changes that single value, while pane
Modules contain no snap policy. The same definition supplies proportional
workspace tiling: Samsung is 8 by 2, USB-C is 3 by 2, and DP-4 is 4 by 1 by
default. Tiled clients retain current integer `tile_bounds`; their complete
chrome footprint has an exact 5 logical px outer and inter-pane gap. Hyprland
removes the 5 px outer gap from the layout work area, while raw adjacent boxes
meet at one shared cut and native 2/3 px asymmetric inner insets form each 5 px
opening. Every visible gap pixel therefore remains compositor-owned for the
standard resize cursor and drag path. The proportional grid projection adapts
the MIT Omarchy Windows Aero Snap pattern to arbitrary grids, but no compositor
plugin or second placement authority is loaded. Tile
bounds are non-exclusive placement coordinates: several native clients may
occupy the same exact bounds, and pointer hit-testing follows the same visible
front-to-back order as compositor rendering.

Hyprland's supported `lua:obsidience` layout applies that one grid to every
native application and undocked module toplevel. From freeform, `Meta+Arrow`
selects the complete edge row or column. Once tiled, the same chord expands one
cell toward the arrow or, at that edge, collapses one cell from the opposite
edge. The sole no-shift Surface exception is an exhausted `Meta+Up` on a
one-row lower Surface, which enters the corresponding bottom-edge tile above;
every other exhausted edge remains unchanged. `Ctrl+Meta+Arrow` translates
existing tile bounds one cell without resizing and is a no-op for freeform
clients. Tiled bounds override module-specific freeform minimum sizes; ordinary
freeform resizing keeps those limits. A native interactive move adopts the
nearest one-or-more-cell span from the released footprint. A native tiled resize
moves the grabbed internal column cut or the connected horizontal cut segments
shared by panes touching that exact edge,
retains the exact 5 px gap and fixed outer Surface edge, and preserves the
semantic `tile_bounds`. Settings > Workspace > Tile behavior bounds each cell's
manual expansion or contraction to 0 through 25% of its regular size, defaulting
to 25%. OLED displacement is applied independently to the resulting manual cut,
even when that carries it beyond the manual percentage envelope; only positive
cells and the fixed outer edges bound OLED motion. The cut offsets themselves
are compositor-runtime state, not another placement store.

The same Tile behavior section owns one optional Samsung OLED motion policy:
enabled state, maximum pixel drift, nominal center-to-maximum travel duration,
and neon rotation duration. It defaults to off, ±32 px per shared seam, one nominal active hour
from center to either limit, and one complete rotation per three active hours.
Each full-height vertical seam and connected horizontal segment starts at the
manual center, then follows its own deterministically directed reflected path
with ±10% pacing so the seams dephase without an activation jump. Both panes sharing a seam consume the
same coordinate, preserving the exact gap; opposing seams can therefore change
one pane by at most twice the configured drift. The effective amplitude is also
bounded by neighboring cell size and minimum-size headroom. One shared
one-second Hyprland timer advances every eligible seam and writes client
geometry only when a rounded coordinate changes. The same timer updates the
native cyan border and 5 px inner-glow angle no more than once per active
minute; Hyprland's continuous angle loop stays unused. Outer edges,
full-Surface tiles, USB-C geometry, and DP-4 geometry remain fixed. Hyprland's
native border and inner glow are compositor-global so the same application and
module chrome remains consistent on all Surfaces; only eligible Samsung active
time advances the shared angle. Fullscreen, secure lock, an unavailable Samsung
output, or no visible active Samsung workspace freezes physical and native-glow
phase without catch-up. Every retained callback is checked against the
Surface and workspace that created it before it can place a pane. OLED off
restores the manual baseline and ordinary chrome. Only policy persists. The
Stage has no separate outer-edge effect, texture, or animation. OLED
presentation is limited to Hyprland's native pane border and inner glow. There
is no GIF decoder, per-pane timer, scheduler Task, daemon, plugin, full-screen
effect, or second geometry authority.

Idle triggering is a separate upstream integration: official `hypridle`
requests the Quickshell session lock after five genuinely idle minutes, turns
all displays off through untargeted Hyprland DPMS after ten idle minutes, and
turns all displays back on at activity. Those two security listeners ignore
application idle inhibitors so a stale browser or video request cannot defeat
lock or post-lock screen-off; general hypridle behavior remains inhibitor-aware.
It owns neither PAM authentication nor suspend, brightness, pane geometry, or
OLED seam phase. The layout does not duplicate idle detection. The standard
live config path selects exact Source leaf
`obsidience/shell/idle/hypridle.conf`.

The lock remains fail-secure if its Quickshell client dies. Hyprland's native
`allow_session_lock_restore` setting permits only the replacement locker to
reclaim that state. The host startup performs one bounded reclaim, while the
canonical development restart command refuses to stop a locker that reports
itself secure or in progress. No second lock service participates.

Lock state does not own ordinary shell-client lifetime. Open pane windows,
their loaded content, every Surface launcher, and the selected ordinary
Three.js scene remain resident beneath the compositor's secure lock surfaces;
the ordinary scene is hidden and paused rather than destroyed. This leaves
privacy and input isolation with `WlSessionLock` while avoiding a complete
client and graph reconstruction at unlock.

`Meta+Shift+Arrow` moves the exact active client to the nearest mapped Surface,
preserving logical width and height; only a dimension larger than the complete
destination workspace is minimally reduced to fit. An unmapped direction
changes nothing. Each Meta shortcut sends exactly one token-bound request to
the native window adapter. The adapter binds the live active address and state
revision immediately before one Hyprland command; any failure is terminal.
The shortcut never preflights or falls back through a QML action. There is no
held-pointer handoff, pane-drag lease, coordinator process, or pane-specific
transport. `Meta+Esc` uses that same path to close the exact active client and
never sends a generic close to the Quickshell process.

Native applications use their own client-side title or tab-bar drag regions.
The shared module title bar requests the same standard Wayland interactive move
for its `FloatingWindow`. Hyprland 0.56.2 performs both operations and the Lua
layout adopts their released geometry. There is no modifier bind, global
primary-button interception, synthetic native-application title bar,
application wrapper, or second QML drag system. Compositor border, rounding,
shadow, focus, and stacking apply identically to both client classes;
application content remains native and unmodified.

Settings > Input projects one physical input truth through the compositor
adapter. The classic M.M.O.7 stays at its independently verified 6400-DPI top
stage; Hyprland applies one per-device custom linear `0.125` multiplier to
produce 800-effective-DPI motion across every Surface. No
per-Surface mouse scale, second profile store, or pane-owned compositor command
is permitted. Mouse is the live hardware/compositor view; Keyboard begins with
the current layout, repeat timing, and system remap state.

Every Surface in the one host uses the same Obsidience visual language and pane
registry. Shell packages may choose layouts and themes but never bind directly
to Hyprland or become competing shell owners. Widgets, data providers, and AI
surfaces receive only declared stable API capabilities. Basic launching,
window switching, notifications, volume, session controls, and recovery remain
usable when models, retrieval, or the graph are unavailable.

One shell host owns singleton shell responsibilities. Failure of a pane,
extension, model, or graph view must not terminate Hyprland or the desktop
session. The independent terminal is the recovery path.

The Shell owns one semantic presentation palette. `PaneFrame` uses it for
internal module controls; small adapters flatten the outer-chrome tokens into
Hyprland and supported
application-native theme contracts such as Edge's Chromium policy. External
applications remain native compositor clients and are never embedded,
reparented, mirrored, or made dependent on the Shell host's lifetime.

Session locking retains one Linux/PAM authority inside the existing Quickshell
host. `LockController` owns one `WlSessionLock` and one `PamContext`; the
compositor supplies a `WlSessionLockSurface` for every output. Every surface is
opaque `#02060c` before optional content loads. The Surface selected by
`graph_surface_id` presents the existing knowledge URL with `lock=1`, reusing
the canonical Three.js graph and physics, while the other Surfaces show the
shared Obsidience identity on the branded background. The password prompt is a
native QML overlay, authentication cannot begin before the compositor reports
the lock secure, and only PAM success releases it. The web graph never receives
credentials or decides unlock. PAM policy is installed root-owned at
`/etc/pam.d/obsidience`. The pinned Quickshell host carries the two source lines
required to satisfy Qt WebEngine's application-argument and shared-context
preconditions plus the three-file upstream `afb2c27` backport that guards
session-lock surface realization against reentrant screen activity. Both
patches and the deterministic build recipe live beneath `adapter/quickshell`.
Hyprlock, gtklock, and a second lock process are not part of this architecture;
greetd remains responsible only for fresh-login authentication. A native Polkit
agent remains a separate acceptance gate.

```text
obsidience/harness/
  __init__.py
  __main__.py
  config.py
  interfaces/{api,cli}/
  {execution,knowledge,conversation,models,realtime,computer,web,host,connections}/
  capabilities/<exact dotted Tool ID as directories>/<leaf>.py
```

Filesystem depth expresses stable responsibility rather than wrapper-only
folders. Prefer one meaningful subsystem level; use deeper structure only for a
real hierarchy such as the speech worker or a dotted Tool ID. Cross-subsystem
imports are explicit, package `__init__` files are side-effect-free, and generic
`utils`, `common`, and `core` junk drawers are not architecture.

Connections describe access to third-party services. A Connection may own zero
or more Feeds; each Feed selects an endpoint and bounded collection cadence.
They are configuration and runtime records, not extra Article kinds or agents.
Settings > Connections owns third-party access and credentials. The standalone
Feeds pane owns Connection-grouped feeds and captured items; selecting an item
presents it in the same Reader used by Knowledge and Source. The Feeds pane
uses their existing PaneModuleHeader and dock authority. Reader has four fixed
slots: upper/lower left and upper/lower right, one module per slot. Collapsing
or removing a sibling does not move a pane between slots; occupied-slot drops
swap docked modules or move the occupant into an empty slot without losing it.
There is no second Reader, placement authority or feed root in the graph.

Opening these panes only reads Harness metadata; it performs no provider I/O.
Host network interface inventory remains a separate System Source projection.
A selected Feed opens directly into Preview or Settings. Wide panes use a feed
sidebar; narrow panes use a compact selector. Preview holds publisher choice
and items; Settings groups collection, destination/retention and Darwin
instructions. The amount is edited only beside Preview; Settings links back
to that control. Connection access fields remain in Settings > Connections,
and new feeds inherit the chosen Connection address. Save/reset stay outside
the scrolling editor. The pane host supplies the title once.

Explicit Preview reads the current RSS/Atom endpoint through the same bounded
HTTPX acquisition and feedparser item parser used by collection. It supports a
draft endpoint on an existing Connection's exact origin before saving. The
response shows up to 30 unique entries in publisher order, available count,
publication dates, inert summaries and supplied-content indicators. The first
`item_limit` entries are highlighted locally; changing the count does not fetch
again. This is the first X publisher entries, not X unseen stories or a
relevance ranking. Existing captured versions remain deduplicated by ordinary
collection. Preview is transient presentation, never a raw Source, Task,
configuration change, cursor/validator update or second reader database. The
network response and the UI both reject stale connection/draft/revision
bindings. Opening or selecting an item never fetches its reporting page or
loads remote assets. Explicit Collect now remains the separate existing intake
action and uses saved Feed settings.

Reader projects a captured provider item as plain text and attests its exact
Source ID/path. It also renders a bounded, clearly labeled uncollected publisher
preview from the shell's ephemeral selection. Preview carries no fabricated
Source identity, performs no HTTP request or mutation, and enables no Article
edit or curation control. Selection admission invalidates pending fetch/save
responses so one document cannot overwrite a newly selected item.
Tide's simple source manager and FreshRSS's bounded reading widths are
presentation references. Existing feedparser and HTTPX provide the actual RSS
plumbing. Matcha's incremental item-processing pattern remains implemented
through existing Source/Index identities; no separate digest writer, reading
database or AI summarizer is imported.

The initial collector supports RSS and Atom through installed feedparser and
HTTPX. One Harness-owned async lifetime schedules acquisition off the event
loop. Each complete parsed provider item has a stable feed/native-item identity
and an immutable content version in existing Source; exact repeated material
uses Source's existing deduplication. ETag and Last-Modified validators commit
only after all selected items are captured. Configuration revisions invalidate
stale results, and disabling a Feed prevents a late request from capturing more
items. The existing Index stores collection state; no second database, external
job runner, or agent loop is introduced.

Source remains the ingestion boundary: a Feed's `source.added` activates Darwin's
Distill Task; general intake activates Learn. Darwin hands off a cited finding,
and `source.inbox` activates
Alexandria's Ingest Task. The Source delivery receipt commits atomically with
the Task's FIFO admission, including replay after the earlier Task completed.
RSS-provided content is raw evidence rather than an assertion that a linked
reporting article was fetched. Its `feed://` Source reference and embedded
reporting URL preserve that distinction for research.

A Source-triggered Learn or Distill activation names the exact admitted Source citation as
its objective and validates the UUID, event key, and content hash together.
Unrelated ambient Shell Scene and temporary Observations are excluded from this
activation. Before other research Tools or a successful outcome, the executor
requires complete matching-hash read receipts from the ordinary `source.read`
Tool. Handoff independently checks those receipts and includes the activating
Source citation. Completion requires the attested handoff or an explicit
Source-cited no-change outcome; a failed read can still end honestly as failed.
This is a prerequisite on the existing Tool boundary, not a hidden read, another
research pass, or a second pipeline. Explicit `task.create` research keeps its
ordinary bounded objective.

Each Feed selects an existing accepted Knowledge container with `destination_ref`.
Several feeds may contribute to the same node, including the ordinary
`News & Research/Top Stories` destination; configuring a Feed creates no graph
node. New feeds default enabled.
On Save, an otherwise unset destination policy defaults to Auto-curate enabled,
while explicit or inherited choices are preserved. The graph and Connections
read and write the same Article permission; Feed configuration has no duplicate
Auto-curate flag. Explicit Pause prevents further scheduled collection.

The Source item and its exact Feed/destination receipt commit before event
dispatch. Darwin's Distill Task reads that item, fetches only its exact reporting
page when needed, and sends one complete cited finding to Alexandria's physical
Inbox. Ingest preserves the complete handoff and compiles native OKF provenance
through the existing proposal owner. Enabled Auto-curate automatically accepts
eligible Articles; disabled retains Review. Immediate and later approval both
validate the current destination and attested Source lineage. Article identity
comes from the Feed and provider item, so updated versions use the same leaf
while the destination is unchanged.
Changing destinations affects new captures and never moves accepted history.
Feeds use their configured retention limits and do not impose a fixed 26-hour
expiry.

Feed policy separates `item_limit` (the first 1–30 unique publisher entries
checked per poll) from `max_active_articles` (1–1000 active Articles from that
exact Feed, default 10). The latter spans destination changes and counts only
native Inbox-to-Feed provenance, never every Article beneath a shared node.
Owner-moved Feed Articles remain counted but are protected from automatic
retirement; unexpected copies protect every copy of that item. Neither a move
nor a filename sort can silently remove provenance or authorize deletion.
Darwin's Distill handoff remains the automatic trigger: Alexandria's Ingest
compiles the incoming Article and the oldest excess Feed Articles into the
existing atomic Review group. Retirement preserves complete content, Sources and
history under `_archived/` with native OKF `status: deprecated` and namespaced
archive time/reason. It does not assert that an older report became false.
All affected Article Auto-curate policies and surviving inbound links remain
authoritative. A blocked or review-required retirement holds incoming
publication; the system must never claim the cap is satisfied while it is not.
An explicit retention-policy save also reconciles quiet Feeds through that same
owner, in bounded archive-only groups when a large reduction needs them. GETs
and the network collector never archive. No extra model pass or scheduler is
introduced, and `stale_after` continues to request Audit rather than deletion.
Large reductions retain their exact continuation in the existing Review
transaction journal until the successor group is staged. Task settlement waits
for the held Inbox publication or explicit rejection. Restart and policy-save
recovery preserve that obligation, recheck the current cap and original
destination, and never overwrite a newer accepted item version.

Optional `distill_instructions` is owner-authored Feed configuration, limited
to 500 characters. It controls focus and presentation within the existing
Distill procedure, never tools, placement or publication permission. The
existing atomic Feed receipt snapshots it with each newly captured item
version, separately from immutable provider bytes. Duplicate captures retain
that snapshot; edits never rewrite queued occurrences or redistill old items.
The compiler admits it through the exact Source binding and labels it as the
owner's captured instructions. The pane explains RSS/Atom's supplied titles,
dates, summary/content and links, separates collection and graph-retention
limits, and displays actual active count and retention disposition.

An API-only Connection can test read-only access at a configured endpoint without
creating a Feed. Generic JSON API streams and provider-specific event adapters
require their own actual acquisition implementation; a descriptor never grants
model-facing authority. Optional Bearer/Bot credentials use the installed
systemd-creds user encryption path outside Source and configuration. They are
write-only and bound to the Connection's exact HTTPS origin; changing providers
cannot reuse an old token, and authenticated redirects cannot cross origins.

## Recursive hierarchy

The same article law applies at every depth:

```text
Article -> child Article -> child Article -> leaf Article
```

Primitive decomposition uses one exact same-kind field:

- Task: `subtasks`
- Runbook: `subrunbooks`
- Tool: `subtools`
- Skill: `subskills`

The hierarchy must be acyclic. A selected descendant carries its ancestor
Articles as condensed context. Selecting a parent Task includes its descendant
Task scope unless an exact descendant is excluded.

Hierarchy and causation are separate. Only an explicit `subtasks` edge makes
one Task a child of another. `task.create` activates one exact accepted Task,
which keeps its authored hierarchy. Activation provenance records why it ran
and never changes either Task's hierarchy. Generate → Task authors reusable
definitions with `vault.propose`; activation never authors a definition.

One Task may have several ordered event triggers. The canonical `triggers`
list identifies those activation routes; manual execution and scheduling remain
available without manufacturing Task subtypes. A trigger changes runtime
bindings, never the Task's identity, acceptance contract, or hierarchy.

Do not use hierarchy merely to name procedure. Research framing, discovery,
screening, extraction, analysis, and verification are Runbook stages unless
one becomes a separately queueable outcome with its own acceptance condition.
Observations is the model exception: Immediate, Temporary, and Durable have
genuinely different lifecycles, so their deeper Task structure is useful.

## Work, procedure, and capability

A Task says what must become true. A Runbook says how to make it true. A Tool
exposes one operation through one exact Capability entrypoint. Its one paired
Skill tells a small model exactly how to use that Tool, including argument
selection, interpretation, failure handling, and safety. Knowledge supplies the
relevant facts and constraints. Modules operate the harness itself and do not
enter this Task authorization spine.

```text
Task
  -> Runbook
     -> Skill
        -> Tool interface
           -> Capability in Source
  + fast hybrid Knowledge context
  -> evidence and acceptance
```

A leaf Task must resolve an applicable accepted Runbook. A Runbook loads only
its explicitly required Skills. Each Skill resolves exactly one Tool, and each
leaf Tool resolves exactly one Capability entrypoint in Source. Assigning the
Task supplies that dependency closure; separate Agent Tool, Skill, or Runbook
grants do not widen or narrow it. Missing or malformed links fail closed; the
model does not invent a replacement Tool or procedure.

The graph response makes the same declared dependencies visible end-to-end:
Runbooks connect to their Tools, and Tasks connect to their Skills and Tools.
These are derived views of the typed binding chain, carrying the intermediate
Article refs and any Agent-specific applicability. Reader displays that path;
the desktop renders the same connections inside each appropriate Agent or
Library graph. Inherited Runbook guidance uses the shared hierarchy resolver,
without selecting siblings. No copied backlink lists, prose-based permission,
new authored bindings, or additional retrieval expansion are introduced.
The navigation manifest owns each graph's Article membership, including assigned
Task dependencies, selected hierarchy, and physical aliases. Reader selection carries the originating
graph identity; links and backlinks remain in that scope as the user navigates.
Library navigation uses its declared Tool+Skill and Task shelves without a
second filesystem projection. Displaying a related Article never assigns it or
grants executable authority. Parent and index Articles keep their own semantic
links through their exact visible aliases; hierarchy duplicates and absorbed
self-links are drawn only once or omitted, respectively.

The shared Library is authoritative for capability guidance. A callable named
`<tool.id>` has exactly one `Tools/<tool.id>` Article and one
`Skills/<tool.id>` Article titled `Using <tool.id>` with the singular edge
`tool: [[Tools/<tool.id>]]`. The applicable Runbook selects exact paired Skills;
the Agent never owns separate Tool/Skill grants or duplicate Skill prose.
Generated `@library/Skills/<tool/id>` IDs are display aliases, not authored
assignments. Multi-Tool order belongs in the Runbook, not in either Skill.

Runbooks are applicable procedures rather than independent Agent assignments.
The shared Library contains Tasks and Tool+Skill pairs. `Agent.tasks` is the
only manual work assignment. Accepted Runbook `task` and `for_agent` bindings
identify Agent-specific applicability; an applicable authored `Task.runbook`
also supplies its dependency set. Execution, graph membership, Reader, and
dependency displays resolve the same accepted bindings and hierarchy.

When an assigned Task lacks an applicable accepted procedure, `task.assigned`
activates the ordinary Generate → Runbook Task. Darwin receives the accepted
shared Tool+Skill catalog and selects the minimal subset needed for the outcome
and acceptance conditions. `vault.propose` requires explicit `metadata.skills`
refs, or native `metadata.obsidience.skills`; omission and wholesale catalog
copying are not dependency selection. The controller binds the exact Task and
Agent to the proposal. Approval makes the Runbook's dependencies available
without writing `Agent.tools`, `Agent.skills`, or `Agent.runbooks`. The assigned
Task waits for review while its procedure is missing. Source-tree checkout is
still independent Knowledge scope, not an executable grant.

## Agent structure

`Executive` is the user-facing role and the root Agent Article. A configured
personal name is merely identity data on that Article and never appears in
paths, protocols, object kinds, or architecture.

- **Executive** interprets the owner's request, chooses work, delegates,
  operates, and returns the verified result.
- **Alexandria** is the Curator. She owns Ingest, Curate, Merge, Link,
  Improve, and Archive and maintains the accepted wiki from bounded findings.
- **Darwin** is the Researcher. He owns Question, Learn, Distill, Model, and Generate.
- **Heimdall** is the Guardian. He owns Audit, Check, bounded Repair, and independent acceptance
  and integrity checks.

Each Agent Article directly owns Architecture, Tools, Skills, Runbooks, Tasks,
Other Agents or Subagents, and Observations. There is no extra Agent wrapper
beneath Executive or any specialist.

Each named Agent has one canonical `type: agent` Brain Article. A parallel
Knowledge role charter is an architectural duplicate of that Agent, even when
it contains unique detail or relationships. Merge must absorb that material
into the Agent Article, redirect references and meaningful edges, then stage the
ordinary shadow Article for archival.

## Activation and RAPTOR retrieval

Every live, manual, scheduled, or event-triggered request follows one executor
and one visible path:

```text
request or event
  -> select exact Task and assignee
  -> resolve Runbook, Skills, and Tools by graph edge
  -> retrieve Knowledge with lexical and vector lanes
  -> fuse ranks deterministically
  -> attach at most two direct typed graph neighbors
  -> pack one token-budgeted activation packet
  -> execute, verify, and record the attempt
```

The one visible Thinking Packet is semantically labeled and packed in this
order:

1. Agent Identity Article;
2. exact Task Article and acceptance conditions;
3. immutable runtime Objective for this activation;
4. authorized Tool Articles;
5. their exact paired Skill Articles;
6. applicable Runbook Articles;
7. typed bindings and exclusions that are not the Objective or controller
   provenance;
8. up to five accepted Knowledge Articles from fast lexical+dense RRF,
   preserving at least three direct hits when available and admitting at most
   two direct graph neighbors;
9. the exact `Current conversation` Article in the `Immediate Observations`
   packet section for an activation in the active Executive conversation.

Bindings always include the newest bounded Shell Scene or an explicit
unavailable reason. It lets the Agent name focused and unfocused windows and
Surfaces before choosing `computer.observe`, `window.activate`, or
`window.place`, but grants no Tool authority by itself.

All activations use the same 1,200-estimated-token Knowledge allowance. The
fast search has no elapsed-time deadline, generative expansion, or
cross-encoder pass. One immutable Objective drives retrieval, graph activity,
the provider packet, and the run ledger. It is the exact bound owner request
when present; otherwise it is the deterministic Task title followed by ordered
Runbook titles. Request, source, event, and response-contract controller data
are not duplicated into Bindings. Objective is runtime data, not an Article.
One typed result set may supply Knowledge and nominate a Task candidate, but
only the selected Task's authored edges fill the Agent, Runbook, Skill, and
Tool slots. The retrieval path is prewarmed before the API accepts its first
activation. It degrades without widening authority.
The Knowledge lane filters Article kind before each lexical/vector top-K, then
uses one accepted-Article snapshot for direct results, graph expansion, and
packet text. Neither direct hits nor neighbors may be staged, archived,
temporary, or explicitly excluded from retrieval. Generic Library search remains
mixed-kind. Embeddings are identified by their model artifact and actual input
text; metadata-only updates do not re-encode Articles. Synchronizers serialize
through a file lock, compute before publishing one SQLite transaction, and
invalidate the derived in-memory vector matrix on relevant local changes or
external database commits. This adds no service or second knowledge store.

The shared conversation selector binds the current explicit request and its
canonical application hint together, preserving the complete Objective. Spoken
repairs and foreground/visual requests select ordinary Computer Use; quoted
examples, descriptive questions and withdrawn commands do not gain Tool authority.
Its bounded computer outcome selects the completion evidence requirement:
focus, placement, observation, launch or in-client action. The executor records
that witness from the actual Tool result, never from model-authored evidence.
A missing witness or acknowledgment without a verified postcondition cannot
complete Computer Use successfully. Clarifications use a failed Task's public
summary instead of falsely declaring the computer effect complete.

An accepted task.complete decision is provisional until normal execution
finalization. Action Trace labels that distinction and records bounded speech
boundary and cancellation metadata (conversation, turn/generation, speech
sequence and transcript presence) without copying words or audio into those
diagnostics. Genuine barge-in still interrupts, preserves returned effects and
suppresses stale speech; VAD thresholds are unchanged. Tentative VAD onset
does not interrupt thinking or playback. The existing NeMo transcript path
confirms speech and emits the interruption before final endpointing.

Known failed/reviewed Task outcomes produce transient Chat and speech notices.
Only an accepted task.complete can supply their public summary; unexpected
executor errors use one fixed public notice while details remain in Action Trace.
Notices do not create successful assistant history or Immediate Observation
pairs, and work failure never changes the speech connection's lifecycle.
A speech-pipe failure records a delivery error without changing an already
completed Task or its exact Chat reply. Cancellation sends a new generation
before awaiting Task cleanup; the existing speech worker invalidates pending
playback during its preparation awaits without echoing an acoustic interruption.

Foreground admission is controller state in the existing scheduler. A conversation
turn or Realtime startup closes autonomous specialist admission and asks active
autonomous work to yield. Only the provider request may be canceled; an in-flight
Tool returns and records its receipt before the executor observes the boundary.
Accepted completion still wins. The interrupted occurrence and later FIFO remain
recorded for explicit disposition and must not be replayed by a cron tick.
Attested user-requested specialist continuations remain eligible. This creates
no new Task, Runbook, scheduling service, model preference, or speech owner.

The Task API projects current admission separately from its immutable last
attempt. A paused FIFO is waiting work; the previous failed or interrupted
receipt remains history with its exact run ID and time. Explicit owner Retry
pins that ID and the existing event inputs and FIFO, admits only a complete
read-only or no-Tool attempt with no child work or Review effects, and returns
the same occurrence to pending. It never changes the model or launches outside
normal foreground/resource admission. Unknown or possibly mutating outcomes
require separate disposition and cannot pass this retry path.

Promote validates its exact committed Temporary inputs through the observation
owner before model acquisition and again before archival. Older queued summaries
that fail the current completeness contract cannot consume inference or be
archived as valid context.

Shell Scene publishes each Surface's current columns and rows with explicit
`grid_edges` units. Invalid pre-dispatch placement returns that contract for
correction; uncertain delivered effects remain non-replayable. Exact tile success
requires the existing compositor layout's addressed-window readback through the
one Shell adapter, matching requested Surface and bounds after placement settles.
A verified no-op is reported honestly and is not evidence that a window moved.

The Executive's exact public dialogue is runtime state. One active conversation
uses an 80-turn in-memory deque backed by complete SQLite history; typed Chat and
Realtime speech append to that same ordered conversation. Enabling, reconnecting
or restarting Realtime preserves it. Only the owner's explicit New conversation
action rotates the identity; speech connection lifetime is not conversation lifetime. A final user transcript is
stored before execution, while an assistant turn is stored only after one
current execution produces a completed, nonempty public reply. Each assistant
row names its exact user row. Rotation never deletes prior SQLite rows.

That dialogue projects into one transient, unverified Knowledge Article named
`Current conversation` beneath the real `Observations/Immediate Observations`
folder/index Article. Immediate Observations and Temporary Observations are
sibling branches, while established owner preferences form the ordinary durable
Preferences subject. Their same-named Markdown Articles condense their children.
The current-conversation Article contains the newest cumulative Temporary
Observation summary, when present, followed by exact completed dialogue and
unresolved final owner requests after its SQLite sequence boundary. Accepted
failed clarification replies retain their explicit failed status and exact run
link, so the next correction can resolve the original question. Partial model
output and raw executor errors never enter this projection. It rides inside every Thinking Packet for that
conversation and its ref drives the same visible graph activation. It is never a
similarity-search candidate, executable authority, or durable claim. The current
owner request remains the Task binding and therefore is not duplicated into the
Article before execution.
The graph and Knowledge explorer consume the same API-derived folder parentage,
title and exact authored index ref. An index is absorbed into its folder node,
never repeated as a leaf; neither lifecycle gets a permanent-label exception.
Ordinary wiki maintenance and Review cannot rewrite or merge the runtime
Immediate/Temporary children. Compact and Promote own that lifecycle, while
indexes and durable Knowledge remain normal wiki-maintenance targets.

The ordinary `observations/immediate/compact` Task runs at a configurable
60-to-90-percent model occupancy threshold, default 80 percent, or when the
owner presses Compact. Occupancy is measured against the active Task's selected
model; Compact uses its own authored resident Executive model to reduce the completed
Immediate prefix into one self-contained cumulative Temporary Observation of at
most 2,000 characters. Every compaction summary is a separate transient,
unverified Article; exact SQLite turns remain unchanged. Ongoing/manual compaction
retains the last two completed pairs verbatim; a conversation boundary compacts
the remaining tail. Summaries use four brief headings: Goal, Constraints and
corrections, Verified state, and Outstanding. The newest committed summary for
the active conversation is protected from Temporary TTL pruning. Promotion
idempotence follows conversation sequence, not a permanent finalized-session
flag, so later dialogue in that same Chat remains eligible.
At a real conversation
boundary, Alexandria's `observations/durable/promote` Task archives the exact
Temporary bundle in Source and stages only justified owner-review candidates.
When New conversation explicitly closes an identity during speech, Realtime
defers only that old identity's final compaction and event until speech ends; promotion then waits for the executor to become idle.
Compaction and Source archival never create accepted durable Knowledge, and the
retired per-turn Maintain Temporary Observations activation does not run for
Executive Chat or Realtime.
Source archives retain their ordinary `source.added` event and an exact
controller-derived `observation_archive` class; that class bypasses redundant
Research Learn activation. It does not bypass Source storage or Review. Promote
reports `review` for staged proposals and `completed` for an honest no-change.

The activation compiler exposes one canonical packet and a provider serialization
of the same explicitly constructed sections. The provider system message contains
the fixed Agent, Task, Tool, Skill and Runbook spine. Immediate Observations form
one user-data message, followed by the current Objective, observations, bindings
and retrieved Knowledge in the next user message. Each Article occurs once in
that request; prior dialogue cannot extend current authority. The displayed packet retains the documented
ontology order. The compiler never rediscovers sections by parsing Article prose.
This real message boundary lets the installed model retain its existing sliding
window checkpoint after the fixed instructions, without a second packet owner,
prewarm inference or memory store.

Gemma's pinned b10078 launcher uses upstream `--checkpoint-min-step 0` with the
existing 32-checkpoint bound. Its default 8,192-token spacing otherwise evicts
the roughly 4.6K fixed-prefix checkpoint after a Tool follow-up, making the next
question re-evaluate the whole prompt. This changes checkpoint retention only;
F16 KV allocation and the sliding-window model remain unchanged. Live follow-ups
retained 4,632 input tokens and reduced first-public-token time from about 2.1
seconds to 0.8 seconds at the accepted 64K configuration.

The ordinary run trace records bounded numeric provider timing: `preflight_ms`
includes accounting/projection, `first_public_delta_ms` measures generation POST
dispatch to the first nonempty public content delta, `generation_ms` measures full
stream receipt, and `cached_input_tokens` is present when reported by the provider.
Private reasoning, role events and heartbeats do not count as public TTFT.
Transport metrics do not participate in action retry or completion decisions.
Model benchmark TTFT is separate from actual Task and complete speech latency.

The existing trace additionally carries bounded monotonic phase edges, correlated
by exact user-turn/run IDs and speech generation/sequence. The popup displays
these in an unnumbered response timeline. Phase durations may overlap and are
never summed. Speech detection is the confirmed VAD edge; first output is a
successful write in Pipecat's existing native queue, not measured acoustic onset.
The VAD stop and transcript fallback share one 0.7-second endpoint; resumed
speech resets it and duplicate stop edges cannot finalize twice. Complete worker
JSON records are parsed within 16 KiB before display text is clipped.

An activation reuses its accepted active-Article resolver for retrieval and
compilation; scheduler admission reuses its already-fresh notes. This is scoped
reuse, not a persistent file cache: selection still validates accepted Tasks
after inference and retrieval still reevaluates lifecycle/expiry. Direct Compact
threshold reads avoid a full Vault scan. A completed interactive answer-only
Query with exactly one accepted task.complete skips terminal index reconciliation
because only already-committed runtime state changed. Unknown decisions, any
other Tool, rejected completion, failure and other Task origins retain sync.
Selector JSON places catalog/context before the varying Objective, and the
provider's separate conversation boundary preserves reusable prompt checkpoints.


The graph's existing thinking notification projects that public Action Trace
as an expandable matrix of Tasks and their ordered steps. Stable event IDs
suppress replay overlap; exact run and call IDs keep repeated and interleaved
Tool invocations attached to their own results. The compiler exposes its own
ordered Thinking Packet sections as a bounded public display copy, including
actual accepted context and Immediate Observations. Tool inputs and returned
evidence render as named, expandable fields. Provider measurements belong to the
action or response produced by the same exact run and executor step, including
the `task.complete` response. Model lifecycle events do not create numbered matrix
steps. Pending generation appears as Task status; unmatched or failed requests
remain in unnumbered response diagnostics, never attached to the next action by
proximity. Resource waiting uses explicit waiting/started events. Public TTFT,
complete generation (which includes TTFT), preparation, and Tool execution remain
separate measurements; absent values are not reported as zero.
For `task.inspect` and `harness.status`, the Tool execution state stays separate
from the reported subject status. A successful read of a failed Task is Returned
with an explicit inspected-Task finding; a degraded health snapshot is likewise
an observed finding. Transport errors and semantic action failures remain failures.
Legacy events remain readable without invented correlation or inferred success. No private model reasoning,
pixels, observation leases or credentials are published.
Relevant Knowledge also displays the compiler's bounded selection accounting:
eligible nominated search hits and examined direct-seed neighbors, actual
supplied/excerpted/omitted decisions, reasons and body character ranges. Counts
cover that candidate set, not the full Vault. At most 32 details and a 16 KiB
public projection preserve explicit omissions and clipping. Character-based
selection estimates remain separate from exact provider tokenization. Reporting
does not modify packed text, Article order, or the model's instructions.

The existing `harness.status` snapshot projects historical patterns through
`history`: at most 200 runs and 400 Tool receipts started within seven days.
Run groups bind exact Task and recorded Runbook ref/hash; Tool groups bind exact
Task and Tool name/ref/hash. Findings require three eligible outcomes, two
unsuccessful outcomes, and at least a 50 percent rate. Each category exposes
sample completeness, exclusions, at most eight findings and three evidence
references per finding, plus observed duration sample statistics. Cancelled,
interrupted, review, started and undispatched states do not enter failure
denominators. Historical findings do not change current health or establish
root cause; returned Tool receipts do not prove semantic success. Heimdall's
existing Check reports these diagnostics without another Task or repair loop.
The existing trace owner caps event size at 64 KiB and history at 2 MiB / 500 events.
The popup retains at most 160 events in memory, including the current Task
heading and Thinking Packet throughout a long run; shortened content is labeled.
Opening or scrolling a row keeps the popup available for inspection independently
of the graph animation lifetime. Close dismisses the current activation; hidden
and lock states clear inspection. Only the popup captures its own pointer input.
Native Wayland on-demand keyboard focus admits Tab/Enter after interaction,
without exclusive focus or another input owner. No second trace service,
persistence store, polling lane or inference is added.
Mutable shell HTML uses `Cache-Control: no-cache` on both fresh and conditional
responses. The WebKit host explicitly requests revalidation at initial load and
Surface retarget; hashed static assets and local presentation preferences keep
their normal caching. This fixes a proven persistent stale-entrypoint cache that
otherwise survived presenter restart after a development build.

Selected-model tokenization supplies the occupancy meter with text counts plus
the measured packet overhead. Before every inference, including subsequent Tool
steps, the runtime counts the actual templated request including any image.
Unavailable text counting uses a conservative UTF-8 byte bound; unavailable
multimodal counting fails clearly instead of guessing. No separate tokenizer is
loaded. The complete Objective survives projection, with typed whitespace intact;
an oversized fixed packet is rejected with its required/available token counts
rather than silently shortened. Under pressure, the same model subsystem's
activation-local TaskContext projects older pageable Source Tool bodies from
actual `source.read`, `web.fetch`, or version-attested `vault.read` results.
Eligibility requires exact message binding and an authorized reread path. Article
pages include their exact ref, full view hash and offsets; continuation must
supply that hash, and changed Article/backlink snapshots return explicit stale
evidence without replacement content. No historical Article snapshot cache is
created. Read identity, provenance, exact
offsets and recovery instructions survive; the fixed packet, Objective, action
and effect receipts, and latest observation remain complete. Full-payload recount
selects a fitting projection. Original Source bytes remain immutable, and the
request projection creates no Knowledge or second conversation store. Accounting
evidence distinguishes runtime tokens from the conservative UTF-8 bound.

The existing HTTPX provider consumes SSE through pinned MIT `httpx-sse` 0.4.3
(recorded in `artifacts.lock.json`). A 300-second token-inactivity deadline
replaces the former total-generation cutoff: only nonempty public or private
reasoning deltas renew it, never transport heartbeats. Reasoning is counted only
as progress and discarded. Cancellation closes the request, and a terminal
finish state plus end marker are required before one public action can execute.
Malformed, incomplete or timed-out streams never cause automatic reconnect or
action replay.

The scheduler also reuses one fresh role resolver within each admission tick.
It does not rebuild the complete Vault for every Task during foreground/Realtime
checks. The next tick sees current roles; exact runtime occurrences and resource
admission remain freshly checked. This removed a measured 2.8-second periodic
event-loop stall (21 scans), reducing that tick to about 235 ms (two scans),
without another cache, index, worker or scheduler.

Gemma 4 has an explicit model-family projection at the existing provider boundary.
Its installed server template serializes system/turn/thinking tokens. A short
system clarification distinguishes the current Objective from prior Immediate
Observations and subsequent Tool results. Per-Task effort remains authoritative;
Low adds concise-reasoning guidance, not another reasoning selector. The native
JSON schema decoder restricts public action names to the Task's authorized set.
Interactive answers use the ordinary `task.complete` public summary for both
typed Chat and speech. Obsidience keeps the existing JSON action
protocol and argument/effect validation; this is not a parallel native Tool-call
loop. Other model families retain their existing provider format.

Architecture references (patterns only; no imported code or new dependencies):

- [Google ADK context compaction](https://adk.dev/context/compaction/):
  token pressure and retention of recent uncompressed dialogue.
- [Hindsight memory practices](https://hindsight.vectorize.io/best-practices):
  exact source identity, scoped evidence, and correction-aware consolidation.
  Obsidience keeps fast retrieval free of generative reflection and durable
  synthesis inside its existing Compact/Promote Tasks and Review boundary.
- [Gemma 4 prompt formatting](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4):
  native system turns, server-owned control tokens, and Task-selected thinking.

Task-selected reasoning remains private and may use the model's full configured
effort. Every public executor response is provider-constrained to one JSON
action object before parsing; the model never handwrites a fenced Tool call.
Provider finish state and bounded parse diagnostics belong in the run ledger,
while complete malformed responses do not.

The executor publishes the packet's exact Article refs and measured retrieval
duration for every activation. The graph animates that real path whether work
began in live text, live voice, Tasks, a schedule, or an event. Automatic speed
matches the measured retrieval duration without a time clamp; disabling its
checkbox gives the graph's Animation speed slider manual control.
The executor owns one terminal graph event in its activation finalizer, including
failure and cancellation. Interrupted attempts retain already-returned Tool
evidence; an in-flight Tool has an unknown, non-replayable outcome. Cancellation
still propagates to the caller and creates no assistant dialogue or replacement
Task. Realtime remains enabled. The model lease releases its ownership even when
default-model reconciliation is interrupted.

Model and reasoning effort are per-Task execution settings. Automatic routing
selects responsive Gemma for Executive and the fully GPU-resident Qwen3.8 9B
Distill for specialist Agents. Hardware is a set of independent component
slots, not a global model profile. The fallback configuration places Gemma on
the RTX 4000 Ada and OmniParser on the RTX 4080 SUPER, while persisted Hardware
selections remain authoritative; the AMD iGPU remains the USB-C display/media
device. A Task lease displaces only overlapping GPU components and restores
the saved selection afterward. Model layers never spill to CPU.

Temporary GPU reservations are admission conditions owned by that same model
runtime. One pure layout check runs before scheduler claim and again inside the
lease; a cached healthy layout cannot bypass reservations. Denial before model
activation does not reconcile unrelated defaults. Scheduled and user-delegated
exact occurrences remain pending with the existing blocked reason, retaining
their parameters, provenance, FIFO position and continuation. The ordinary
scheduler resumes them after release. Ephemeral manual or conversation requests
receive an explicit unavailable result instead of replay under a different saved
model or Objective. A late denial before any Tool effect restores the prior
occurrence identity; after effects, normal failure evidence and no-replay rules
remain authoritative. No new queue, Task kind, resource daemon or model fallback
is introduced.

The accepted 2026-09-05 Executive profile allocates 65,536 tokens to Gemma on
one RTX 4000 slot, retaining 3,584 output tokens and a 256-token input safety
margin (61,696 usable input). The launcher honors the saved max_num_seqs
explicitly; the prior omitted flag defaulted to four slots sharing only 16,384
total KV tokens. Live /props and GPU allocation attest the new context and one
slot with 3,227 MiB free after load, retaining F16 KV and the existing projector.
The larger capacity prevents pressure failures; routine requests still need
small current packets and no Executive reasoning for fast replies. Qwen Q8 stays
at 65,536 because its two-GPU layout has much narrower measured free margins.

Muse supports two explicit layouts: RTX 4000 text-only, or both GPUs with
vision and DFlash. The
dual layout is preferred for Tasks; RTX 4080-only is rejected because the
official 17 GB quant does not fit. Selection never changes Task identity, graph
authority, or the activation contract.

## Model addition loop

A catalog addition or artifact revision emits the ordinary `model.added`
event. Darwin's Model Task follows one accepted Runbook using four strict
Tool+Skill pairs: inspect the registered artifact, register its immutable
Source manifest, benchmark each relevant valid GPU layout, and apply only the
smallest measured configuration change. Benchmarking temporarily leases the
requested GPUs and restores the saved Hardware assignment afterward. Existing
catalog entries are baselined on first registration so enabling this mechanism
does not create a retroactive activation storm.

The Models pane projects supported modalities and features, quantization,
context, valid hardware,
current residency, the latest commensurate benchmark, and the model Source
manifest. Hardware separately owns saved component residency. Source stores
small immutable manifests and measurement records that attest the external
model blobs; it never duplicates multi-gigabyte weight files.

Every text-generating model benchmark has one standalone primary contract:
the exact same prompt, a 256-token ceiling, temperature zero where supported,
one discarded warmup, and three measured samples. TTFT is the median time from
request dispatch to first public output. End-to-end tok/s is aggregate actual
completion tokens divided by aggregate complete request wall time, including
TTFT and prompt processing. Frame cadence, interruption acknowledgement, audio
prefill, and startup remain useful secondary diagnostics; they never substitute
for a standalone per-model receipt.

Models presents Task reasoning models only. Hardware presents the fixed speech
runtime: Pipecat transport, NeMo turn taking, Nemotron streaming ASR on the RTX
4080, and Pocket TTS on CPU. Hardware selects the Star Trek Computer, HAL, or
Ultron Pocket voice. The raw voice-training corpus is not imported.

Hardware cards are also compact read-only sensor suites. Every card exposes a
memory meter and utilization meter, then the device-specific live readings
available from `/proc`, Linux hwmon/amdgpu, or `nvidia-smi`. Sensor polling is
visible-pane only and does not change component assignment, Task routing, or
model configuration.

Hardware owns exact microphone input and speaker output for the next Realtime
start, plus one preferred physical camera for future camera-capable Tools.
Choices project the live PipeWire and physical V4L2 inventory and never change
system-wide defaults. Agent video feeds are a separate input class: the TFT ADB
feed belongs to the Realtime experiment and is never listed or persisted as a
camera. Video and camera must not share one UI or semantic slot.

The thinking graph visualizes this actual activation path. It stays static when
the harness is not resolving a request.

## Missing-knowledge loop

A small model must not guess around a real gap.

1. Executive identifies the missing fact, procedure, Tool, or Capability.
2. Executive activates Darwin's Question or Learn Task with one bounded gap.
3. Darwin gathers direct evidence and stores immutable raw Source objects. Each
   `source.added` occurrence routes through the existing Learn Task; supporting
   captures inside that active occurrence coalesce into the same commitment.
4. Darwin drops one bounded source-backed synthesis into the physical
   `obsidience/evidence/inbox/` through `source.handoff`.
5. The durable `source.inbox` event activates Alexandria's centralized Ingest
   Task, which reconciles the handoff and its cited Sources into the smallest
   coherent set of Articles and links.
6. Heimdall verifies evidence, graph integrity, or acceptance when the change
   is risky or consequential.
7. The original Task is retried with the newly retrievable knowledge.

If the gap is reusable work or a Tool interface, Generate creates the
appropriate Task, Runbook, Tool, or Skill. A proposed Tool cannot activate
until its exact Capability binding, singular Source-linked entrypoint, and one
paired Skill all validate.

## Wiki maintenance

The main maintenance families stay shallow:

- **Executive:** Query and Computer Use, shared by typed and spoken requests.
  The grouping is Knowledge and Query keeps the canonical `Tasks/query` path.
- **Wiki:** Ingest, Curate, Merge, Link, Improve, Archive, Audit,
  Check.
- **Research:** Question, Learn, Distill, Model. Learn accepts general
  `source.added`; Distill accepts Feed items. Neither creates per-item Tasks.
- **Generate:** Tool, Skill, Task, Runbook.
- **Observations:** Compact and Promote as direct Task children. Immediate,
  Temporary and Durable describe the data lifecycle, not extra Task groups.
  The observation Tools and paired Skills are also direct children of their
  Observations Library group. Shared parent membership controls graph and
  Reader presentation while preserving exact callable and persisted Task IDs.

Curate performs one bounded scheduled inspection. When its Runbook detects a
high-signal maintenance lead, it may activate the exact accepted Merge or Link
Task; that Task independently confirms and completes its bounded outcome
through its own Runbook. Merge owns duplicate consolidation, while Link owns
missing Article relationships. Editorial actions such as copyedit, categorize,
split, and retitle remain branches within the Improve Runbook. An existing
folder Article and native hierarchy satisfy structural child coverage;
Improve must not synthesize per-child Markdown tables of contents or duplicate
hierarchy links. `missing_index` remains for real folders without their folder
Article. Parent condensation and evidence-backed editorial improvements remain
in scope, and existing retention checks protect real accepted inbound links.
Evidence-grounded routine
maintenance may be accepted automatically after deterministic validation.
Conflicts, destructive lifecycle actions,
authority changes, and high-risk effects require independent Guardian or owner
review. Review is a risk control, not the normal wiki-writing mechanism.

Native OKF `stale_after` is an absolute freshness boundary, not a claim that
an Article has become false. Curate routes elapsed deadlines to Audit; explicit
`status: deprecated` or a supported supersession routes to Archive. Archive
retains content, documentary Sources, and history below `_archived/`, with root
`status: deprecated` and namespaced `archived_at`/`archive_reason`. Automatic
activation context excludes expired/deprecated Knowledge at read time; explicit
read/search retains access and `vault.read` reports a bounded lifecycle view.
Document status remains separate from Task execution state and verification.

Review is serialized at the Article boundary. Only one unresolved proposal may
target an accepted Article, and updates or archives pin the exact accepted base
revision they were drafted from. API queue reads share the decision lock so a
poll cannot inspect a proposal halfway through publication. The native pane
retires acknowledged cards before enabling another decision, ignores older
queue responses, and reconciles a failed response through a read without
automatically replaying the decision. A Task in `review` cannot be reactivated by
`task.create`. Redirect updates are decided before their dependent archive;
the Review projection disables a dependency-blocked decision instead of
letting an ordinary click fail or overwrite another complete replacement.
Review decision and execution finalization are order-independent: deciding all
proposals from an exact run while it is still finishing completes the Task and
the late `task.complete` result may not restore stale `review` state.
Feed publication and its required retention use one bounded group of these same Article proposals.
Each member pins its exact base and the group pins membership, metadata and body
hashes. One Review card describes every create, update and archive; a stale member
blocks the whole decision. Validation resolves the complete candidate graph before
publication. The existing Article lock gives graph readers one coherent publication,
and the ordinary decision ledger records all members in one SQLite transaction.
A bounded preimage journal in staging recovers an interrupted group before startup
reconciliation or indexing; an unrecognized newer edit fails closed. Source and
Review remain the existing authorities, with no second publisher or scheduler.

The accepted Task taxonomy also classifies the review object: a proposal staged
by the exact Link Task is a first-class Link review, while every other proposal
is an Article review. The harness records that class, derives it for older
proposals, and projects the exact added and removed Article links. The model and
UI may not guess or override it. Approval still applies the complete Article
replacement atomically, so Link reviews do not create a second mutation path.

Link review evidence is controller-derived proposal metadata: the exact changed
wikilink, its body line and excerpt, and the endpoint revision captured at staging.
The proposed body is also pinned. A syntactically present link is not a verified
semantic relationship; the existing explanation and Review decision establish
whether it is useful. Missing/invalid endpoints and stale source or proposal
bodies fail closed; endpoint revision drift produces a visible warning without
rewriting the pending proposal, so reciprocal links remain independently reviewable.
Link changes only
non-runtime Knowledge/Agent bodies, never executable authority. Evidence stays
with the review object rather than becoming another Article kind or trust score.

Curate's existing maintenance Tool reports bounded connectivity diagnostics
alongside its semantic leads. Components and isolated endpoints describe accepted
Article links, not the folder hierarchy and not a requirement to connect unrelated
subjects. Only the existing Runbook can issue a peer Link or Merge Task.
The existing index retains metadata-aware invalidation and unchanged embeddings;
an explicit missing Article path never falls back to an unrelated same-basename
Article after deletion or rename.
Stale maintenance occurrences may be retired by the existing scheduler only
after attesting the exact Curate activation receipt and a conclusively empty
attempt. Settlement records a separate no-effect controller receipt and advances
one FIFO head atomically; prior failed executions remain unchanged. Original
signed arguments are verified before comparing canonical runtime values. Equal
integer/float values survive normalization, while boolean/number substitutions,
changed values and incomplete evidence cannot authorize settlement. A newer
accepted revision remains eligible for a fresh Curate lead.

These are narrow pattern references to
[Graphify's relationship evidence](https://github.com/Graphify-Labs/graphify/blob/33362d969292b57eda82f3fbd9eb5f3f5bc9bbc2/graphify/symbol_resolution.py),
[connectivity analysis](https://github.com/Graphify-Labs/graphify/blob/33362d969292b57eda82f3fbd9eb5f3f5bc9bbc2/graphify/cluster.py),
and [incremental reconciliation](https://github.com/Graphify-Labs/graphify/blob/33362d969292b57eda82f3fbd9eb5f3f5bc9bbc2/graphify/watch.py).
No Graphify code, clustering dependency, daemon, exporter, or second graph is
imported. Codex's separate codebase-memory-mcp index is development navigation
only; it cannot grant Obsidience Tool authority or replace the Article vault.

Articles should be concise, self-contained, current, and pleasant to read.
Remove duplicated summaries, migration history, receipts, generic filler,
unresolved framework vocabulary, and facts that do not improve retrieval or
execution.


Harness execution continuity, 2026-09-09: each leaf activation records exact
receipt coverage in the existing SQLite ledger before dispatch. Each actual
Tool call commits intent before invoking its Capability and one immutable
terminal receipt immediately on return. Receipts contain exact identities,
accepted Tool hashes, outcome, duration and result hash/count; public trace
text never authorizes retry. Interrupted effects, missing coverage, changed
inputs, pending Reviews and continuations prevent automatic event replay.
Only attested read-only or proven-undispatched work can pass ordinary restart
admission. Per-call metadata is bounded and follows existing run-history
lifetime; there is no new global run-pruning policy. task.inspect retains
original/omitted counts and completeness when display evidence is clipped.

The sanitized public trace keeps at most 500 events and 2 MiB in that same
ledger. Monotonic cursors resume delivery after disconnect; expired cursors
and queue gaps explicitly recover from retained history. Event publication
from workers joins the API loop. Model events remain measurements attached
to the response or action they produced. Pixels, credentials and private
reasoning never enter either public trace storage or Tool receipt payloads.

The API lifetime owns one HTTPX provider pool. The first decision-budget
notice remains in request history; common Task instructions precede varying
voice guidance. Request projection may still remove consumed images and
recoverable old pages. Occupancy presentation performs no tokenizer network
I/O; an asynchronous exact count confirms estimated threshold pressure before
routine compaction. An unavailable estimate cannot alone start compaction;
the complete templated request guard remains authoritative on every request.
Model choices, precision, context allocation and reasoning selections remain
Task-owned.

model.configure and model.benchmark await the existing Model runtime through
native async capability dispatch. STOP releases cancelled leases without
loading default models during cleanup. Reconciliation remains visibly pending
until the next normal owner admission/initialization settles it. Cancellation
after committed settings or measurements retains the actual result, reports
unreconciled runtime state, and ends the Task before another decision. The API
unwinds acquired owners on startup failure as well as normal shutdown.

Chat's Clarify action targets the exact active owner turn and its existing
leaf Task. At most eight 2,000-character clarifications enter the current
activation at model/Tool boundaries. A clarification supersedes an unfinished
model decision before its Tool dispatch; a running Tool retains its actual
outcome. The original Objective, Task, computer outcome and authorized Tools
remain unchanged. Completion validation closes admission and a rejected
completion reopens it. Stale input is rejected; text received across closure
is saved explicitly as unapplied. Applied IDs bind the exact conversation/run
receipt, so later context distinguishes an applied clarification from an
unresolved request. New requests and speech interruption retain ordinary Task
admission and STOP behavior.

## Runtime and interface projections

The Python harness owns indexing, retrieval, activation, execution, scheduling,
Source integrity, and the run ledger. The native shell UI is a thin projection.

- **Graph** shows the real hierarchy and active retrieval path. Graph Settings
  also selects the one physical Surface for the whole graph; per-Agent
  placement is not part of this slice. Render refreshes retain each cloud's
  positions, velocities and force cooling state unless its actual topology,
  collision radii or force settings change. Task status and other paint-only
  changes update appearance without disturbing node positions. The main graph
  and satellites use the same physical-input comparison; a changed cloud does
  not reheat unchanged neighbours.
  Semantic depth also determines a shared spherical layer in each 3D cloud:
  every direct Brain branch occupies the first layer, and each deeper declared
  level follows in order. The first layer retains the original close spacing
  of 1.4 taxonomy spring lengths, subject to collision and packing floors.
  Cube-root increments beyond that anchor preserve the spherical
  cloud when branch depths differ, with packing and node clearance as floors.
  Private simulation depth follows exact parent chains,
  so the 2D renderer's common Article paint tier does not move a shallow Article
  to a deep shell. The layer radius reserves radial clearance for node
  sizes and spherical surface space for its population. Crowding expands the
  whole layer and carries later layers outward without changing ancestry.
  One final coupled constraint predicts d3's damped integration and resolves
  contacts as great-circle motions on the assigned shells. The outward
  parent-child cap, recursive crown boundaries and avoidance spheres are solved
  together, so a later radial correction cannot undo collision clearance.
  New article and branch seeds use the same parent-derived shells before the
  first frame. Valid retained states keep exact positions, velocities, cooling,
  solver progress and expanded-layer capacity across presentation updates.
  Crown membership follows exact parent ancestry at every fork. Current sibling
  directions define moving angular boundaries; descendant avoidance demand at
  each layer supplies a bounded capacity bias. Entire crowns receive gentle
  angular spreading, then individual nodes resolve full avoidance-radius
  clearance. Only Brain is pinned; there are no fixed or camera-facing sectors.
  Direct-fan packing reserves space in each parent's outward cap. Persistent
  capacity violations may enlarge the lowest affected whole layer and propagate
  clearance outward, never moving an unchanged inner layer or a lone node.
  Cooling alone does not finish layout. Eight consecutive cold, low-motion
  ticks with valid shell, contact, outward and territory residuals mark it
  settled. Work remains bounded: twelve constraint passes per tick, at most
  eight capacity expansions per layer, and an 880-tick geometric budget.
  Unresolved terminal states are explicitly needs-capacity or stalled, exposed
  through cloud diagnostics and a one-shot warning, not reported as settled.
  This remains inside the existing scene-owned d3 tick; semantic spring
  strengths, separate 2D physics, review effects and graph authority are unchanged.
  Branch coherence cannot guarantee disjoint screen projections from every angle.
  Pending Link additions spring into their eventual visual layout and glow in
  the actual link gradient, with an awaiting-review legend. This bounded preview
  belongs only to the Scene: its physical edge union and degree-sized radii match
  the eventual accepted result, while the accepted model remains the only source
  for thinking paths and semantic use. Approval replaces the preview in the same
  fresh graph snapshot, preserving positions, velocities, cooling and curve
  geometry; its four-second confirmation glow fades into the normal edge.
  Canonical private force input ordering preserves ongoing motion across rebuilds.
  Rejection removes only its proposal's constraints, allowing the remaining graph
  to settle without reverting intervening changes. The existing Review authority
  and activity stream retain ownership; original approval time bounds replay and
  reconnect, and a stable per-proposal entrance time prevents polling/rebuilds
  from repeatedly springing in the same link. A proposed link remains unaccepted
  knowledge until the actual Review decision.
  Cross-links meet their Articles or hierarchy nodes directly. Same-level links
  follow their shell, while links between different levels may cross shells.
  The shared route interpolates the live endpoint radii and angles; it adds only
  a sub-half-percent correction for rendered-segment sag. Article-size clearance,
  raised endpoint leaders and extra outward bow are absent. The retired Link
  curve setting is read only for persisted compatibility. Normal links, Review
  glow and travelling streaks use this exact route in every cloud; streak tails
  clip individual segments without shortcutting bends. Force positions remain
  the authority for placement; this change creates no fixed rings or force rule.
- **Reader** reads and edits Articles and opens linked Source files in the same
  center surface.
- **Knowledge explorer** shows the real vault hierarchy.
- **Source explorer** shows the exact bounded project filesystem: wiki
  Markdown, application code, stable System descriptors, and immutable raw
  sources. Its System branch follows the physical
  `state/system/{hardware,applications}` folders, with Network beneath Hardware.
  One bounded descriptor catalog supplies both Source labels and the deterministic
  ADMECH Knowledge mirror. The root and application descriptor files become their
  own folder condensations; fixed observed facts enrich only actual schema nodes.
  Authored workstation knowledge remains under Workstation Observations.
  System captures live separately in `evidence/system/` and do not create a System
  branch. Knowledge Markdown directly exposes `vault/`; Evidence exposes raw
  captures, manual imports and Alexandria handoffs; Project Files exposes code.
  The UI may format a real
  folder label, but cannot invent its existence or contents; every leaf still
  carries its exact project-relative disk path. Selecting
  an Article can cross-filter this one view to its Markdown and associated files;
  clicking any result opens the bytes at that exact displayed disk path in the
  same Reader. Tool Capability
  files carry their exact Article link, while internal Modules, interfaces, UI
  code, scripts, tests, and telemetry remain outside the graph.
- **Source checkout** assigns one subtree independently to any Agent as a
  Knowledge scope. It maps only to related accepted Articles and biases the
  existing five-Article fast retrieval. Source files never become graph nodes,
  Library assets, executable authority, or unconditional prompt content.
  The exact System scope maps to ADMECH Workstation; Hardware and Applications
  narrow that priority to their exact accepted schema mirror Articles, excluding
  unrelated workstation Observations. Descriptor leaves narrow to the exact Article.
- **Library** shows shared accepted Tasks and Tool+Skill pairs. Tasks may be
  assigned; Tool/Skill availability is derived from assigned Task dependencies.
- **Tasks** shows only scheduled, event-triggered, or active Tasks, including
  inherited descendant scope.
- **Review** shows only material that actually requires a decision, with Link
  reviews visually distinct from ordinary Article reviews and their exact
  relationship delta visible before approval.
- **Applications** lists real desktop entries and uses PackageKit through the
  system Polkit boundary for native package search, install, and removal. It is
  an ordinary pane; the far-left bar button remains a separate transient
  Start-style launcher for opening applications.
- **Terminal** owns the `obsidience-ui` tmux view and its viewport sizing while
  the persistent tmux service preserves the underlying development session.
- **Settings** is one sectioned shell pane. Graph owns its first section and
  continues to command the canonical Three.js store. Input projects the live
  Mouse and Keyboard state. Workspace owns shared pane behavior, beginning with
  the global 10 px pane-grid selector. No section is a separate pane or bar
  item.

No UI module may carry a copied claim catalog, static semantic ontology, second
scheduler, second memory store, hidden activation path, or duplicated Agent
subject/name dictionary.

## Realtime Executive

The Realtime button controls the speech connection and session infrastructure.
It keeps audio available between requests and has no Task, Runbook, Thinking
Packet, or reasoning-model selection of its own. Each final transcript selects
the same accepted work as typed Chat: `Tasks/query` or
`Tasks/executive/operate`. Each Task's authored `model` and `reasoning_effort`
remain the only reasoning selection. Both explicitly select `obsidience-gemma`;
Query and Computer Use both use `none` effort, following the owner's
2026-09-05 responsiveness preference.
Pipecat and NVIDIA NeMo provide speech transport; Nemotron transcribes on the
RTX 4080 and Pocket speaks on CPU. No second Agent, planner, verifier, Tool
authority, or Realtime-specific model selector exists.
Pipecat's upstream `LocalAudioTransport` owns the selected local input and
output. Obsidience does not add a browser audio client, audio WebSocket, or
custom capture/playback processor.

The existing input transport reports bounded microphone levels before ASR and
projects its provisional VAD edge as `capture_active`. That edge is visual
feedback only; NeMo's confirmed speech edge still owns interruption and final
transcripts alone select work. The shell's single `ShellApi` subscribes to the
existing `/ws/realtime` stream and shares that presentation with every Surface.
The recognition strip consumes partial text on arrival and renders a bounded
recent level history as native QML waveform bars, inspired by Voxtype's compact
oldest-left/newest-right envelope. No Voxtype runtime or audio subsystem is
imported. The earlier two-second HTTP polling delayed otherwise-live words;
there is no replacement polling loop. Disconnect and session transitions clear
transient capture visuals, while completed conversation text retains its
ordinary final-only path.

Realtime ready wakes the OBSBOT camera through its official SDK and Realtime off
sleeps it. While Realtime is on, that SDK command disables the camera's 120-second
no-video auto-sleep timer; off restores it. The camera's real hardware state owns
its microphone state.

Each final transcript executes its selected work Task through the one activation
compiler, model lease, Tool path, ledger, graph activity, and ordinary
`task.complete`. That terminal result's public summary is the answer delivered
to Chat or spoken by Pocket. Completed work leaves the speech connection ready
for the next request. Speech onset cancels Pocket playback and the in-flight
Task generation. Backchannels may be
filtered without granting semantic authority to the speech layer.
NeMo's serialized `UserStoppedSpeaking` edge owns the persistent user-speaking
state; a visible final transcript never substitutes for that turn boundary.
The final transcript and final public reply also project into the same Executive
Chat conversation used by typed input. Canceled, failed, blocked, interrupted,
or generation-stale output never becomes an assistant conversation row.

At session start, Realtime validates and freezes the selected microphone,
speaker, and Pocket voice. Hardware changes made while it runs are saved for
later and never mutate the active audio graph.

The speech owner retains explicit enabled intent in its existing same-login
runtime directory. Explicit Stop clears it; Harness shutdown preserves it.
Harness startup restores that intent through the same speech and hardware owners
before opening scheduler admission. Missing or invalid intent leaves speech off,
and a failed restore reports its error without a retry loop. In that error state,
speech is inactive and the scheduler uses ordinary hardware admission. This runtime marker
does not survive reboot or become conversation, Task, or Knowledge state.

While the Realtime connection is active, autonomous specialist schedules and
triggers remain pending before claim. An interactive Executive execution may
use its authorized `task.create` to activate Research Question or Learn as an
explicit delegation exception. The controller derives that interactive and
creator provenance from the actual execution; caller arguments cannot supply
it and it never creates hierarchy.

## Definition of done

An architecture change is complete only when:

- the vault validates with no broken load-bearing edges;
- every Tool has exactly one paired Skill, exact Capability binding, and
  singular Source-linked entrypoint;
- the filesystem, Source explorer, graph, Reader, Library, and Tasks projections agree;
- Python compilation, UI typecheck, and production build pass;
- both development services have been restarted;
- the actual USB-C interface and core API endpoints have been verified; and
- accepted project text contains no predecessor architecture or Tool claim
  without its real Capability binding and entrypoint.


## Contextual Executive admission and completion: 2026-09-05

The existing Conversation coordinator prepares current context before semantic
Task admission. One bounded non-reasoning call through the configured Executive
model selects only the assigned Query or Computer Use Task from the accepted
outcome catalog, exact request, current semantic Shell Scene, recent dialogue and
bounded historical Tool evidence. It creates no additional Agent, Task, model,
scheduler or knowledge store. Invalid selection fails before Task claim; there
is no current-text keyword fallback. Measure selection latency separately.

Controller Bindings carry computer_outcome and action-only computer_scope.
Input scope requests one click; state scope requests the resulting application
state. A gameplay request in an open application must not become another launch.
The immutable run records its original binding for continuation. Continuations
reuse that binding and Task, never reclassify the objective from current state.
Historical execution evidence is a bounded projection of exact conversation/run
links. Assistant claims never attest delivery, and an earlier receipt never
establishes current state or grants another effect.

Query cannot complete a controller-bound computer outcome. State completion
requires a current execution action, actual post-action image supplied to the
immediately preceding model response, and a structured visual verification
finding. Invalid/intervening responses, rejected completion, cancellation and
provider failure consume that image evidence. This records Gemma's visual
interpretation, not independent proof of semantic accuracy. Three distinct
state steps are allowed only with a separate newer computer.observe before each;
input scope remains one attempt. An uncertain click is never retried.

Context selection, historical evidence and completion repair preimages are under
/home/wissenschafter/backups/obsidience-conversation-intent-20260905-230126.

Interactive Executive activation also receives an ephemeral local clock and a
bounded catalog derived from the currently accepted assigned Task/Tool Articles.
The catalog is explicitly descriptive and grants no additional Tools. It
excludes scheduled/event work and reports omissions. The selected Task's spine
remains the sole authority. This prevents older broad permissions or archived
architecture descriptions from masquerading as implemented capabilities.

Speech stop or worker failure never enqueues finalization of the still-selected
conversation. It drains only boundaries already requested by New conversation.

The Compact lifecycle rejects incomplete summaries at append, commit and
historical selection. Invalid older summaries do not advance the active
sequence boundary; exact SQLite dialogue remains recoverable. Required sections
are Goal, Constraints and corrections, Verified state, and Outstanding, each
nonempty. Structural validity does not establish semantic truth.
