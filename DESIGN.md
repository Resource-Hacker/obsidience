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

## Canonical Article kinds

Accepted frontmatter uses exactly six semantic kinds.

| Kind | Meaning |
| --- | --- |
| `knowledge` | Facts, constraints, context, explanations, indexes, domains, and observations |
| `task` | A reusable outcome with inputs and acceptance conditions |
| `runbook` | The ordered or branching process for completing a Task |
| `tool` | One executable interface with declared arguments, effects, and failures |
| `skill` | Exact practical instructions for using one Tool correctly |
| `agent` | An accountable executor with a role and checked-out work and Tool+Skill pairs |

Knowledge is the descriptive default. A domain such as Games or a subject such
as Architecture is a Knowledge Article. It becomes an index by having children;
it does not become a separate Domain or Index object.

Source is intentionally outside this kind list:

- **Source** is one typed, read-only view over the real Obsidience project tree:
  `obsidience/vault/` contains wiki Markdown; `obsidience/evidence/` contains
  immutable raw material; `obsidience/harness/`, `obsidience/ui/`,
  `obsidience/scripts/`, and `obsidience/tests/` contain application code; and
  `obsidience/state/system/` is the physical System inventory. Its real folders
  are `hardware/{compute,drives,devices}`, `applications/`, and `network/`;
  every descriptor remains an exact readable file. Source follows those
  folders: `SYSTEM` owns peer `HARDWARE` and `APPLICATIONS` branches, while
  Drives stays inside Hardware and exposes the actual files beneath each
  volume. Private `@view/` keys stabilize UI identity but cannot invent a
  branch or replace a leaf's exact path. These folders are not Article kinds.
  Live sensor values stay on the Hardware API.
  Source supports Articles but is not a second knowledge graph or mutation
  authority.
- Obsidience is an ordinary directory on `/home`; `/var/lib/ai` is the Models
  storage location. `/home` and `/var/lib/ai` are separate Btrfs subvolume
  mounts on one shared filesystem and therefore share free space. There is no
  dedicated Obsidience partition or quota.
- A newly created immutable raw Source emits one `source.added` event after its
  bytes and ledger identity are durable. The event is one trigger on Darwin's
  existing Learn research Task. Darwin writes one cited synthesis through
  `source.handoff` into the physical `obsidience/evidence/inbox/`; that durable
  transition emits `source.inbox` for Alexandria's centralized Ingest Task. Duplicate
  capture or handoff emits nothing. Source never becomes accepted Knowledge or
  an intermediate Review object.

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
record reports Hyprland as the live compositor. The current session is
deliberately unlocked development state: secure locking, a native Polkit UI,
fullscreen HDR application behavior, fullscreen VRR, and WoW remain explicit
acceptance gates. Samsung desktop HDR is active only on `HDMI-A-1` through the
`hdr` preset and 10-bit scanout; a 225-nit SDR mapping restores the physically
accepted desktop appearance.

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
the typed command, updates Reader's ordinary `PanePlacement`, and broadcasts
one typed `pane.state` event. The one shell host owns one full-Surface
`PaneCanvas` per output; all registered panes are sibling items within their
canvas, and the accepted placement makes each pane visible on exactly one
Surface. Its native
input mask is the union of the open pane rectangles, leaving all uncovered
desktop space click-through. A canvas occupies the top layer only while one of
its module panes owns Hyprland keyboard focus; native application focus lowers
that canvas below ordinary windows and clears its active shortcut owner, while
the active module's local z-order keeps it above its module peers. The shared
module chrome is one exact three-logical-pixel border, with a subdued inactive
token and a stronger cyan token only for the pane that owns real keyboard
focus. `Alt+Tab` and `Alt+Shift+Tab` ask this same shell authority to cycle a
fresh deterministic ring of open native applications and undocked module panes
on the focused Surface. Native selection reuses the exact-address window
adapter; module selection reuses that Surface's canvas. Reader
consumes the typed selection, reads either
the exact Article through `/api/articles/{ref}` or the exact Source bytes
through `/api/source-files/{key}`, and renders the result in a translucent
native Qt Quick pane. The WebKit surface is
graph-only: the shell has no `?surface=reader` route, Reader web view, or
React Reader wrapper. This preserves one graph implementation and one generic
shell placement contract without Electron IPC or a second coordinator.

Reader also owns the native docking composition preserved from the archived
Electron interface. Knowledge defaults to its cyan left explorer and Source to
its violet right explorer; either can collapse into a 28-pixel rail, stack
above or below the other on one side, or detach back into its generic floating
pane. The primary shell owns one atomic `obsidience.pane-dock-layout.v1`
record. A docked explorer follows Reader across Surfaces, while its last
floating `PanePlacement` remains untouched for later detachment. Reader stays
the only Article and Source document surface.

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

Every pane, without exception, has one generic `PanePlacement`:

```text
pane_id + surface_id + local_rect + open + z_order + optional tile_bounds
```

Pane-specific cross-display bridges and pane-specific outer drag handlers are
forbidden. `PaneItem` and `PaneFrame` provide the one shared floating-pane
interaction path. A passive press observer activates and raises the whole pane
on the first primary click without consuming that click from its content.
Pointer dragging remains inside the current Surface;
`SurfaceLayout` applies one usable-bounds rule to preview, authoritative
commit, reopen, and transfer so shell chrome can never cover the title-bar
handle. The same authority owns one global Surface-local logical-pixel grid,
defaulting to 10 px. It rounds pane x, y, width, and height to that grid before
minimum-size and Surface-boundary clamps; those safety bounds win at an edge.
Settings > Workspace changes that single value, while pane Modules contain no
snap policy. The same `SurfaceLayout` owns proportional workspace tiling:
Samsung is 8 by 2, USB-C is 3 by 2, and DP-4 is 4 by 1 by default. Tiled panes
retain current integer `tile_bounds`; their complete chrome footprint has an
exact 5 logical px outer and inter-pane gap. The pure gap geometry adapts the
MIT Omarchy Windows Aero Snap pattern to arbitrary grids, but no compositor
plugin or second placement authority is loaded. From freeform, `Meta+Arrow`
selects the complete edge row or column. Once tiled, the same chord expands one
cell toward the arrow or, at that edge, collapses one cell from the opposite
edge. The sole no-shift Surface exception is an exhausted `Meta+Up` on a
one-row lower Surface, which enters the corresponding bottom-edge tile above;
every other exhausted edge remains unchanged. `Ctrl+Meta+Arrow` translates
existing tile bounds one cell without resizing and is a no-op for freeform
panes. Tiled bounds override pane-specific freeform minimum sizes; ordinary
freeform resizing keeps those limits. Manual title-bar drag snaps to the
nearest tile bounds; manual resize clears `tile_bounds`.
`Meta+Shift+Arrow` asks the shell host to transfer the active pane to the
nearest mapped Surface in that direction, preserving logical width and height;
only a dimension larger than the complete destination workspace is minimally
reduced to fit. The compositor adapter
captures all three physical shortcuts and calls the same bounded shell command.
The host writes one accepted placement revision and the destination Surface
renders it. An unmapped direction changes nothing. This deliberately uses no
held-pointer handoff, pane-drag lease, coordinator process, or pane-specific
transport.

Native application windows use the same grid semantics without pretending to
be QML PaneItems. Hyprland's supported `lua:obsidience` layout projects the
Surface's columns, rows, five-pixel gap formula, resize, translation, and
cross-Surface size preservation onto real compositor clients. The shortcut
path always asks the primary QML authority first and falls through only on its
exact `no_active_pane` result. The existing window adapter then binds the live
active address and revision immediately before one Hyprland command. All other
failures are terminal, so the shell never guesses whether a pane or native
window owns the action. Compositor border, rounding, and shadow tokens supply
the shared outer pane chrome; application content remains native and unmodified.
`Meta+Esc` follows that same ownership rule: dismiss the active QML pane first,
then close the exact active native client only when no QML pane owns the action.
It never sends a generic close to the Quickshell host.
Native applications use their own client-side title or tab-bar drag regions.
The client sends the standard Wayland interactive-move request, Hyprland 0.56.2
performs the move, and the native layout adopts the dropped grid cell when the
application is retiled on release. QML panes retain their shared direct
title-bar drag path and commit the same nearest Surface grid bounds on release.
Both paths infer the nearest one-or-more-cell span from the released footprint.
There is no modifier bind, global primary-button interception, synthetic title
bar, or application wrapper.

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

The Shell owns one semantic presentation palette. PaneFrame reads it directly;
small adapters flatten the same tokens into Hyprland and supported
application-native theme contracts such as Edge's Chromium policy. External
applications remain native compositor clients and are never embedded,
reparented, mirrored, or made dependent on the Shell host's lifetime.

Session locking must retain one Linux/PAM authority. The live default session
is explicitly unlocked development state; greetd authenticates login but does
not lock an active session. A secure release requires Hyprlock or another
accepted compositor lock, verified PAM behavior, one Polkit agent, privacy
covers for every Surface, input quarantine before the prompt, and one
successful-unlock event. The graph may decorate a lock surface but never
handles credentials or decides unlock.

```text
obsidience/harness/
  __init__.py
  __main__.py
  config.py
  interfaces/{api,cli}/
  {execution,knowledge,conversation,models,realtime,computer,web,host}/
  capabilities/<exact dotted Tool ID as directories>/<leaf>.py
```

Filesystem depth expresses stable responsibility rather than wrapper-only
folders. Prefer one meaningful subsystem level; use deeper structure only for a
real hierarchy such as the speech worker or a dotted Tool ID. Cross-subsystem
imports are explicit, package `__init__` files are side-effect-free, and generic
`utils`, `common`, and `core` junk drawers are not architecture.

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

A leaf Task must resolve a Runbook. A Runbook loads only its required Skills.
Each Skill resolves exactly one Tool, each leaf Tool resolves exactly one
Capability entrypoint in Source, and an Agent's checkout may narrow that set
further. Missing or malformed links fail closed; the model does not invent a
replacement Tool or procedure.

Runbooks are agent-specific synthesized objects. The shared Library therefore
contains Tasks and Tool+Skill pairs. Checking out a Tool includes its Skill.
Checking out a Task activates Generate -> Runbook so Darwin can synthesize the
procedure for that Task, Agent, and available Tool set.

## Agent structure

`Executive` is the user-facing role and the root Agent Article. A configured
personal name is merely identity data on that Article and never appears in
paths, protocols, object kinds, or architecture.

- **Executive** interprets the owner's request, chooses work, delegates,
  operates, and returns the verified result.
- **Alexandria** is the Curator. She owns Ingest, Curate, Merge, Link,
  Improve, and Archive and maintains the accepted wiki from bounded findings.
- **Darwin** is the Researcher. He owns Question, Learn, News, Model, and Generate.
- **Heimdall** is the Guardian. He owns Audit, Check, and independent acceptance
  and integrity checks.

Each Agent Article directly owns Architecture, Tools, Skills, Runbooks, Tasks,
Other Agents or Subagents, and Observations. There is no extra Agent wrapper
beneath Executive or any specialist.

Each named Agent has one canonical `kind: agent` Brain Article. A parallel
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
9. the exact model-facing `Immediate Observations` Article for an activation in
   the active Executive conversation.

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
The Executive's exact public dialogue is runtime state. One active conversation
uses an 80-turn in-memory deque backed by complete SQLite history; typed Chat and
Realtime speech append to that same ordered conversation. Enabling Realtime
rotates once to a fresh conversation, which remains active until the next enable
or the owner's explicit New conversation action. A final user transcript is
stored before execution, while an assistant turn is stored only after one
current execution produces a completed, nonempty public reply. Each assistant
row names its exact user row. Rotation never deletes prior SQLite rows.

That dialogue projects into one transient, unverified Knowledge Article named
`Immediate Observations`. The Article contains the newest cumulative Temporary
Observation summary, when present, followed by every exact completed pair after
its SQLite sequence boundary. It rides inside every Thinking Packet for that
conversation and its ref drives the same visible graph activation. It is never a
similarity-search candidate, executable authority, or durable claim. The current
owner request remains the Task binding and therefore is not duplicated into the
Article before execution.

The ordinary `observations/immediate/compact` Task runs at a configurable
60-to-90-percent model occupancy threshold, default 80 percent, or when the
owner presses Compact. Occupancy is measured against the active Task's selected
model; Compact uses its own authored resident Executive model to reduce the completed
Immediate prefix into one self-contained cumulative Temporary Observation of at
most 2,000 characters. Every compaction summary is a separate transient,
unverified Article; exact SQLite turns remain unchanged. At a real conversation
boundary, Alexandria's `observations/durable/promote` Task archives the exact
Temporary bundle in Source and stages only justified owner-review candidates.
Realtime defers the final compaction and event until Realtime ends so activation
latency is unchanged; promotion then waits for the executor to become idle.
Compaction and Source archival never create accepted durable Knowledge, and the
retired per-turn Maintain Temporary Observations activation does not run for
Executive Chat or Realtime.

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

Model and reasoning effort are per-Task execution settings. Automatic routing
selects responsive Gemma for Executive and the fully GPU-resident Qwen3.8 9B
Distill for specialist Agents. Hardware is a set of independent component
slots, not a global model profile. The fallback configuration places Gemma on
the RTX 4000 Ada and OmniParser on the RTX 4080 SUPER, while persisted Hardware
selections remain authoritative; the AMD iGPU remains the USB-C display/media
device. A Task lease displaces only overlapping GPU components and restores
the saved selection afterward. Model layers never spill to CPU.

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

- **Wiki:** Ingest, Query, Curate, Merge, Link, Improve, Archive, Audit,
  Check.
- **Research:** Question, Learn, News, Model. Learn accepts `source.added` as
  one trigger without becoming a Source-specific Task.
- **Generate:** Tool, Skill, Task, Runbook.
- **Observations:** Immediate, Temporary, and Durable lifecycle Tasks.

Curate performs one bounded scheduled inspection. When its Runbook detects a
high-signal maintenance lead, it may activate the exact accepted Merge or Link
Task; that Task independently confirms and completes its bounded outcome
through its own Runbook. Merge owns duplicate consolidation, while Link owns
missing Article relationships. Editorial actions such as copyedit, categorize,
split, and retitle remain branches within the Improve Runbook. Evidence-grounded routine
maintenance may be accepted automatically after deterministic validation.
Conflicts, destructive lifecycle actions,
authority changes, and high-risk effects require independent Guardian or owner
review. Review is a risk control, not the normal wiki-writing mechanism.

Review is serialized at the Article boundary. Only one unresolved proposal may
target an accepted Article, and updates or archives pin the exact accepted base
revision they were drafted from. A Task in `review` cannot be reactivated by
`task.create`. Redirect updates are decided before their dependent archive;
the Review projection disables a dependency-blocked decision instead of
letting an ordinary click fail or overwrite another complete replacement.
Review decision and execution finalization are order-independent: deciding all
proposals from an exact run while it is still finishing completes the Task and
the late `task.complete` result may not restore stale `review` state.
The accepted Task taxonomy also classifies the review object: a proposal staged
by the exact Link Task is a first-class Link review, while every other proposal
is an Article review. The harness records that class, derives it for older
proposals, and projects the exact added and removed Article links. The model and
UI may not guess or override it. Approval still applies the complete Article
replacement atomically, so Link reviews do not create a second mutation path.

Articles should be concise, self-contained, current, and pleasant to read.
Remove duplicated summaries, migration history, receipts, generic filler,
unresolved framework vocabulary, and facts that do not improve retrieval or
execution.

## Runtime and interface projections

The Python harness owns indexing, retrieval, activation, execution, scheduling,
Source integrity, and the run ledger. The Electron UI is a thin projection.

- **Graph** shows the real hierarchy and active retrieval path. Graph Settings
  also selects the one physical Surface for the whole graph; per-Agent
  placement is not part of this slice.
- **Reader** reads and edits Articles and opens linked Source files in the same
  center surface.
- **Knowledge explorer** shows the real vault hierarchy.
- **Source explorer** shows the exact bounded project filesystem: wiki
  Markdown, application code, stable System descriptors, and immutable raw
  sources. Its System branch follows the physical
  `state/system/{hardware,applications,network}` folders, and Drive nodes mount
  the exact files at the recorded storage locations. The UI may format a real
  folder label, but cannot invent its existence or contents; every leaf still
  carries its exact project-relative disk path. Selecting
  an Article cross-filters this one view to its Markdown and associated files;
  clicking any result opens the bytes at that exact displayed disk path in the
  same Reader. Tool Capability
  files carry their exact Article link, while internal Modules, interfaces, UI
  code, scripts, tests, and telemetry remain outside the graph.
- **Source checkout** assigns one subtree independently to any Agent as a
  Knowledge scope. It maps only to related accepted Articles and biases the
  existing five-Article fast retrieval. Source files never become graph nodes,
  Library assets, executable authority, or unconditional prompt content.
  The exact System scope maps to ADMECH Workstation; Hardware and Applications
  narrow that priority to ADMECH Hardware and ADMECH Software respectively.
- **Library** shows shared accepted Tasks and Tool+Skill pairs and their
  checkout state.
- **Tasks** shows only scheduled, event-triggered, or active Tasks, including
  inherited descendant scope.
- **Review** shows only material that actually requires a decision, with Link
  reviews visually distinct from ordinary Article reviews and their exact
  relationship delta visible before approval.
- **Applications** lists real desktop entries and uses PackageKit through the
  system Polkit boundary for native package search, install, and removal. It is
  an ordinary pane; the far-left bar button remains a separate transient
  Start-style launcher for opening applications.
- **Terminal** mirrors the current shared development tmux window without
  owning or renaming it.
- **Settings** is one sectioned shell pane. Graph owns its first section and
  continues to command the canonical Three.js store. Input projects the live
  Mouse and Keyboard state. Workspace owns shared pane behavior, beginning with
  the global 10 px pane-grid selector. No section is a separate pane or bar
  item.

No UI module may carry a copied claim catalog, static semantic ontology, second
scheduler, second memory store, hidden activation path, or duplicated Agent
subject/name dictionary.

## Realtime Executive

The Realtime button owns one leaf Task, `Tasks/executive/realtime`, for the
complete live session. Its ordinary `model` and `reasoning_effort` fields are
the only reasoning selection. Pipecat and NVIDIA NeMo provide speech transport;
Nemotron transcribes on the RTX 4080 and Pocket speaks on CPU. No second Agent,
planner, verifier, Tool authority, or Realtime-specific model selector exists.
Pipecat's upstream `LocalAudioTransport` owns the selected local input and
output. Obsidience does not add a browser audio client, audio WebSocket, or
custom capture/playback processor.
Realtime ready wakes the OBSBOT camera through its official SDK and Realtime off
sleeps it. While Realtime is on, that SDK command disables the camera's 120-second
no-video auto-sleep timer; off restores it. The camera's real hardware state owns
its microphone state.

Each final transcript executes the Realtime Task through the ordinary activation
compiler, model lease, Tool path, ledger, and graph activity. Speech onset
cancels Pocket playback and the in-flight Task generation. Backchannels may be
filtered without granting semantic authority to the speech layer.
NeMo's serialized `UserStoppedSpeaking` edge owns the persistent user-speaking
state; a visible final transcript never substitutes for that turn boundary.
The final transcript and final public reply also project into the same Executive
Chat conversation used by typed input. Canceled, failed, blocked, interrupted,
or generation-stale output never becomes an assistant conversation row.

At session start, Realtime validates and freezes the selected microphone,
speaker, and Pocket voice. Hardware changes made while it runs are saved for
later and never mutate the active audio graph.

While Realtime is active, autonomous specialist schedules and triggers remain
pending before claim. Only `task.create` from the exact Realtime Task can mark
a peer specialist Task as an explicit delegation exception. This provenance
does not create hierarchy and cannot be supplied by caller arguments.

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
