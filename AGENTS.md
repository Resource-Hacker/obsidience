# Obsidience Development Contract

Read `DESIGN.md` before changing the harness. Obsidience is a standalone,
graph-native agent harness optimized first for low-parameter models running on
local consumer hardware.

## Mission

Obsidience instantiates Andrej Karpathy's LLM-wiki pattern as the durable brain
of the agent fleet: immutable raw Source, an agent-maintained Markdown wiki,
and this schema remain ordinary files in one project tree. Its fast hybrid
retrieval and typed graph expansion compile each request
into a small, complete activation packet. The model should receive the objective,
procedure, knowledge, Tool interfaces, constraints, and acceptance conditions it
needs instead of being expected to reconstruct the system from a large prompt.

If required knowledge is missing, the Researcher acquires it and hands a bounded
finding to the Curator. If a reusable Capability or procedure is missing, the
Generate Task family creates a reviewable Tool, Skill, Task, or Runbook only
after a real implementation or outcome contract exists.

## Canonical ontology

- Every graph node is an Article. A parent Article is an index and condensation
  of its descendants; a leaf Article carries the complete local subject.
- `Knowledge` supplies facts, context, constraints, and explanations.
- `Task` states a reusable outcome and acceptance condition. It never encodes a
  procedure merely to create hierarchy.
- `Runbook` states the ordered or branching procedure for a Task.
- `Tool` is the graph-facing executable interface to one real Capability, with
  explicit arguments, effects, permissions, and failures. Every accepted leaf
  Tool has exactly one paired Skill, one `capability:<exact Tool title>` binding,
  and one singular Source-linked entrypoint at
  `obsidience/harness/capabilities/<dotted Tool segments>/<leaf>.py`.
- Before writing a Tool implementation, prefer an existing maintained modular
  open-source package, script, executable, or extension. Register or link the
  real implementation and provenance in Source; keep Obsidience code to the
  thin typed, graph-authorized, bounded, and verified adapter that is actually
  unique to this harness. Do not recreate an available Capability.
- `Capability` is executable machinery behind a Tool. Its code and provenance
  live in Source; it is not an Article kind, checkout, or Task authority.
- `Module` is one top-level Obsidience product component with its own physical
  folder and bounded contract, such as `Harness`, `Shell`, `UI`, `Vault`, or
  `Tests`.
  Harness folders such as execution, retrieval, models, and realtime are
  subsystems of the Harness Module, not additional Modules. A Module may serve
  a Capability adapter, but it is never a Capability, Tool, checkout, or
  model-facing authority.
- The filesystem package hierarchy is the code-side projection of function just
  as Article hierarchy is the knowledge-side projection of meaning. Keep it
  shallow, group real logical subsystems, and make import direction explicit.
  There is no first-party folder named `modules`.
- The Harness map is `interfaces/{api,cli}`, direct
  `{config,execution,knowledge,conversation,models,realtime,computer,web,host}`
  subsystems, and `capabilities/` mirroring exact dotted Tool IDs. Prefer one
  meaningful subsystem level; go deeper only for true hierarchy such as the
  speech worker and dotted Tool IDs. Cross-subsystem
  imports are explicit, every `__init__` is side-effect-free, and generic
  `utils`, `common`, or `core` junk drawers are forbidden.
- `Skill` teaches exactly one Tool. A Tool and its Skill are checked out
  together.
- `Agent` is an accountable executor that owns checked-out Tool+Skill pairs,
  Runbooks, Tasks, and Observations.
- The Tasks pane is the runtime projection for scheduled, event-triggered, or
  currently active Tasks. Task remains the only work object.
- `Source` is the one read-only filesystem view beside the graph. Every leaf
  retains the exact project-relative path of a real file:
  `obsidience/vault/` holds wiki Articles, `obsidience/evidence/` holds
  immutable raw material, `obsidience/harness/`, `obsidience/shell/`,
  `obsidience/ui/`, `obsidience/scripts/`, and `obsidience/tests/` hold
  application code, and
  `obsidience/state/system/` is the physical System inventory:
  `hardware/` contains Compute, Drives, and Devices; `applications/` contains
  installed or explicitly not-yet-integrated application records; and
  `network/` contains connection records. Clicking a leaf opens those exact
  bytes. The Source tree follows these real folders and real storage locations,
  never a renderer-only taxonomy. `SYSTEM > HARDWARE` and
  `SYSTEM > APPLICATIONS` are peers; Drives remains under Hardware and exposes
  exact files beneath its volumes. Private `@view/` keys stabilize UI identity
  only; they never replace a leaf's exact path or become ontology kinds.
  Live utilization stays on the Hardware API rather than masquerading as file
  content. Source may support Knowledge but cannot grant itself trust, become
  a graph node, or become a second vault.
- Obsidience is an ordinary directory backed by `/home`, while `/var/lib/ai`
  is the Models storage location. `/home` and `/var/lib/ai` are separate Btrfs
  subvolume mounts on one shared filesystem and use the same free-space pool.
  Obsidience has no dedicated partition or quota.
- Creating one new immutable raw Source object through the managed Source
  boundary emits exactly one ordinary `source.added` event. That event is one
  trigger on Darwin's existing Learn research Task; it never creates a
  Source-specific Task. Darwin drops at most one cited synthesis through
  `source.handoff` into the physical `obsidience/evidence/inbox/`. That durable
  write emits `source.inbox`, whose sole subscriber is Alexandria's centralized
  Ingest Task. Duplicate capture or handoff emits no event. Source writes never
  create Knowledge or an intermediate Review object.
- A Source-tree checkout is plain Agent scope metadata, not a Library checkout
  or graph edge. It maps the selected subtree to related accepted Knowledge
  Articles and only prioritizes those Articles inside the ordinary bounded
  fast search. It never attaches raw files wholesale, grants Tool authority,
  creates a Task or Runbook, or turns transient System telemetry into durable
  Knowledge.
- Checking out exact `obsidience/state/system` supplies the accepted ADMECH
  Workstation branch through ordinary retrieval. Hardware narrows that scope
  to ADMECH Hardware; Applications narrows it to ADMECH Software. This adds
  Knowledge priority only and never attaches Source bytes or executable
  authority.
- Obsidience is the harness and developing desktop shell. Its first replacement
  target is `plasmashell`, while KWin remains the compositor boundary. It is
  neither the computer, the kernel, nor a System32 analogue: its actual code is
  visible on the System Volume and its Applications record describes the shell
  role. It may replace more KDE Plasma/GNOME/Windows desktop functions and eventually
  become an OS environment. That direction adds no ontology kind and grants no
  fictional capability: each replacement arrives as one real, modular System
  or interface implementation with an explicit boundary, rollback, and
  acceptance test. Reuse Linux itself for kernel, drivers, filesystems, systemd,
  udev, PipeWire/WirePlumber, NetworkManager, and compositor protocols; do not
  recreate operating-system plumbing inside the Harness. The first desktop
  cutover may retain KWin as the compositor while Obsidience replaces
  `plasmashell`, the panel, and workspace surface. The native `Shell` Module now
  provides the first bounded slice: the default Obsidience KWin login session,
  one Samsung-only Obsidience Stage matching the current background and identity
  chrome, and read-only KWin state. It reserves no panel area and creates no
  placeholder panel. `plasmashell` stays disabled so it cannot compete for shell ownership;
  the independent terminal is the recovery path. The Electron development UI
  is disabled on `native-shell` and retained only on
  `archive/electron-20260828`. The native Samsung, USB-C, and DP-4 hosts all
  instantiate the same registry for Chat, Library, Tasks, Reviews, Reader,
  Knowledge, Source, Models, Hardware, Camera, Settings, Applications,
  Terminal, and Displays. The far-left bar control remains the transient
  Start-style launcher. Its menu is one shared button-anchored shell popup on
  every Surface. The Obsidience bar is the sole side-Surface bar; legacy tint2
  panels must not run or be restored by display wake repair. Applications is
  the ordinary movable software-management pane backed by PackageKit/Polkit.
  One shared placement record transfers and
  resizes every pane. The
  project target is a full `plasmashell`
  replacement on unmodified upstream KWin. Treat each physical display as one
  runtime Surface: Samsung is KWin/Wayland, USB-C is Xorg `:2.0`, and DP-4 is
  Xorg `:2.1`. Surface is not an Article kind or Capability. Every pane uses the
  same `pane_id + surface_id + local_rect + open + z_order` placement contract;
  never create a Reader-specific or pane-specific display bridge. Every
  floating pane is wrapped by the shared `PaneItem` and `PaneFrame`; pane
  Modules must not implement their own outer movement or focus shim. The shared
  passive press observer must activate and raise a pane on its first primary
  click without consuming that click from terminal or control content. Pointer dragging is
  local to the current Surface and `SurfaceLayout` clamps every preview,
  commit, reopen, and transfer to the shared usable bounds so the title-bar
  handle cannot be stranded behind shell chrome. `SurfaceLayout` also owns one
  global logical-pixel pane grid. Its default is 10 px, it snaps pane position
  and size before safety clamping, and Settings > Workspace is its only human
  control; individual pane Modules must never implement their own snap logic.
  `Meta+Shift+Arrow` moves the active pane to the nearest mapped Surface in
  that direction through one primary-shell placement revision. KWin owns the
  physical shortcut on Samsung. On USB-C and DP-4, the existing single-owner
  input router consumes that exact chord before XTest forwarding and calls the
  same bounded shell command client. The primary shell remains the only
  placement writer. No held-pointer transfer, pane-drag lease, coordinator
  service, Openbox binding, or pane-specific bridge is permitted for this state
  change. An unmapped direction is a no-op.
  Only the active Surface displays its cursor; inactive Surface cursors stay hidden.
  Preserve Samsung-only KWin ownership and VRR isolation.
  KWin and KScreenLocker remain the sole session-lock and PAM authority.
  One `graph_surface_id` in the existing Surface layout selects Samsung, USB-C,
  or DP-4 for the whole graph; per-Agent placement is deferred. Obsidience
  keeps the top-left Obsidience identity mark on that selected Surface and
  centers the Executive root at the selected Surface's exact midpoint.
  projects one lock event to all three Surfaces. The selected Surface shows the
  canonical graph, each nonselected side Surface is an opaque input-empty
  privacy cover, and Samsung retains KDE's compositor-enforced stock greeter
  over a real graph-rendering wallpaper when selected. The root input router
  rejects every side-Surface lease. Unlock is accepted only from KScreenLocker
  and never restores prior side ownership. Settings is one sectioned pane;
  Graph is its first section, Workspace owns shared pane behavior, and neither
  has a standalone bar button.

Only these canonical kinds belong in accepted frontmatter: `knowledge`,
`task`, `runbook`, `tool`, `skill`, and `agent`.

## Hierarchy law

Prefer one meaningful level beneath a family. Add depth only when a parent and
every child name real, independently explainable outcomes. Observations is the
reference exception: Immediate, Temporary, and Durable are distinct lifecycle
scopes, and their children are distinct operations. Procedural stages such as collect,
screen, analyze, and verify belong in a Runbook unless they are independently
queueable outcomes with their own acceptance conditions.

Every selected descendant includes its ancestor Articles for context. Selecting
a parent Task includes all descendant Tasks unless that activation explicitly
excludes one. Cycles are forbidden. One Task may activate another exact
accepted Task through `task.create`; activation provenance records causation
and never creates hierarchy. Only an explicit `subtasks` edge creates
hierarchy. The target keeps its authored taxonomy placement.

A Task may declare an ordered `triggers` list and remains the same reusable
outcome no matter which event, schedule, manual activation, or peer Task starts
it. Event names are runtime activation routes, not Task kinds or hierarchy.
The singular `event` field is legacy read compatibility only; new and edited
Task Articles use `triggers`.

## Agent structure

- `Executive` is the user-facing role and the root Agent Brain Article. A
  configured personal name is identity data, never an ontology term, path,
  type, or protocol.
- Alexandria is the Curator. She owns Ingest, Curate, Merge, Link,
  Improve, and Archive and receives Darwin's bounded findings in her Inbox.
- Darwin is the Researcher. He owns Question, Learn, News, Model, and Generate.
- Heimdall is the Guardian. He owns Audit, Check, and independent acceptance.
- Library is a passive projection of shared accepted Tasks and Tool+Skill pairs.
  It is not an Agent and cannot be a checkout target.

The Executive and specialist Agent Articles use the same direct subjects:
Architecture, Tools, Skills, Runbooks, Tasks, Other Agents or Subagents, and
Observations. Specialist domain subjects may be added when they are genuine
Knowledge indexes.

Each named Agent has exactly one canonical `kind: agent` Brain Article. A
parallel Knowledge role charter for that same Agent is a duplicate shadow, not
a second subject: Merge absorbs its unique content and meaningful relationships
into the Agent Article, redirects inbound references, and stages the ordinary
shadow Article for archival.

## Activation contract

One executor handles live text, live voice, manual Tasks, schedules, and event
triggers. For every leaf Task it must compile one visible Thinking Packet in
this order:

1. the exact Agent Identity Article;
2. the selected Task Article and acceptance conditions;
3. the immutable runtime Objective for this activation;
4. authorized Tool Articles;
5. their exact paired Skill Articles;
6. applicable Runbook Articles;
7. typed bindings and exclusions that are not the Objective or controller
   provenance;
8. up to five accepted Knowledge Articles from the shared fast hybrid search,
   preserving three direct hits when available and adding at most two direct
   graph neighbors;
9. the exact model-facing `Immediate Observations` Article when the activation
   belongs to the active Executive conversation.

The fast search uses lexical+dense weighted RRF with no generative expansion,
cross-encoder, or elapsed-time cap. Search may nominate a Task candidate, but
the harness must resolve one exact accepted Task before its authored edges can
authorize Runbook, Skills, or Tools. The packet is semantically labeled and
token-budgeted. The immutable Objective is the exact bound owner request when
one exists; otherwise it is the deterministic selected Task title followed by
the ordered Runbook titles. That one value drives retrieval, graph activity,
the provider packet, and the run ledger. Request, source, event, and response
contract metadata are not duplicated into Bindings. Objective is runtime data,
not an Article kind. The same typed
search results may fill Knowledge and nominate a Task, but required packet
slots still come only from the selected Task's authored graph edges. The fast
retrieval path is prewarmed before the API accepts its first activation. Do not
flatten all text into an undifferentiated prompt.
Definitions never carry operational state;
runtime state belongs to Tasks in execution and the run ledger.
The Executive's exact public conversation is runtime state. Typed Chat and
Realtime speech share one active 80-turn hot deque backed by complete SQLite
history. Enabling Realtime rotates once to a fresh conversation; that identity
remains fixed until Realtime is enabled again or the owner selects New
conversation. Persist the final user turn before execution and persist an
assistant turn only for a current, completed, nonempty public reply linked to
that exact user turn.

Project the active conversation into one transient, unverified Knowledge Article
named `Immediate Observations`. It contains the latest cumulative Temporary
Observation, if any, plus every exact completed pair after that compaction
boundary. The Article rides inside the Thinking Packet and its exact ref rides
the visible graph activation path; it never participates in similarity retrieval
or grants Task, Runbook, Skill, Tool, or Policy authority. The current request
remains the Task binding rather than being duplicated into the Article.

At the configurable 60-to-90-percent occupancy threshold, 80 percent by
default, issue the ordinary `observations/immediate/compact` Task. Measure
occupancy against the active Task's selected model; Compact itself uses its
authored resident Executive model to replace the completed Immediate prefix with one
cumulative Temporary Observation of at most 2,000 characters. Each compaction
summary remains a separate transient, unverified Article while exact SQLite rows
remain unchanged. At a real conversation boundary, Alexandria's ordinary
`observations/durable/promote` Task archives the exact Temporary bundle in
Source and stages only justified owner-review candidates. Realtime defers this
final compaction and event until Realtime ends so startup latency is unchanged;
the Task then waits for the executor to become idle. Compaction and Source
archival never create accepted durable Knowledge. Do not emit the superseded
per-turn Maintain Temporary Observations activation for Executive Chat or
Realtime.
Task reasoning remains private and uses the selected per-Task effort. The
provider must constrain every public executor response to one JSON action
object; retain bounded finish and parse diagnostics in the run ledger instead
of storing complete malformed model output or adding Task-specific parsers.

Model choice and reasoning effort are per-Task execution settings. `auto`
routes Executive to responsive Gemma and specialist Agents to the fully
GPU-resident Qwen3.8 9B Distill. Hardware residency is modular: each GPU owns
one selected component, and a Task lease displaces only components on the GPUs
that Task needs before restoring the saved Hardware selection. The fallback
configuration is Gemma on the RTX 4000 Ada and OmniParser on the RTX 4080 SUPER;
persisted user selections are authoritative. No model layer may spill to CPU.
Muse may run text-only on the RTX 4000 or use both GPUs for vision plus DFlash;
the known-invalid RTX 4080-only layout is rejected. Models contains only Task
reasoning models.
When OmniParser is not the selected RTX 4080 component, the marker
`%t/obsidience-perception-enabled` is absent and the paired systemd conditions
must keep `jarvis-perception.socket` and `jarvis-perception.service` inactive;
selecting OmniParser creates the marker before either unit starts.

The real-time Executive is the ordinary `Tasks/executive/realtime` Task. Its
existing `model` and `reasoning_effort` fields are the only reasoning selection.
Fixed Pipecat and NVIDIA NeMo transport streams the Hardware-selected microphone
through Nemotron Speech Streaming EN 0.6B on the RTX 4080, while Pocket TTS runs
on CPU. Use Pipecat's upstream `LocalAudioTransport` with process-scoped Pulse
routing; do not add a browser audio client, audio WebSocket, or custom
capture/playback processor. Each final transcript executes through the normal
Task activation packet and Tool path. Speech onset cancels playback and the
in-flight Task without closing the microphone. The speech runtime is not an
Agent, planner, Tool owner, memory, policy, verifier, or second reasoning path.
Pipecat capture must emit VAD frames without creating generic user-turn
interruptions; `NeMoTurnTakingService` is the sole turn/interruption owner. The
OBSBOT AEC route uses Silero confidence `0.2` with minimum volume `0.0`; the
bounded NeMo turn-taking adapter treats a nonempty recognized transcript as a
speech start when Silero misses AEC-conditioned speech and supplies the same
1.2-second stop edge through NeMo's existing VAD contract. The adapter also
resets the streaming ASR state upstream and serializes the canonical
`UserStoppedSpeaking` edge; `HEARD` never substitutes for that edge. Realtime
state exposes NeMo's user-speaking state and the latest typed partial or final
transcript, and the visible final is the exact normalized text submitted to the
Task.
Realtime ready must wake the OBSBOT camera through its official SDK; Realtime off
must sleep it. While Realtime is on, the same SDK command disables the camera's
120-second no-video auto-sleep timer; off restores it. The camera's real hardware
state owns its microphone state. Reassert the OBSBOT UAC microphone enable after
camera wake even when the SDK already reports enabled: the Tiny 2 Lite can otherwise
remain digitally silent. Do not substitute custom wake frames or a keepalive.

## Knowledge maintenance

- Learn may be activated by `source.added`; Darwin researches the exact Source
  and writes one cited synthesis to the physical Source Inbox.
- Ingest is activated only by `source.inbox` and transforms that handoff plus
  its cited raw Sources into the smallest coherent set of maintained wiki
  Article creates or updates.
- Curate runs a bounded scheduled inspection. Its Runbook may use `task.create`
  to activate the exact accepted Merge or Link Task. Each confirms its own
  lead and performs only its bounded outcome through its own Runbook.
- The scheduler claims a due Task before it waits for the executor semaphore;
  later ticks must never queue a second copy of that same activation.
- A restart-interrupted event Task retains its bound activation and FIFO and
  returns to `pending`, including an exact older `failed` interruption marker.
  Ordinary provider, model, Tool, and acceptance failures remain `failed` for
  explicit resolution. Merge and Link candidate occurrences are deduplicated
  by their exact destination Task plus sorted Article refs; a changed content
  evidence hash never manufactures another activation for the same pair.
- A Task awaiting an owner decision is not idle. `task.create` must not rerun,
  overwrite, or queue another occurrence of that Task while it is in `review`.
- Review decision and execution finalization are order-independent. If the owner
  decides every proposal from an exact run while that run is still finishing,
  finalization completes the Task and must not recreate stale `review` state.
- A deferred `task.create` reports the destination's state without changing the
  caller. A Task may enter `review` only when that exact execution staged an
  unresolved proposal or reached an explicit acceptance gate authored on the
  Task; proposal-less Curate deferrals complete honestly.
- One accepted Article may have only one unresolved proposal. Update and
  archive proposals pin the accepted base revision; a stale or overlapping
  proposal fails closed. Review lists dependency-safe updates before archives
  and disables an archive until its canonical-union update and every accepted
  inbound-reference redirect are accepted.
  Exact backlinks come from graph resolution in `vault.read`, never from search;
  Merge cannot complete review while an archive lacks redirect proposals.
- Merge confirms and consolidates one exact duplicate candidate set.
- Link confirms and adds one missing, meaningful Article relationship.
  Proposals staged by the exact accepted Link Task are first-class Link review
  objects. The harness derives that class from Task taxonomy and exposes the
  exact added and removed Article links; neither the model nor UI may author or
  infer it. Approval remains one atomic Article replacement through the normal
  review authority.
- Improve handles copyediting, categorization, expansion, retitling, and
  splitting as Runbook branches.
- Archive handles one stale or superseded Article. Audit covers evidence,
  contradictions, and graph links; Check covers deterministic harness health.
- Research contains Question, Learn, News, and Model. Model is an ordinary
  `model.added` event Task that inspects an exact artifact, registers its
  immutable Source manifest, benchmarks valid hardware layouts, and applies
  only a measured configuration. Framing, discovery, collection, screening,
  assessment, extraction, analysis, and verification are procedure.
- Generate contains Tool, Skill, Task, and Runbook. Generate → Task authors
  reusable Task definitions with `vault.propose`; `task.create` only activates
  an exact accepted Task and never authors a Library definition.
- Observations contains Immediate, Temporary, and Durable lifecycle families.

Model research uses four executable Tool+Skill pairs:
`model.inspect`, `model.source`, `model.benchmark`, and `model.configure`.
Their Source records describe and attest the external model blobs without
copying multi-gigabyte weights into the project. The Models pane is the human
inventory and benchmark surface; Hardware remains the saved residency surface.
Models contains Task reasoning models only. Hardware shows the fixed Pipecat,
NeMo, Nemotron, and CPU Pocket speech runtime and owns the Star Trek Computer,
HAL, or Ultron voice selection. Their raw training clips are not Source and are
never runtime inputs.
Every text-generating model benchmark is a standalone per-model comparison with
the exact same prompt, a 256-token ceiling, temperature zero where the runtime
supports it, one discarded warmup, and three measured samples. Primary TTFT is
the median request-dispatch-to-first-public-output time. Primary end-to-end
tok/s is the total actual completion tokens divided by the total complete
request wall time across those samples, including TTFT and prompt processing.
Frame, interruption, audio, and startup timings remain secondary diagnostics
and must never replace either primary field or be presented as a model-to-model
result.
Each Hardware card also projects live read-only sensors. CPU reports system
RAM, utilization, temperature, clocks, load, and topology; the AMD iGPU reports
GPU memory, utilization, media load, temperature, power, and clocks; NVIDIA
cards report VRAM, compute and engine utilization, thermals, power, clocks,
fan, power state, and PCIe link. Read these from live local interfaces and do
not add a second monitoring daemon or treat telemetry as assignment authority.
Hardware owns the exact microphone and speaker selected for the next Realtime
session plus the preferred physical camera used by the Camera pane and Camera Tools.
Project live PipeWire audio and physical V4L2 cameras without changing
system-wide defaults. The resizable Camera pane is video-only, opens when the
physical camera is enabled, and releases every browser video track when closed;
it must never request or own audio. TFT ADB is an Agent video feed, not a camera,
and must never appear in or consume the Camera preference. Realtime freezes
microphone, speaker, and Pocket voice at start.

Accepted Articles must be concise, concrete, human-readable, and useful to
retrieval. Remove filler, duplicate summaries, historical scaffolding, fictional
Tool bindings, generic hierarchy edges, and framework-specific vocabulary.

## Development workflow

- Project root: `/home/wissenschafter/Projects/obsidience`.
- Development harness: `obsidience-harness-dev.service` on `127.0.0.1:8765`.
- Development UI: `obsidience-ui-usbc-dev.service` on isolated USB-C Xorg `:2`.
- Use `obsidience/scripts/dev.sh` for an interactive combined launch.
- The UI is a thin projection of the live graph. It must not invent semantic
  kinds, static claim catalogs, trust rules, or a second scheduler.
- `/api/graph.navigation` is the sole UI contract for Agent/Library card names,
  roles, generated subject Article titles, and subject parentage. UI code may
  route by those stable IDs but must never rebuild their labels from paths or
  keep a parallel subject dictionary.
- Generated namespace indexes use human-facing titles with an uppercase first
  letter. Do not rewrite terminal callable Tool identifiers; `vault.read` is an
  exact executable name, while its parent index is `Vault`.
- The graph animation must represent the exact packet path for every Task
  activation and remain passive when no work is being resolved. Automatic
  speed follows measured fast-search duration without a time clamp; its
  checkbox yields to the per-graph Animation speed slider when disabled.
- The Reader is the single Article and Source viewer. Knowledge and Source
  explorers are dockable views, not separate truth stores.
- External applications remain native KWin/Openbox clients, never PaneItems or
  embedded mirrors. One Shell palette feeds PaneFrame and bounded native theme
  adapters; application content remains owned by the application.
- Reader docking has one primary-owned atomic layout: Knowledge defaults left,
  Source defaults right, same-side explorers stack evenly, and collapsed
  explorers use a narrow rail. Docked explorers follow Reader between Surfaces;
  detached explorers resume their own generic PanePlacement. Never add a web
  Reader, second document loader, or display-transfer path for docking.
- The native Terminal owns the `obsidience-ui` tmux session view and window
  sizing. Its fixed readable font and viewport follow the pane, and tmux uses
  the largest attached client so the full pane reflows without letterboxing.
  DP-4 is a passive mirror and must not constrain Obsidience's terminal size.

After every project change, rebuild as needed and restart the harness plus each
affected native shell host so the owner can test the exact current state.
Verify the API and the actual USB-C display, not only command exit codes.

## Required validation

Before handoff:

1. run the vault validator and require zero broken load-bearing edges;
2. compile all Python source files;
3. run `pnpm --dir obsidience/ui typecheck` and
   `pnpm --dir obsidience/ui build`;
4. confirm Source integrity and the exact Tool-to-Skill-to-Capability pairing;
5. restart the harness and affected native shell services;
6. verify `/api/status`, `/api/graph`, `/api/tasks`, and the USB-C UI;
7. ensure accepted graph text contains no stale framework architecture or Tool
   claim without its exact Capability binding and singular entrypoint.

Realtime is one long-lived Executive Task at `Tasks/executive/realtime`, not a
second harness or a Task per Tool call. Its ordinary `model` field selects the
model; no Realtime-specific model mode, resolver, planner, or verifier exists.
The fixed Pipecat/NeMo speech transport supplies live audio and interruption;
the Task-selected model remains the sole reasoning model.

While that Task runs, the scheduler must leave autonomous non-Executive Tasks
pending before claim. The only exception is a real peer Task created by
`task.create` from the exact Realtime Task, carrying harness-authored
`realtime_delegate` and creator provenance. Tool calls themselves never create
Tasks, and causal order never creates task hierarchy.

Create a timestamped rollback copy before broad or destructive changes. Keep
unrelated user work intact.
