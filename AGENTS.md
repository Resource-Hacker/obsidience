# Obsidience Development Contract

Use the local `karpathy-guidelines` skill every turn, as requested by the owner.

Read `DESIGN.md` before changing the harness. Obsidience is a standalone,
graph-native agent harness optimized first for low-parameter models running on
local consumer hardware.

Before shell or desktop integration work, use the local `check-omarchy` skill.
Before writing generic infrastructure, use `reuse-upstream` to check installed
plumbing, official documentation, and maintained GitHub implementations. Import
only the narrow compatible dependency or pattern; a useful reference is not
automatically adopted code.

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
  `{config,execution,knowledge,conversation,models,realtime,computer,web,host,connections}`
  subsystems, and `capabilities/` mirroring exact dotted Tool IDs. Prefer one
  meaningful subsystem level; go deeper only for true hierarchy such as the
  speech worker and dotted Tool IDs. Cross-subsystem
  imports are explicit, every `__init__` is side-effect-free, and generic
  `utils`, `common`, or `core` junk drawers are forbidden.
- `Skill` teaches exactly one Tool. A callable `<tool.id>` is defined by
  `Tools/<tool.id>` and its single `Skills/<tool.id>` Article titled
  `Using <tool.id>` with a singular `tool: [[Tools/<tool.id>]]` edge. Tool and
  Skill remain one shared Library pair. A Task's applicable accepted Runbook
  selects the required Skills and their Tools; Agent Articles never duplicate
  those dependencies or Skill prose. Multi-Tool order belongs in Runbooks.
- `Agent` is an accountable executor with assigned Tasks, its identity,
  Knowledge, and Observations. `Agent.tasks` is the only manual work assignment;
  Tools, Skills, and Runbooks are derived from the assigned Tasks, never
  independently granted through Agent metadata.
- Library Observations groups stay shallow: Tasks contains Compact and Promote
  directly; Tools and Skills contain the existing observation operations
  directly, without Immediate, Temporary, or Durable wrapper nodes. One shared
  callable namespace rule supplies Tool and Skill parent membership in both
  graph and Reader. Preserve the exact callable IDs, paired Skill references,
  Task file identities, triggers, assignments and runtime history. The actual
  Agent Immediate and Temporary Observation stores retain their distinct roles.
- The Tasks pane is the runtime projection for scheduled, event-triggered, or
  currently active Tasks. Task remains the only work object.
- Connections are third-party access configuration; optional Feeds select raw
  data from one Connection. They are not Article kinds, Tools, or Tasks. The
  Settings pane owns Connection access setup, and the standalone Feeds pane
  owns feed browsing and collection settings; the Harness owns
  one lifecycle-bound intake loop. Credential-free definitions live in
  `obsidience/state/connections.json`, while cursors, item versions, and check
  results use the existing Index. These records are distinct from host network
  interface inventory in `state/system/hardware/network.json`.
- RSS/Atom collection captures each complete provider item into immutable
  Source through `source.ingest_source`, using `feed://` identity and retaining
  the reporting URL inside the raw material. It never labels an RSS excerpt as
  a fetched reporting article. Source and its Feed/destination receipt commit before event dispatch;
  admission and the Darwin Distill FIFO receipt commit together; Darwin hands its synthesis to Alexandria's existing
  Inbox/Ingest path. Conditional HTTP validators advance only after the selected
  items are durable. Unchanged items cannot enqueue repeated research.
- A `source.added` Learn or Distill activation is bound to its exact Source UUID,
  citation, event key, and content hash. Ambient window titles and temporary
  Observations cannot supply its research topic. The ordinary visible
  `source.read` Tool must read that Source completely before research Tools,
  handoff, or successful completion are admitted. Handoff must cite the
  activating Source; completion requires that handoff or an explicit cited
  no-change outcome. Read failures remain reportable as failures. Source bytes
  stay untrusted Tool evidence, never injected Task instructions.
- Each Feed selects an existing Knowledge container through `destination_ref`.
  Multiple Feeds may share a destination. There is no Feeds graph root or
  automatic feed-specific node. `News & Research/Top Stories` is an ordinary
  owner-selected Knowledge destination.
  New bindings default an otherwise unset Article Auto-curate policy to true;
  existing explicit or inherited choices remain authoritative. The graph and
  Connections use the same Article field, never a second Feed permission.
  Destination changes apply to newly captured items without moving history.
- Feed items activate Darwin's `Tasks/research/distill`. Darwin reads the
  complete item and only its exact reporting page when needed, then drops one
  cited distillation through `source.handoff` into Alexandria's physical Inbox.
  Ingest preserves that complete handoff and compiles native OKF provenance into
  the selected node through the existing proposal owner. Auto-curate publishes
  eligible Articles automatically; disabled nodes retain Review. Both immediate
  publication and later approval revalidate the current destination and Source
  lineage. Feeds use their own retention limits and do not impose a fixed 26-hour expiry.
- Each Feed owns `max_active_articles` (1–1000, default 10), separate from
  `item_limit` (1–30 publisher entries checked per poll). Count only attested
  Inbox-to-Feed publications across destinations, never every Article in the
  selected node. Owner moves or copies remain counted and protected from
  retirement. Darwin's handoff triggers Ingest's atomic incoming-plus-archive
  Review group; explicit policy saves also reconcile quiet Feeds. All affected
  Article permissions, current policy, exact bases and surviving inbound links
  are checked before publication. Blocked retirement holds the incoming item.
  Retain complete Articles and Sources through native OKF archival; do not
  reinterpret `stale_after`, add a collector writer or create another scheduler.
  Large reviewed reductions retain continuation in the existing Review journal
  before settling the Task. Recover the exact successor and held Inbox after a
  restart or policy save; recheck current policy and accepted item versions.
- Feed `distill_instructions` is optional owner configuration, limited to 500
  characters and snapshotted in the atomic Feed receipt. Admit it as explicitly
  labelled owner guidance within Distill's existing procedure. Provider text
  cannot set it; edits affect new captured versions, not queued work or Source
  hashes. Empty-field compatibility preserves older admitted occurrences.
- A Connection may have no Feeds. HTTP API Connections support an explicit
  read-only endpoint test and optional Bearer/Bot credential; configuring one
  does not add a Discord bot, API stream adapter, or model Tool. Credentials are
  write-only, systemd-creds encrypted under `~/.config/obsidience/connections`,
  bound to exact connection ID and HTTPS origin, and excluded from Source,
  config, trace, prompts, and API reads. New Feeds default enabled; explicit Pause remains authoritative.
- Settings > Connections owns third-party access setup. The standalone Feeds
  pane owns its Connection-grouped feed list, captured items, Preview and feed
  Settings. Feed selections open in the same standalone Reader used by
  Knowledge and Source; there is no embedded Feed Reader or repeated access
  editor. Preview separates publisher choice from collection, destination,
  retention and Darwin instructions. Narrow panes use a compact feed selector;
  Save/reset remain outside the scrolling editor. Collection amount is edited
  only beside Preview. A new RSS Feed starts with its chosen Connection address.
- Knowledge, Source and Feeds share Reader's four fixed dock slots: upper/lower
  left and upper/lower right. A collapsed slot keeps its position. Docking into
  an occupied slot swaps an already docked pane or moves its occupant into an
  empty slot when the incoming pane is floating. The existing revisioned dock
  authority owns the operation; no second placement file or docking service.
- Explicit Feed Preview reads a saved or draft endpoint through the existing
  HTTPX/feedparser path and exact Connection origin. It shows up to 30 unique
  publisher-ordered entries with dates and inert supplied text; first-X
  highlighting responds locally to item_limit. This means the first X
  publisher entries, not X unseen or model-ranked stories. It writes no Source,
  Task, config, receipt, validator or cursor and never loads linked pages or
  assets. Reject stale revision/connection/draft responses. Opening the pane
  performs no provider I/O. Collect now remains explicit intake using saved
  settings. Reader projects captured items with exact Source ID/path attestation
  and labels uncollected publisher previews explicitly. Its bounded preview
  selection is ephemeral shell presentation only and cannot be edited, curated
  or treated as a Source. Selection changes invalidate pending document/save
  responses before another item renders. No second database or summarizer.
- `Source` is the one read-only filesystem view beside the graph. Every leaf
  retains the exact project-relative path of a real file:
  `obsidience/vault/` holds wiki Articles, `obsidience/evidence/` holds
  immutable raw material, `obsidience/harness/`, `obsidience/shell/`,
  `obsidience/ui/`, `obsidience/scripts/`, and `obsidience/tests/` hold
  application code, and
  `obsidience/state/system/` is the physical System inventory:
  `hardware/` contains Compute, Drives, Devices, and Network; `applications/`
  contains installed or explicitly not-yet-integrated application records.
  Clicking a leaf opens those exact
  bytes. The Source tree follows these real folders and real storage locations,
  never a renderer-only taxonomy. `SYSTEM > HARDWARE` and
  `SYSTEM > APPLICATIONS` are peers; Drives describes its actual storage
  locations without nesting the project or vault under a device. Private `@view/` keys stabilize UI identity
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
  trigger on Darwin's Learn Task for general intake or Distill for Feed items; it never creates a
  Source-specific Task. Darwin drops at most one cited synthesis through
  `source.handoff` into the physical `obsidience/evidence/inbox/`. That durable
  write emits `source.inbox`, whose sole subscriber is Alexandria's centralized
  Ingest Task. Duplicate capture or handoff emits no event. Source writes never
  create Knowledge or an intermediate Review object.
- Finished UTF-8 text files arriving in `obsidience/evidence/incoming/` enter
  that same Source boundary through one in-process watchdog 6.0 inotify
  observer. Closed writes, atomic moves and startup reconciliation are the
  inputs; no filesystem polling or second service. Originals remain on disk,
  while Source attests immutable evidence. Hidden, partial, binary, symlinked,
  changing or oversized files are not ingested. This is the explicit intake,
  not a recursive research watch over code, model weights or the whole computer.
- Research-owned supporting captures preserve Source events but bind them to
  the exact existing Darwin execution so they do not recursively queue Learn.
  Inbox provenance binds the actual research Task/run; text cannot assert it.
- `News & Research/Top Stories` is the ordinary Knowledge destination for new
  or changed items from the BBC Top Stories Feed. The former Top 10 edition is
  archived. Historical Feed publications remain at their captured paths, and
  normal Feed retention continues across destinations. There is no News Task,
  hourly briefing schedule, fixed edition compiler or News-specific Tool branch.
  The configured Connection/Feed intake is the only automatic news acquisition
  path: immutable Source activates Darwin's Distill, whose cited handoff
  activates Alexandria's Ingest. Each
  Feed selects its destination, collection interval, amount, instructions and
  active-Article limit. Existing articles, Sources and historical execution
  receipts retain their identities and OKF freshness fields.
- Darwin owns research and summaries; Alexandria ingests the complete handoff
  and maintains useful graph relationships without repeating the reporting or
  rewriting the summary. Feed retention remains the atomic incoming-plus-archive
  path through the ordinary Review owner. General Auto-curate cannot grant
  executable authority, alter policy, or archive unrelated Knowledge.
- Acquisition uses pinned Trafilatura 2.2.0 beneath the existing HTTPX and
  immutable Source boundary, with Markdownify for generic or sparse documents.
  `web.fetch` accepts up to ten URLs with four joined workers and a
  60,000-character encoded result limit. The existing read/search Tools also
  accept bounded batches; failures, identities and recovery paths stay explicit.
- Scheduler admission counts direct, scheduled and externally running Task
  identities before claiming configured capacity. Ready Source Inbox heads
  precede other bound events, which precede periodic work. Each class remains
  chronological and each Task's FIFO stays intact. Deferred cron remains
  overdue; active continuations, foreground work, STOP and model reservations
  retain their gates. This order never preempts an active Task.
- Physical index IDs map to visible graph nodes before Auto-curate markers
  cascade to descendants; branch and Article rings share the same dotted
  Three.js shader. Do not add a second marker state or extra animation loop.
- A Source-tree checkout is plain Agent Knowledge scope metadata, not a Task assignment
  or graph edge. It maps the selected subtree to related accepted Knowledge
  Articles and only prioritizes those Articles inside the ordinary bounded
  fast search. It never attaches raw files wholesale, grants Tool authority,
  creates a Task or Runbook, or turns transient System telemetry into durable
  Knowledge.
- Source uses scoped keyset pages capped at 2,000 records per response. Its
  explicit live coverage is separate from integrity issues; no ordinary page
  limit may mark System data faulty. Exact file reads and scoped checkouts
  resolve allowed roots and accepted resource links independently of the first
  page. Both Source clients follow all pages and retain their prior complete
  inventory on failure. Every accepted resource reference remains audited,
  including references outside the requested page or scope.
- Checking out exact `obsidience/state/system` supplies the accepted ADMECH
  Workstation branch through ordinary retrieval. Hardware narrows that scope
  to ADMECH Hardware; Applications narrows it to ADMECH Software. This adds
  Knowledge priority only and never attaches Source bytes or executable
  authority.
- Obsidience is the harness and the visible shell of an Arch Linux system.
  Hyprland is the compositor boundary; Linux, systemd, udev,
  PipeWire/WirePlumber, NetworkManager, Polkit, PAM, and standard compositor
  protocols remain upstream plumbing. Do not recreate them inside the Harness.
  Obsidience may grow into a complete OS environment, but that direction adds
  no ontology kind or fictional Capability: each responsibility arrives as one
  real Module slice with rollback and an acceptance test.
- The target stack is Hyprland -> `adapter/hyprland` -> stable Shell API -> one
  Quickshell host -> panes, providers, widgets, and AI surfaces. Only the
  compositor adapter may consume Hyprland events or commands. No pane, widget,
  graph, or Harness subsystem may call the compositor directly.
- greetd launches the default `Obsidience` UWSM session directly. One Hyprland
  process owns Samsung `HDMI-A-1` through the RTX 4080 and USB-C `DP-8` plus
  logical DP-4 `HDMI-A-2` through the AMD iGPU. One native QML host reuses the
  pane registry and one Three.js graph across all three logical Surfaces and
  stores state under `obsidience-shell`. KWin, Plasma Shell, Plasma Login Manager,
  KScreenLocker, and SDDM are removed from the live installation. Their Git
  archive and backup are rollback evidence only, not an installed recovery
  session.
- greetd's empty `/run/greetd.run` marker suppresses `initial_session` after
  the first launch of a boot. For a deliberate development compositor recycle,
  save tmux first, stop `greetd.service`, wait until the old UWSM compositor and
  graphical-session targets are fully inactive, verify and unlink only that
  exact empty marker, then start `greetd.service`. A single restart can race the
  old UWSM teardown and reject the new session as a duplicate compositor;
  leaving the marker in place lands on agreety instead of restoring Obsidience
  automatically.
- The existing Quickshell host is the one active-session lock authority.
  `LockController` owns one `WlSessionLock` plus `PamContext`, and the compositor
  creates a secure lock surface on every output. Each surface first paints the
  opaque `#02060c` background. Only the Surface selected by `graph_surface_id`
  loads the existing Three.js `lock=1` graph route; the other Surfaces retain
  the shared Obsidience identity. Password input stays in the native QML prompt,
  reaches only PAM, and can release the lock only after PAM success while the
  compositor reports the session secure. The graph is decoration and never
  receives credentials or decides unlock. Its failed initial navigation uses
  the existing Harness connection signal for one bounded reload per connected
  interval, including reconnect-before-load-failure races; working graph pages
  stay resident and failed pages retain the opaque stage. This presentation
  recovery cannot replace the lock or PAM owner. Do not add Hyprlock, gtklock, or a
  second lock process beside this path. Authentication policy is the root-owned
  `/etc/pam.d/obsidience`, not the writable Source tree. The selected Quickshell
  runtime is the content-addressed compatibility build at
  `/home/wissenschafter/.local/opt/obsidience-quickshell/quickshell-0.3.1-webengine-lock-6333ecc9/quickshell`.
  It retains the two-line Qt WebEngine host-contract patch and backports only
  upstream Quickshell commit `afb2c27`, which serializes session-lock surface
  realization and suppresses reentrant screen updates. Hyprland's supported
  `misc.allow_session_lock_restore` option lets this sole locker reclaim a
  fail-secure lock if its prior process dies. The host service performs that
  bounded recovery on startup; `session/restart-shell` refuses an ordinary
  development restart while this process reports `locking` or `secure`. Use
  that helper instead of directly restarting the host service. On 2026-09-04,
  the two observed `wl_display invalid object` failures were traced to raw host
  restarts made while the session was already securely locked, not to idle,
  WebEngine, the graph, or screen sleep. Do not replace the selected runtime
  with the unfixed distro binary or a broad unpinned upstream build. Direct and
  `loginctl` secure lock/PAM cycles, a 65-second graph-renderer run, and
  all-output DPMS off/on passed on 2026-09-03. greetd
  continues to authenticate fresh login. Samsung desktop HDR is configured only on `HDMI-A-1` with the `hdr`
  color preset, 10-bit scanout, and a 225-nit SDR mapping physically accepted
  by the owner on 2026-09-02. Do not claim Polkit UI, fullscreen HDR application
  behavior, fullscreen VRR, or WoW acceptance until each is implemented and
  physically verified. Rollback and acceptance evidence begin at
  `/home/wissenschafter/backups/obsidience-lock-reentrancy-20260903-234932`.
- Electron is disabled and retained only on `archive/electron-20260828`. The
  one native host shares one registry across Samsung, USB-C, and DP-4 for Chat, Library,
  Tasks, Reviews, Reader, Knowledge, Source, Models, Hardware, Camera, Settings,
  Applications, Terminal, and Displays. There is no Hyprland copy of any pane,
  no second graph, and no second Reader.
- Graph display aliases must carry an exact canonical `article_ref`. Project
  relationships and Thinking Packet targets through that same identity map;
  Reader and Source navigation use the physical Article. Reader links and
  backlinks come from the canonical graph response, not copied lists in Tool
  or Skill bodies. Display connectivity never grants executable authority.
  That response also derives Task-to-Skill/Tool and Runbook-to-Tool connections
  from exact typed bindings and inherited guidance. Each shortcut carries its
  intermediate Article refs and any Agent scope; Reader explains the route and
  all graph clouds display it. Body mentions never create capability shortcuts,
  and these display edges never enter retrieval or execution authorization.
  Navigation groups publish their exact Article membership once; the Reader
  and desktop use that same scope. Reader selections retain the clicked graph
  identity through navigation so shared Tools do not show another Agent's
  backlinks. Library navigation projects its two graph shelves once, without
  appending a second raw-file tree or duplicate Skill mirrors.
  Assigned Tasks supply the applicable Runbook/Skill/Tool dependency closure;
  manual capability checkout lists are not a second membership authority.
  Parent and index Articles retain their authored semantic links through exact
  display aliases. A relationship already shown by a hierarchy edge is drawn
  once, and absorbed aliases never produce self-links.
- Treat each physical display as one runtime Surface. Surface is not an Article
  kind or Capability. One global `PaneWorkspace` owns module definitions,
  Reader docking, and one persisted placement record per pane:
  `pane_id + surface_id + local_rect + open + optional tile_bounds`.
  Each undocked module is exactly one Quickshell `FloatingWindow`, hence one real
  Wayland `xdg_toplevel`. `FloatingWindow.screen` expresses its intended
  Surface; Hyprland maps and places the native pane. There is no shared window
  canvas, module-local focus owner, or module-local z-order. `PanePlacement`
  stores its canonical record under
  `~/.local/state/obsidience-shell/placements`. When an open pane receives a new
  native Wayland address, the shell issues one exact semantic tile restore
  through the existing compositor adapter before admitting native observation;
  a stale or failed restore cannot overwrite the saved record. Process teardown
  and QML reload are not user close actions. Only explicit pane close controls
  persist `open=false`.
- `SurfaceLayout` defines one logical-pixel grid, 10 px by default, and the
  default proportional tile layouts: Samsung 8 by 2, USB-C 3 by 2, and DP-4 4
  by 1. Tiled chrome has exact 5 logical px outer and inter-pane gaps. From
  freeform, `Meta+Arrow` selects the full edge row or column; once tiled it
  expands toward the arrow or collapses from the opposite side at that edge.
  Only an exhausted `Meta+Up` on a one-row lower Surface crosses without Shift,
  entering the corresponding bottom-edge tile above; every other exhausted edge
  is a no-op. `Ctrl+Meta+Arrow` moves existing tile bounds one cell. Native
  title-bar drag snaps to the nearest tile bounds on release. Raw tiled boxes
  meet at each shared cut; Hyprland's native asymmetric 2/3 px inner gaps render
  the exact 5 px opening while keeping every gap pixel in compositor hit-testing.
  Its standard resize cursor therefore appears throughout the gap for
  applications and modules alike. Native resize moves a full-height column cut
  or only the connected horizontal cut segments beneath the pane's straight
  edge, so the exact neighbors follow while unrelated top/bottom pairs remain
  independent and the exact gap and fixed Surface edges stay intact.
  Shared module chrome exposes separate right-edge and bottom-edge selectors
  plus a 30 px corner selector for two-axis resizing. Each selector sits on the
  actual movable cut, including the opposite interior edge of an outer tile;
  unavailable full-span axes expose no false selector. Returning within 5 px
  of the regular pane size briefly draws the restored default boundary only
  for the axis being resized. OLED motion suppresses that static-size cue.
  Freeform panes retain ordinary right, bottom, and corner resizing.
  Settings > Workspace > Tile behavior persists one resize limit from 0 to 25%
  (25% by default); the selected percentage bounds only the user's manual cut
  displacement relative to each regular grid cell. OLED displacement is added
  independently after that bounded manual position and may cross the percentage
  envelope while retaining positive cells and fixed outer edges. Secure lock
  freezes OLED geometry and glow phase without catch-up. Tiled bounds override
  only freeform pane minimums. The proportional tile projection adapts
  the MIT Omarchy Windows Aero Snap geometry pattern while native Hyprland owns
  its real gaps; no external tiler or second placement authority runs. Pointer
  dragging remains local.
  Tile bounds are placement coordinates rather than occupancy locks: native
  clients may share exact bounds, and the visibly focused client owns input in
  their overlap.
  `Meta+Shift+Arrow` moves the exact active client to the nearest mapped Surface,
  preserving logical pane size and shrinking only a dimension larger than the
  complete destination workspace. No pane-specific bridge, held-pointer lease,
  or coordinator process is allowed.
- Native applications and undocked module panes follow one window contract
  through Hyprland's supported `lua:obsidience` layout. Hyprland is the sole
  authority for focus, z-order, outer border/shadow/rounding, interactive
  movement and resize, `Alt+Tab`, and tiling. `input.follow_mouse` is `0`, so
  pointer hover never changes focus. `Alt+Tab` uses Hyprland's native forward
  cycle and `Alt+Shift+Tab` its native reverse cycle. Every close, layout, or
  transfer shortcut sends exactly one token-bound native window-adapter request;
  it never preflights or falls back through a QML action and never builds a
  mixed focus ring or second focus owner. The adapter pins the exact active
  address and state revision before issuing one compositor command. `Meta+Esc`
  closes only that exact active client and never sends a generic close to the
  shell host.
- An undocked module toplevel is classified only when its immutable initial app
  ID is exactly `io.obsidience.shell` and its immutable initial title matches
  `obsidience-pane:<pane_id>`. Mutable display titles are never identity. The
  window inventory includes these module clients so native focus, close, layout,
  transfer, and geometry observation apply uniformly. The Applications taskbar
  list filters inventory rows carrying a `pane_id` because the shell's pane
  buttons already represent them; this presentation filter must not remove
  module clients from the adapter. `PaneFrame` may supply module content and
  internal title-bar controls, but it does not draw competing outer compositor
  chrome.
- Native applications retain their own client-side title or tab-bar drag
  regions. An undocked module's shared title bar requests the same standard
  Wayland interactive move from its `FloatingWindow`. Hyprland performs both
  moves, and the adapter adopts the released one-or-more-cell footprint. Do not
  add a modifier bind, global primary-button interception, application wrapper,
  or second QML drag authority.
- Input has one physical/compositor truth. The connected classic M.M.O.7 is
  verified at its 6400-DPI top stage and Hyprland applies one per-device custom
  linear `0.125` multiplier for 800-effective-DPI motion on all
  Surfaces. Never restore the retired DP-4/USB-C per-display scale split, add a
  second mouse profile store, or let a pane call Hyprland directly. Settings >
  Input projects Mouse and Keyboard state through the Hyprland adapter.
- Hyprland owns all three outputs. The RTX 4080 is the primary renderer and
  owns Samsung; the AMD iGPU owns USB-C and logical DP-4 scanout. There is no
  per-Surface compositor, shell host, pointer router, clipboard bridge, Xorg,
  or Openbox path. One `graph_surface_id` selects the whole graph; per-Agent
  graph placement remains deferred. Settings is one sectioned pane; Graph,
  Input, and Workspace do not gain standalone bar buttons.
- Settings > Workspace > Tile behavior also owns the optional Samsung OLED
  motion policy. It is disabled by default and defaults to a 32 px maximum
  displacement per shared seam, a nominal active hour from center to either limit,
  and one complete neon rotation per three active hours. Independently phased
  full-height vertical seams and connected horizontal segments follow
  deterministic reflected paths, start at the manual center, and dephase through
  deterministic direction and ±10% pacing; panes on both sides receive the same seam
  coordinate, so gaps stay exact and one pane can change by at most twice the
  configured per-seam drift. One shared one-second Hyprland timer owns motion;
  it writes client geometry only when a rounded coordinate changes and updates
  the native cyan border and 5 px inner glow at most once per active minute. The
  layout freezes both phases whenever Samsung is fullscreen, off,
  or has no visible active workspace; it does not catch up afterward. It also
  validates retained callbacks against their original Surface/workspace, keeps
  outer Surface edges fixed, and never moves USB-C or DP-4 geometry. Hyprland's
  native border and inner-glow configuration is compositor-global by design so
  pane chrome remains identical on every Surface; Samsung eligibility alone
  advances its angle. Glow angle and runtime seam offsets are ephemeral; only
  the policy persists. The Stage has no separate edge animation. Do not add a
  GIF decoder, per-pane animation, daemon, plugin, full-screen effect, or second
  geometry store for OLED motion.
- Official `hypridle` owns the separate idle trigger policy. After five
  genuinely idle minutes it requests `loginctl lock-session`; `lock_cmd`
  delegates that request to the Quickshell lock controller. At ten idle minutes
  it applies Hyprland DPMS off without an output selector, covering all three
  displays, and activity applies DPMS on to all of them. The two protection
  listeners individually ignore application idle inhibitors so a stale browser
  or video request cannot prevent lock or post-lock screen-off; general
  hypridle behavior retains inhibitor awareness. It performs no suspend,
  brightness, or authentication work. The standard live config path selects exact Source leaf
  `obsidience/shell/idle/hypridle.conf`. Keep this in the upstream service; do
  not fold idle detection into the layout or add an Obsidience watcher.
- The secure lock covers resident shell clients instead of using lock state as
  a client-lifecycle signal. Open pane windows, their loaded content, and every
  Surface launcher remain mapped underneath `WlSessionLock`; the ordinary
  Three.js graph stays mounted but pauses while hidden. Do not unmap or rebuild
  those clients at lock/unlock—the compositor lock surface owns privacy and
  input isolation.
- `obsidience/shell/system-packages.toml` is a names-only additive Arch package
  policy. Required groups describe the target shell; protected groups prevent
  boot/graphics and workstation packages from being pruned. Omission never
  authorizes removal, and observed versions remain evidence rather than
  rolling-release policy.

Canonical Articles use Open Knowledge Format v0.2 with the small Obsidience
profile: required `type` is `knowledge`, `task`, `runbook`, `tool`, `skill`, or
`agent`. Common document fields stay at the root; application metadata lives
under `obsidience`. The shared codec projects this to the existing internal
view; internal `kind` is never a second authored field. Root document `status`
means draft/stable/deprecated, not Task activity. Task queue, parameters, FIFO,
status, latest result and attempt history live in the existing SQLite ledger.
Status-only transitions must not rewrite Articles or re-embed them.

Use ordinary Markdown links for Article bodies, relative or bundle-root
absolute; exact typed bindings remain in the Obsidience extension. A parent's
Article is `Folder/Folder.md`, never OKF's reserved `index.md` or `log.md`.
Imported `verified`, `generated`, resource links, and arbitrary extension keys
are data, not approval or executable authority. Parsing is not admission. Keep
the current graph, retrieval, assignment, review, Source, and executor owners;
do not install the OKF reference agent as a parallel harness.

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
  Darwin owns research summaries; Ingest preserves them and handles placement,
  duplicates, provenance and useful links without a second research review.
- Darwin is the Researcher. He owns Question, Learn, Distill, Model, and Generate.
- Heimdall is the Guardian. He owns Audit, Check, bounded Repair, and independent acceptance.
- Library is the owner's complete accepted Article catalog, including Knowledge,
  Agent identities, Tasks, Runbooks, and paired Tools and Skills. It is not an
  Agent and cannot be an assignment target. Reader owns revision-checked Agent
  checkout icons; the separate Library catalog has no assignment writer.

The Executive and specialist Agent Articles use the same direct subjects:
Architecture, Tools, Skills, Runbooks, Tasks, Other Agents or Subagents, and
Observations. Specialist domain subjects may be added when they are genuine
Knowledge indexes.

Assign Tasks for executable work and check out Knowledge for context. Resolve
Task -> applicable Runbook -> paired Skill -> real Tool through the existing
dependency owner; no independent capability grants. Agent `knowledge` roots and
`exclude_knowledge` determine shared Knowledge access, while owned Knowledge
remains local. Apply that exact scope before lexical/vector top-K, direct graph
expansion, reads, listings, maintenance candidates, and graph membership.
Missing principals fail closed. Another Agent's Observations cannot be checked
out or read indirectly through raw-file Source. Explicit attested handoffs
supply only their exact evidence, not the producer's private graph. Source-tree
selection is only a preference within Knowledge already checked out.

If a Task assignment lacks an applicable accepted Runbook, the ordinary
`task.assigned` event activates Generate → Runbook. Darwin receives the accepted
shared Tool+Skill catalog as candidates and chooses the minimal sufficient
subset, not the entire catalog. Its `vault.propose` must supply explicit
`metadata.skills` refs (or native `metadata.obsidience.skills`). The controller
binds exact `task` and `for_agent` applicability; approval supplies the
dependencies without writing Agent Tool/Skill/Runbook lists. The assigned Task
waits for review rather than executing an unaccepted procedure.

Each named Agent has exactly one canonical `type: agent` Brain Article. A
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
9. the exact `Current conversation` Article in the `Immediate Observations`
   packet section when the activation belongs to the active Executive conversation.

The same compiler produces the provider messages from explicit owned sections:
fixed Agent, Task, Tools, Skills and Runbook instructions remain in the system
message. Immediate Observations use a separate user-data message before the
current Objective, observations, bindings and retrieved Knowledge user message.
Each Article appears once; conversation cannot confer new authority. Keep the visible Thinking Packet order
above unchanged; never parse Article headings to choose roles or introduce another
packet or authority. This boundary permits the installed model's existing prompt
cache to reuse the fixed instructions across questions.
Gemma's b10078 launcher retains the native bounded checkpoints with
`--checkpoint-min-step 0`; the default 8,192-token pruning distance removes the
fixed-prefix checkpoint after Tool follow-ups. Keep the upstream checkpoint
count bound and F16 KV allocation; do not substitute full-window SWA allocation.

Successful provider steps record numeric `provider_metrics` in the ordinary run
trace: preflight time, generation time, first nonempty public delta after dispatch,
and provider-reported cached input tokens when available. Private reasoning and
empty role events are not public TTFT. Benchmark TTFT, actual Task TTFT, complete
answer latency and speech latency are distinct measurements. Diagnostic metadata
must not affect action retry limits or completion/effect receipts.

Since 2026-09-09, the same trace carries bounded monotonic timing edges from
confirmed speech detection and first partial through preparation, selection,
activation, provider work, committed answer, AEC preparation, first PCM and the
first successful native output write. Exact user-turn and run IDs join pre-run
stages to the response; generation and speech sequence reject old playback.
These are unnumbered measurements, never Tool decisions or acoustic proof.
Input timing stays ephemeral until an exact user turn exists and never enters
conversation text or the Thinking Packet. Worker JSON is parsed within a 16 KiB
record bound before presentation text is clipped.

The active compiler, selector and retrieval exclude system/archive Articles at
scan time and reuse one accepted snapshot within each activation. Selection
still rereads accepted Tasks after inference and expiry is evaluated on every
retrieval. Exact Compact threshold lookup reads its Article directly. Only an
ordinary successful interactive Query with one accepted task.complete and no
other decisions skips the terminal Vault sync; its runtime state and Tool
receipt remain committed. All other paths retain reconciliation. Selector input
places the fixed catalog before conversation/scene data and the current Objective
last, preserving its authority while improving prefix reuse.


The existing graph thinking popup presents the same public `/ws/trace` stream
as Terminal. Its expandable matrix groups exact run IDs and pairs Tool calls and
results by call ID. Ordered Thinking Packet sections come from the existing
compiler, not headings guessed from Article prose. Provider measurements attach
to the action or response produced by that exact run and executor step; model
lifecycle events never create numbered matrix steps. Pending generation is Task
status, while unmatched/failed attempts remain unnumbered response diagnostics.
Keep first-text, full generation, preparation, resource wait and Tool duration
distinct. Named input/result fields and final recorded outcomes explain actual
work; private reasoning, pixels, leases and credentials never enter the public
projection.
Successful `task.inspect` and `harness.status` rows show Returned; the inspected
Task status and observed Harness health appear as separate findings. A failed
subject is not a failed inspection. Actual Tool errors and semantic action
failures retain their failure states.
The stream keeps bounded event/history payloads and marks shortened content.
The Relevant Knowledge disclosure includes bounded selection accounting for
eligible search candidates and examined seed neighbors, with supplied/excerpted/
omitted decisions and exact body ranges. It is a display projection only; its
character-based estimates do not replace exact provider token accounting or
alter selection, provider instructions, or authority.
The popup owns only disposable presentation state. Interaction keeps it open
for reading independently of the graph activity linger; close dismisses that
activation, and hiding/locking clears inspection. Pointer input is scoped to the
popup. The existing WebKit layer uses native on-demand keyboard focus so
Tab/Enter reach the controls after interaction without reserving focus. Never
infer completion from graph animation or a dispatched Tool.
The mutable `/shell/knowledge/` HTML entrypoint must revalidate (`no-cache`),
including 304 responses; native WebKit initial/retarget requests also request
revalidation so an old cached document cannot survive a development restart.
Preserve persistent graph preferences and caching of assets with hashed names.

Before each provider request, the existing model subsystem measures the complete
templated payload against the Task-selected context, output reserve, and safety
margin. Under pressure, its activation-local `TaskContext` may project only older
pageable `source.read`/`web.fetch` bodies or version-attested `vault.read` pages
that are bound to the actual Tool result and have an authorized exact reread path.
Article continuations require the returned view hash and reject a changed Article
or backlink snapshot without substituting new content. Preserve read identity,
provenance header, exact offsets and recovery instruction, as well as
the complete Objective, packet, action/effect receipts and latest observation.
This is disposable request projection, not a new memory store or generative
compaction Task. Recount the projected payload; reject an irreducible overflow.
Report whether counting used the actual runtime or the conservative text bound.

The one provider adapter uses pinned `httpx-sse` for HTTPX streaming. Actual
public or private reasoning token progress renews the generation inactivity
deadline; SSE heartbeats do not. Private reasoning is never retained. Require a
complete terminal action before parsing, preserve cancellation, and never
reconnect or replay a partial response automatically.

The model owner checks GPU reservations before scheduler claim and again under
the existing lease. A scheduled or delegated exact occurrence that cannot acquire
its selected layout stays pending with `blocked_reason`, preserving provenance,
parameters, FIFO and continuations until admission opens. A direct ephemeral
request gets an explicit unavailable disposition, not a replay under saved
settings. A reservation denial before any effect is not a failed run; work that
already returned effects must retain its ordinary failure/no-replay evidence.
Do not substitute models or reduce context, precision or resource settings.

Admission checks within one scheduler tick reuse one fresh role resolver. The
next tick and standalone calls read current roles again. Rebuilding the entire
Vault for every Task while foreground input was active caused measured 2.8-second
event-loop stalls; tick-local reuse reduced that scan to about 235 ms without
new threads, persistent caches or altered occurrence/authorization rules.

Every activation also carries one bounded semantic Shell Scene in Bindings.
It names focused and unfocused applications and module panes by Surface and
includes Surface awake state, but contains no compositor IDs, coordinates, or
pixel data. Scene names, observation results and window effects share one
resolver: registered application ID (otherwise exact app_id), or exact pane_id.
Display titles are not selectors. Observation returns a reusable concrete
`target: {kind, name, surface}` even for focused input; title and focused state
remain separate evidence. Multiple matching windows fail closed. `computer.observe` may capture one exact target without focusing it;
`window.activate` and `window.place` are separate explicit effects. One captured
image is attached only to the next in-memory message for the Task-selected
vision model and is never persisted. A sleeping Surface fails immediately and
is never woken implicitly. Do not create a second scene graph, vision Agent,
capture service, focus watcher Task, or alternate window mutation path.

TFT launch identity was corrected on 2026-09-05: `teamfight_tactics` selects
`tft-waydroid.desktop` through the existing managed GUI launcher. The dedicated
Gamescope SDL process sets `SDL_APP_ID=tft-waydroid`; launch readiness,
observation, activation, and placement use only that exact native app_id.
Generic Gamescope windows and the retired Android AVD identity are not TFT
witnesses. The launcher owns duplicate prevention through its lifetime flock;
there is no replacement fixed TFT unit. Preserve the accepted NVIDIA outer
renderer, AMD Android rendering, fixed inner image, stretch scaling, and the
existing mouse-to-touch/duplicate-event guard. An AMD outer-renderer trial was
rejected for a black native window despite valid Android pixels. The verified
normal-renderer result is TFT's sign-in screen, not account or match readiness.
The earlier isolated NVIDIA Wayland `Missing buffer` crash was not reproduced
by the successful launch and is not claimed repaired by this registry change.
Rollback and actual-window evidence are under
`/home/wissenschafter/backups/obsidience-tft-route-20260905-211644`.

Hyprland sends `hl.dsp.layout` messages to the focused workspace. Exact
`place`, `place-cancel`, and `restore` messages must resolve their addressed
window through the layout's existing current contexts, rejecting stale or
ambiguous matches; they must not require or change target focus. Active-window
shortcuts keep their focused-context scope. The 2026-09-05 live regression
moved TFT from Samsung to USB-C and back through `window.place` while Terminal
retained focus, verifying the exact window after both effects.

The API's Realtime, Trace, and Activity event WebSockets share one disconnect
lifecycle: a sender and disconnect reader are cancelled and joined before the
owning route unsubscribes. Quiet producers must not leave handlers waiting on
empty queues during client disconnect or Uvicorn shutdown. The 2026-09-05
repair extends the existing Realtime lifecycle to Trace and Activity; preserve
their original publishers, snapshots, event formats, and bounded queues.
Rollback and real-socket regression evidence are under
`/home/wissenschafter/backups/obsidience-event-ws-close-20260905-213230`.

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
Knowledge retrieval filters each lane before ranking and resolves direct hits
and neighbors from one accepted-Article snapshot. Archived, staged, temporary,
and `retrieval: false` Articles cannot re-enter through graph links. Immediate
Observations still rides separately through its explicit conversation binding.
Embedding identity is the loaded model artifact plus the actual embedded text,
not Task status or other metadata. Index synchronization computes first and
publishes once in SQLite; its derived vector cache invalidates on local changes
and external commits. Keep this in the existing index, not a second service.
Definitions never carry operational state;
runtime state belongs to Tasks in execution and the run ledger.
Every started activation emits one terminal graph event even on interruption or
failure. Cancellation preserves completed Tool results in an interrupted ledger
entry, marks in-flight effects unknown and non-replayable, and propagates to the
caller. The Realtime connection remains enabled and its microphone stays open.
Model-lease cleanup always releases ownership, including cancellation during
default-model reconciliation.
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

Shell Scene publishes each Surface's current columns and rows with explicit
`grid_edges` units. Invalid pre-dispatch placement returns that contract for
correction; uncertain delivered effects remain non-replayable. Exact tile success
requires the existing compositor layout's addressed-window readback through the
one Shell adapter, matching requested Surface and bounds after placement settles.
A verified no-op is reported honestly and is not evidence that a window moved.

The Executive's exact public conversation is runtime state. Typed Chat and
Realtime speech share one active 80-turn hot deque backed by complete SQLite
history. Enabling, reconnecting or restarting Realtime preserves the selected
conversation. Only the owner's explicit New conversation control rotates that
identity. Speech connection lifetime is not conversation lifetime. Persist the final user turn before execution and persist an
assistant turn only for a current, completed, nonempty public reply linked to
that exact user turn.

Immediate Observations is a real folder/index Article beneath Observations, peer
to Temporary Observations and the durable Preferences subject. Project the active
conversation into its single transient, unverified `Current conversation` child at
`Agents/Executive/Observations/Immediate Observations/current-conversation.md`.
It contains the latest cumulative Temporary
Observation, if any, plus exact completed dialogue and unresolved final user
requests after that compaction boundary. Preserve accepted failed clarification
replies as explicitly failed historical evidence so the next correction retains
its original question; never admit raw executor errors or partial assistant text. The Article rides inside the Thinking Packet and its exact ref rides
the visible graph activation path; it never participates in similarity retrieval
or grants Task, Runbook, Skill, Tool, or Policy authority. The current request
remains the Task binding rather than being duplicated into the Article.
Both lifecycle branches have same-named Markdown condensations. Ordinary graph
labels remain hover/selection/activity-driven; no observation gets a permanent
label exception. SQLite remains the exact history store, not one new Article per
turn. Runtime Immediate and Temporary children are excluded from ordinary wiki
Merge/Link candidate generation and proposal approval; Compact and Promote own
their lifecycle. The branch indexes and durable Preferences remain ordinary
maintainable Knowledge.

At the configurable 60-to-90-percent occupancy threshold, 80 percent by
default, issue the ordinary `observations/immediate/compact` Task. Measure
occupancy against the active Task's selected model; Compact itself uses its
authored resident Executive model to replace the completed Immediate prefix with one
cumulative Temporary Observation of at most 2,000 characters. Each compaction
keeps the newest two completed pairs exact during an ongoing conversation;
boundary compaction includes the remaining tail. The summary uses Goal,
Constraints and corrections, Verified state, and Outstanding headings. Every
summary remains a separate transient, unverified Article while exact SQLite rows
remain unchanged. The active conversation's newest committed summary must not
expire under the ordinary Temporary TTL. Finalization is keyed by conversation
sequence, so continuing the same Chat can produce another promotion later.
At a real conversation boundary, Alexandria's ordinary
`observations/durable/promote` Task archives the exact Temporary bundle in
Source and stages only justified owner-review candidates. When an explicit New conversation closes the old identity during speech,
Realtime defers that old conversation's final compaction and event until speech ends;
the Task then waits for the executor to become idle. Compaction and Source
archival never create accepted durable Knowledge. Do not emit the superseded
per-turn Maintain Temporary Observations activation for Executive Chat or
Realtime.
Observation Source archives still emit `source.added`, but their controller-bound
`observation_archive` class does not activate Research Learn again. Promote
finishes `review` when it stages proposals, not `completed`.
The model runtime owns tokenization and chat-template serialization. The context
meter counts selected-model text tokens plus measured packet overhead; the
executor checks each complete serialized request against the selected model's
input allowance before inference. Preserve the complete Objective, including
typed line breaks; reject overflow clearly rather than silently clipping it.
Gemma 4 is selected by explicit Model family metadata. Its server template owns
system, turn, and thinking tokens; never hand-build them in Articles. Reuse the
server's JSON schema decoder to restrict public responses to authorized Tool
names. Interactive work returns its public answer through ordinary
`task.complete`; Tool arguments and all effects remain validated by
Obsidience. ADK and Hindsight are design references, not runtime dependencies,
alternate executors, or alternate memory authorities.
Task reasoning remains private and uses the selected per-Task effort. The
provider must constrain every public executor response to one JSON action
object; retain bounded finish and parse diagnostics in the run ledger instead
of storing complete malformed model output or adding Task-specific parsers.

Model choice and reasoning effort are per-Task execution settings. `auto`
routes Executive to responsive Gemma and specialist Agents to the fully
GPU-resident Qwen3.8 9B Distill. Hardware residency is modular: each GPU owns
one selected component, and a Task lease displaces only components on the GPUs
that Task needs before restoring the residency selection saved in Settings → AI & Voice. The fallback
configuration is Gemma on the RTX 4000 Ada and OmniParser on the RTX 4080 SUPER;
persisted user selections are authoritative. No model layer may spill to CPU.
Muse may run text-only on the RTX 4000 or use both GPUs for vision plus DFlash;
the known-invalid RTX 4080-only layout is rejected. Models contains only Task
reasoning models.
When OmniParser is not the selected RTX 4080 component, the marker
`%t/obsidience-perception-enabled` is absent and the paired systemd conditions
must keep `jarvis-perception.socket` and `jarvis-perception.service` inactive;
selecting OmniParser creates the marker before either unit starts.

Realtime is speech connection and session infrastructure. Its button opens or
closes audio; it does not create a Task or select a Runbook. Typed Chat and each
final speech transcript select the same accepted work definitions:
`Tasks/query` for a question and `Tasks/executive/operate` for a computer outcome.
The Executive taxonomy groups those two outcomes as Knowledge, while Query
retains its exact canonical path. Both Tasks explicitly select
`obsidience-gemma`; Query and Computer Use both use `none` effort, per the
owner's 2026-09-05 responsiveness preference.
Their per-Task `model` and `reasoning_effort` fields remain authoritative.
Fixed Pipecat and NVIDIA NeMo transport streams the microphone selected in Settings → AI & Voice
through Nemotron Speech Streaming EN 0.6B on the RTX 4080, while Pocket TTS runs
on CPU. Use Pipecat's upstream `LocalAudioTransport` with process-scoped Pulse
routing; do not add a browser audio client, audio WebSocket, or custom
capture/playback processor. Each final transcript executes its selected work
through the one Task activation packet, Tool path, ledger, and ordinary
`task.complete`. Its verified public summary serves both Chat and speech.
Speech onset cancels playback and the
in-flight Task without closing the microphone. The speech runtime is not an
Agent, planner, Tool owner, memory, policy, verifier, or second reasoning path.
Pipecat capture must emit VAD frames without creating generic user-turn
interruptions; `NeMoTurnTakingService` is the sole turn/interruption owner. The
OBSBOT AEC route uses Silero confidence `0.2` with minimum volume `0.0`; the
bounded NeMo turn-taking adapter treats a nonempty recognized transcript as a
speech start when Silero misses AEC-conditioned speech and supplies the same
0.7-second stop edge through NeMo's existing VAD contract. The adapter also
resets the streaming ASR state upstream and serializes the canonical
`UserStoppedSpeaking` edge; `HEARD` never substitutes for that edge. Realtime
state exposes NeMo's user-speaking state and the latest typed partial or final
transcript, and the visible final is the exact normalized text submitted to the
Task.
The shell's one `ShellApi` consumes `/ws/realtime` for all Surface launchers.
Partial words render on their incoming event; do not restore a two-second
`/api/realtime` poll or per-Surface stream owners. The existing recognition
strip displays a bounded history of actual microphone levels as native QML
waveform bars. Capture telemetry is measured before ASR and its provisional
`capture_active` VAD state is presentation-only: it neither sets semantic
`user_speaking` nor interrupts or submits work. NeMo remains the sole semantic
turn owner, and only final transcripts activate Tasks. Disconnect, Realtime off,
and worker replacement clear transient waveform/capture state. No UI microphone,
audio socket, copied PCM, fabricated waveform animation, or recognizer is added.
Realtime ready must wake the OBSBOT camera through its official SDK; Realtime off
must sleep it. While Realtime is on, the same SDK command disables the camera's
120-second no-video auto-sleep timer; off restores it. The camera's real hardware
state owns its microphone state. Reassert the OBSBOT UAC microphone enable after
camera wake even when the SDK already reports enabled: the Tiny 2 Lite can otherwise
remain digitally silent. Do not substitute custom wake frames or a keepalive.


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

## Scoped activation implementation


A Task definition is not an active request. The existing SQLite ledger stores
one `task_activations` occurrence for each event or user turn and links every
attempt in `runs` to its `activation_id`. The Task status/FIFO is a compatibility
projection of those occurrences, not a second authority. Each occurrence keeps
its original objective, inputs and result; a later request never inherits its
predecessor's target. Completed occurrences cannot be implicitly replayed.
Different occurrences of the same definition retain independent history. Unknown
effects remain unresolved; only evidenced independent work may pass a terminal
head. Review resolves the originating occurrence rather than a newer Task head.
Existing state is normalized once without rewriting historical receipts.
New admissions, completed work and foreground release wake the existing scheduler
so a ready response need not wait for the periodic housekeeping interval.

Task hierarchy supplies navigation and assignment scope only. It does not
execute descendants sequentially. Order and prerequisites belong to a Runbook;
select one applicable executable Task for an activation. Application launch
uses a complete bounded operation: dispatch once, await the existing scene's
readiness witness, then report ready, timeout or uncertain delivery honestly.
No readiness timeout authorizes a second launch.

The compiler uses authored `Runtime` instruction sections and applicable
operation sections without discarding the full reference Articles. A Runbook's
`operation_tools` may only narrow its accepted capability set. Static registry
argument schemas constrain each Tool with its own input shape; Tool adapters
still verify effects, targets, and evidence. The completion owner narrows successful
evidence-bound completion to explicit no_change/evidence fields while no change or
proposal is recorded. Failure remains available; a decoding constraint is not
verification of the model's evidence. Instruction hashes and character
ranges record what was supplied. Knowledge prose cannot become executable policy.

Required context is explicitly selected through `required_context` on accepted
Agent/Task/Runbook contracts. It must be in the Agent's checked-out graph and
current; missing or oversized required constraints fail instead of being silently
omitted. Optional Knowledge uses scoped lexical/vector ranks plus bounded direct
neighbors. Relevant contiguous passages replace fixed leading excerpts; exact
Unicode offsets and omission accounting remain visible. A retrieved relation is
context, not an authorization edge.

Each Agent has a lifecycle-owned Current activation Article containing its exact
objective, selected/read Article refs, resolved entities and controller receipts.
It is transient, unverified, and excluded from search. The model receives the
current request once in Objective; Reader additionally displays that request in
its working-state view. Public graph activity means actual context supplied,
Article read/search, Tool dispatch/result or accepted relationship, not inspection
of hidden model reasoning. Idle transport and checkout refreshes never fabricate
thinking. Late progress from a superseded activation cannot replace the new view.

Realtime Query may request one bounded admission reclassification before any
effect. Reclassification reuses the original user request and exact authorized
Task selection; it cannot create a Tool grant or repeat an operation.

## Knowledge maintenance

- System evidence is collected and published by the Harness itself, without a
  model or Task. The bounded `knowledge/system_schema.py` catalog reads the
  physical `state/system/{hardware,applications}` descriptors and supplies
  Source labels and the deterministic `knowledge/system.py` publisher.
  The Knowledge root is labelled System while its ADMECH Workstation reference
  remains stable. Hardware is a physical Source grouping only: Compute, Devices,
  Drives and Network publish directly beneath System. Applications contains one
  leaf Article per application; registered application details are cited sections
  within that Article, not child nodes. The publisher owns this projection;
  collectors and Source retain their exact physical descriptor paths.
  Existing installations migrate through `migrate_system_schema --flatten`
  with the Harness stopped, a Vault/SQLite/receipt backup, and the exact dry-run
  plan hash. Retire wrappers through native OKF archival and repair accepted
  references; never rewrite historical Source or Review receipts.
  Labels cannot relocate stable descriptor-derived Article paths. Fixed approved
  observations enrich descriptor facts; collector strings never execute code.
  Immutable versions live in `evidence/system/`, outside the System schema.
  Authored workstation contracts and historical observations are direct Article
  children of Workstation Observations. Do not repeat Hardware, Applications,
  Software, Incident, or other subject folders beneath that branch; ordinary
  Article links express those associations. Redundant folder condensations are
  archived with their content, and accepted references point to the substantive
  Articles. System scope is
  read-only; new authored content belongs under Workstation Observations.
  Refresh runs at startup and through the owner Source-pane action.
  Preserve exact `source://` citations,
  stable bytes on unchanged input, and prior good Articles when a collector is
  unavailable. Controller receipts record publication hashes and provenance,
  not a second knowledge store. Imported `generated` metadata grants no rights.
  Reader edits, proposals, Review decisions, moves and automatic maintenance
  must preserve the publisher's destinations; generated Articles remain readable
  and usable as link targets.
- Source shows System, Knowledge Markdown, Evidence, and Project Files. Host network
  interfaces belong at `state/system/hardware/network.json`, reflected under
  System / Network. Connections remain Settings configuration.
  Knowledge Markdown exposes the actual `vault/` Article paths. Evidence shows
  captured references in `raw/`, the optional manual-import folder `incoming/`,
  Alexandria handoffs in `inbox/`, and immutable System captures in `system/`.
  These are distinct stores; raw evidence is not graph Markdown. Reading Source must
  never collect hardware, rewrite descriptors or create research work.

- Keep System inventory shallow: physical `hardware/drives` supplies one descriptor
  and a direct System / Drives Article per physical drive, matched by exact serial/model and its
  attested WWN through installed util-linux `lsblk`. Device numbering is observed
  data, not identity. Partition, filesystem and mount details stay inside that
  drive Article. Obsidience and model-store paths belong in the Obsidience
  application Article; they are not drives or a System Volume branch. Network
  is one direct System Article; the standalone Web Browser is one direct
  Applications Article. Cameras, Microphones and Speakers describe endpoint
  inventories. Keep real multi-subject groups such as Compute and Devices;
  Obsidience settings stay inside its application Article. Retired condensations retain their OKF
  archive fields and original Source citations.

- Auto-curate is one owner-authored `auto_curate: true | false` field on the
  actual Article. Children inherit the nearest explicit selection, including a
  false opt-out. An Agent Brain scopes its own Knowledge folder, not shared
  capability definitions. Reader state and dotted graph rings use that exact
  effective permission. The checkbox changes permission, never creates a
  per-node Maintain Task or changes existing Task triggers.
- The three specialist Brains, Executive Observations, subject Observation
  branches, and News & Research are enabled. Only scoped create/update Knowledge
  proposals may use the ordinary approval path automatically. Agent identity,
  capability and authority metadata, archives, unresolved links and stale
  proposals retain their review boundaries. Feed publication keeps its exact
  Source -> Distill -> Inbox -> Ingest provenance gate. Auto-curate is permission, not
  proof of a claim's truth.
- Immediate's disk projection and Temporary append consult the same permission.
  Turning Immediate off freezes the displayed Article without deleting SQLite
  history or removing conversation context from the model. Turning Temporary off
  blocks new appends/compactions, rather than silently bypassing the checkbox.
  Existing observations are not deleted by a toggle. Compact and Promote remain
  ordinary Tasks with their own triggers and per-Task model selections.

- Learn accepts general `source.added`; Feed items activate Distill. Darwin
  reads the exact Source and writes one cited finding to the physical Inbox.
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
  by their exact destination Task, sorted Article refs and accepted candidate
  revision. A fresh Curate inspection may identify work on a newer revision.
  The existing scheduler may settle a conclusively unexecuted stale maintenance
  occurrence using its exact creator receipt, preserving the failed run and
  advancing one FIFO head transactionally. Original signed argument spellings
  are verified before comparison with canonical runtime values: numeric `1`
  and `1.0` agree, while boolean/number changes, altered values, truncated or
  unverified evidence, and possible effects remain unresolved.
- Task presentation separates current admission from the immutable last attempt.
  Owner Retry pins the failed run, attests its unchanged event and FIFO, and
  permits only complete read-only/no-Tool attempts without child or Review
  effects. It requeues through the existing scheduler and preserves Realtime
  and model-resource admission; it never relabels the old receipt successful.
- An explicitly owner-authorized maintenance resolution may review current
  Articles and settle each exact commitment through the existing occurrence
  transaction. Preserve the original interrupted run and any unknown legacy
  effect coverage; a current-state review is not a model replay. Accepted
  Article changes still use the ordinary Review authority. A controller
  no-change receipt suppresses only its attested reviewed candidate key and
  revision, retaining the original activation parameters and both endpoint
  hashes. Changed Article inputs remain eligible for a fresh Curate review.
- Promote validates exact committed Temporary inputs before model acquisition
  and again at archival through the same observation owner. An older incomplete
  summary is invalid input, never an accepted compaction or archival result.
- Source inbox identity is recorded in the initial activation receipt before
  cancellable execution. A pre-Tool foreground interruption must retain it.
- Harness startup restores the speech owner's same-login enabled intent before
  scheduler admission. Explicit Realtime Stop clears that runtime marker;
  Harness shutdown preserves it. Restart the Harness directly when Realtime
  should return; do not issue an explicit Stop as a restart precondition.
- A Task awaiting an owner decision is not idle. `task.create` must not rerun,
  overwrite, or queue another occurrence of that Task while it is in `review`.
- Review decision and execution finalization are order-independent. If the owner
  decides every proposal from an exact run while that run is still finishing,
  finalization completes the Task and must not recreate stale `review` state.
- Review queue reads share the API decision lock. The native pane removes an
  acknowledged card before another decision, rejects older queue responses,
  and reconciles a failed response by reading the queue without replaying it.
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
- Link proposal evidence records exact wikilink locations and endpoint revisions
  at staging, not a model-authored confidence score. Approval blocks missing or
  invalid endpoints and stale proposal/source bodies. Endpoint revision drift
  is a visible warning, never a hidden proposal rebase. Link changes Knowledge/Agent bodies, never Tool
  authority. Curate connectivity signals remain diagnostic leads, not taxonomy
  or a reason to link otherwise unrelated subjects. Exact missing Article paths
  must not resolve to a different Article sharing the same basename.
- Improve handles copyediting, categorization, expansion, retitling, and
  splitting as Runbook branches. An existing folder Article and native
  hierarchy satisfy structural child coverage; do not synthesize per-child
  Markdown tables of contents or duplicate hierarchy links. `missing_index`
  remains for a real folder without its folder Article. Preserve useful parent
  condensation and evidence-backed editorial improvements. Existing retention
  checks continue to protect real accepted inbound links.
- Archive handles one explicitly deprecated or evidenced superseded Article;
  elapsed freshness alone belongs to Audit. Audit covers evidence,
  contradictions, and graph links; Check covers deterministic harness health.
  A valid healthy or degraded snapshot completes the Check inspection; only
  failure to obtain or report that snapshot fails its execution. The health
  Tool and Tasks API share the existing execution-ledger projection of current
  unresolved commitments, blocked configuration, and scheduled drafts. Idle
  historical failures remain visible without independently degrading health.
  The same snapshot includes seven-day history, capped at 200 run records and
  400 Tool receipts, grouped by exact Task and recorded Runbook or Tool revision.
  Recurring findings require at least three eligible outcomes, two unsuccessful
  outcomes, and a 50 percent rate. Counts, exclusions, sample completeness and
  bounded evidence stay explicit; dispatch receipts cannot prove semantic
  success or root cause. These diagnostics grant no retry or repair authority.
- A completed degraded Check dispatches the ordinary `harness.degraded` event
  to Heimdall's sibling Repair Task. Its persisted controller finding and
  existing-ledger handoff receipt make restart reconciliation idempotent.
  Repair uses only `harness.status` and paired `harness.repair`; the latter may
  requeue an exact failed occurrence once only when complete durable receipts
  rule out effects, retained Review and continuations. It revalidates within
  the existing Task transaction and commits its receipt with pending state.
  The original Task/event/activation key, not a later run ID, bounds that retry.
  A missing legacy receipt is not automatic replay authority. Repair excludes
  itself, preserves FIFO and previous attempt evidence, consumes its inspection
  on an attempted operation, and requires fresh status before completion.
  Each pass allows at most eight attempts, counted from its existing controller
  Tool trace, and lists eligible work before blocked entries. It completes only
  after a fresh read and either no eligible entry or an exhausted pass budget;
  further eligible work remains explicitly deferred to a later Check pass.
  A completed bounded pass may report unsupported blockers or queued work;
  neither means the target outcome succeeded. No shell, model change, Source
  mutation, second scheduler or automatic Review approval is granted.
- Research contains Question, Learn, Distill, and Model. Model is an ordinary
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
inventory and benchmark surface; Settings → AI & Voice owns saved residency.
Models contains Task reasoning models only. Settings → AI & Voice shows the fixed
Pipecat, NeMo, Nemotron, and CPU Pocket speech runtime and owns the Star Trek Computer,
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
Settings → AI & Voice owns the exact microphone and speaker for the next Realtime
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

## Bounded Runbook evaluation

- Darwin's Generate / Runbook accepts a controller-frozen `refinement_case`
  for a body-only revision of one existing leaf Runbook. Preserve title,
  applicability, Skill/Tool authority, model and reasoning settings.
- Candidate staging hands `runbook.proposed` to Heimdall's existing Audit FIFO.
  `harness.evaluate` uses the current executor with frozen Tool responses;
  every simulated action is intercepted before live dispatch and completion.
  Never call `run_task` for trials or add a second provider/scheduler.
  Trace identifies each case, baseline/candidate and repetition within the same
  Audit, with separate simulated action/measurement correlation.
- Cases and reports are internal, content-addressed Source artifacts under
  `obsidience/evidence/evaluations`, not new Articles or external intake.
  Fixed criteria are developer-authored; Darwin receives training cases only.
  Require complete paired coverage, no regressions, all candidate cases passing
  and strict training improvement. Evaluation errors cannot be dropped.
- Review requires the exact complete candidate, baseline/dependency bytes,
  selected model profile, evaluator revision and returned Tool receipt from a
  completed independent Audit. Evaluation never approves changes automatically.
  Stale artifacts require explicit fresh preparation; ordinary Check and Repair
  keep their existing responsibilities. Models cannot author implementation
  patches through Generate / Tool or this evaluation capability.
- The developer CLI is `python -m obsidience.scripts.runbook_evaluation`.
  Its prepare command binds an exact recorded execution; start admits the
  existing Generate Task. Total trial duration includes model admission and
  is not TTFT. Frozen tests do not prove actual workstation effects.

## Development workflow

- Canonical project and live shell root:
  `/home/wissenschafter/Projects/obsidience`. The Harness, mutable Vault, Shell,
  UI, tests, and Source projection all use that one root. Hyprland naming is
  restricted to the compositor adapter and package profile; it is not a second
  product, project, or runtime namespace.
- Development harness: `obsidience-harness-dev.service` on `127.0.0.1:8765`.
- The resident graph presenter requires its Shell host but only wants the
  Harness for startup. Preserve its process through Harness stops/restarts;
  existing API and activity reconnection retain the last accepted graph.
  Its lifetime remains part of the Shell session, with the existing HTML
  readiness gate. A provider dependency must never cleanly stop and strand it.
- Native UI: one greetd-launched Hyprland compositor and one Quickshell host
  across all three outputs. `obsidience-ui-usbc-dev.service` is disabled
  Electron rollback and must not be started as a parallel interface.
- The UI is a thin projection of the live graph. It must not invent semantic
  kinds, static claim catalogs, trust rules, or a second scheduler.
- `/api/graph.navigation` is the sole UI contract for Agent/Library card names,
  roles, generated subject Article titles, and subject parentage. UI code may
  route by those stable IDs but must never rebuild their labels from paths or
  keep a parallel subject dictionary.
  Executive Knowledge folders are derived from the real vault tree; each
  authored `Folder/Folder.md` supplies its folder's title, condensation and exact Reader
  path. The API publishes that same parentage and absorbed-hub identity to the
  graph and Knowledge explorer. Do not append a second filesystem tree to the
  declared subject tree or render the folder's index again as a child leaf.
- Generated namespace indexes use human-facing titles with an uppercase first
  letter. Do not rewrite terminal callable Tool identifiers; `vault.read` is an
  exact executable name, while its parent index is `Vault`.
- The graph animation must represent the exact packet path for every Task
  activation and remain passive when no work is being resolved. Read/search
  paths carry the same controller-bound graph ID, run ID and measured retrieval
  duration as that run's start and completion. A terminal event cannot clear a
  different graph/run or resurrect completed activity on reconnect. Automatic
  speed follows measured fast-search duration without a time clamp; its
  checkbox yields to the per-graph Animation speed slider when disabled.
  A render refresh preserves each cloud's force positions, velocities and
  cooling state when its actual physics inputs are unchanged. Task status,
  labels, Auto-curate paint and visual-only settings must not reheat layouts.
  Real node, relationship, parent, collision-radius or force changes may
  resettle only the affected cloud; the main graph and satellites share this rule.
  All agents use createKnowledge3dCloud in knowledge-3d-cloud.ts; orbit, spin
  and scale are presentation differences only. Keep the shared numerical
  layout in knowledge-3d.ts, not a second executive or satellite implementation.
  Brain-level angular relaxation remains active after edge springs cool and
  evaluates siblings simultaneously. Bounded root substeps let the scaffold
  converge before leaf constraints settle. Escape coplanar saddles using the
  crown's own frame, never camera axes or fixed slots; a six-peer planar seed
  must occupy three dimensions at rest. Sparse two/three-peer roots are exempt.
  Every shared 3D cloud puts all nodes at the same semantic depth on one
  spherical layer, including its first visible frame and every force tick.
  Direct Brain branches always occupy layer one, anchored at the original close
  spacing of 1.4 taxonomy spring lengths subject to node clearance. Cube-root
  increments distribute later layers through a spherical cloud; deeper branches
  never enlarge the Brain-to-first-layer gap or unchanged inner layers.
  Layer radii reserve node-size
  clearance and surface packing space and expand collectively with density;
  a busy branch cannot drift onto a deeper layer. The final coupled constraint
  uses d3's own damped integration to resolve avoidance, outward edges and
  recursive crown boundaries through bounded great-circle corrections. Do not
  restore competing Cartesian 3D corrections followed by radial projection.
  Only topology, glyph sizes and spacing determine nominal radii, never activity
  or paint. Private 3D depth follows exact parent ancestry, including Articles;
  the 2D renderer's terminal Article paint tier is never physical depth.
  The separate 2D layout and semantic spring strengths remain unchanged.
  Crown membership follows exact parentId ancestry at every fork. Current sibling
  directions define moving boundaries, with bounded capacity bias from descendant
  avoidance footprints. Reserve full avoidance radii, not only visible cores.
  Coarse crown rotations and fine contact solving share the existing scene tick;
  only Brain is pinned. Do not substitute fixed sectors or camera-dependent layout.
  Direct-fan capacity and persistent violations expand whole affected layers
  with outward clearance propagation, never unchanged inner layers. Carry
  expanded radii and solver progress with positions, velocities and alpha across
  physics-identical rebuilds. Paint and approval cannot restart solving.
  Alpha is a cooling schedule, not convergence evidence. Finish only after eight
  cold, geometrically valid, low-motion ticks. Keep the twelve-pass, eight-
  expansion-per-layer and 880-tick bounds; expose unresolved needs-capacity or
  stalled diagnostics and a one-shot warning rather than freezing as settled
  or adding an unbounded independent loop. Front/back projection overlap remains
  possible as the 3D view rotates.
  Valid pending Link additions from `graph.link_proposals` preview the eventual
  visual spring, degree-based radius and actual link gradient only at the Scene
  boundary. The accepted model remains the sole source for thinking paths and
  semantic use. A proposal springs into place and glows while awaiting Review;
  approval retains that physical union until the fresh accepted snapshot replaces
  it, then changes paint without reheating or changing curve geometry. Private
  force input order is canonical so hot motion survives that handoff too.
  Rejection removes only the rejected preview and lets remaining constraints
  settle; it never restores an old whole-graph snapshot. The existing activity
  stream carries exact decision endpoints and original approval time for the
  four-second confirmation glow. Polls, reconnects and cloud rebuilds do not
  replay an existing entrance or approval. Review paint never changes the active
  Task's accepted thinking path.
  Every cloud connects cross-links directly to their exact endpoints. Links at
  the same level follow their shell; links between levels may transition across
  shells. The route interpolates actual endpoint radii and angles, with only
  sub-half-percent tessellation compensation. Never add article-size clearance,
  raised radial leaders or an extra outward bow. The old Link curve control is
  retired; its saved field remains compatibility data only. Normal, pending and
  approved paint share the same route, and streaks clip its individual segments
  without shortcutting bends. This presentation never changes force state or
  introduces graph authority.
- The Reader is the single Article and Source viewer. Knowledge and Source
  explorers are dockable views, not separate truth stores.
- External applications and undocked module panes are native `xdg_toplevel`
  compositor clients, never embedded mirrors. Hyprland's `lua:obsidience`
  layout projects one Surface grid and one shortcut contract onto both, while
  one Shell palette feeds internal `PaneFrame` controls, compositor chrome, and
  bounded native theme adapters. Application content remains owned by the
  application. Module clients remain in the native window inventory but are
  filtered from the Applications taskbar projection by their exact `pane_id`.
- Hardware is Obsidience's native monitoring module, using the ordinary pane
  placement and the existing `ShellApi.theme` instance. Its read-only
  `/api/hardware/monitor` projection reuses host sensor inventory and psutil;
  one bounded on-demand cache owns sample deltas, with no background sampler
  or second telemetry store. Charts retain bounded UI-only history, skip
  duplicate samples, and show gaps for unavailable/reset measurements. Keep
  process identity and counter-reset guards; the process table is read-only.
  Use compact TMOG-style Summary, Performance device navigation, and Processes
  views. Keep physical-network totals separate from loopback/virtual details
  and omit unsupported optional sensors. Public psutil iteration supplies the
  bounded process census; scheduling delay is not a sensor failure.
  Model residency, microphone/speaker/camera choices, and Pocket voice belong
  under Settings → AI & Voice using their existing APIs. Opening a monitoring
  or settings view never changes saved configuration. TMOG is a visual
  reference only; do not restore its external Hardware launcher or theme shim.
- Reader docking has one primary-owned atomic layout: Knowledge defaults left,
  Source defaults right, same-side explorers stack evenly, and collapsed
  explorers use a narrow rail. A docked Knowledge or Source view renders only
  inside Reader's dock tree; no standalone toplevel exists while it is docked.
  It follows Reader between Surfaces; detaching it creates and maps exactly one
  `FloatingWindow` on its intended `screen`. Hyprland places that native pane,
  and `PanePlacement` mirrors the settled result. Never add a web Reader, second
  document loader, or display-transfer path for docking.
- The native Terminal owns the `obsidience-ui` tmux session view and window
  sizing. Its fixed readable font and viewport follow the pane, and tmux uses
  the largest attached client so the full pane reflows without letterboxing.
  DP-4 is a passive mirror and must not constrain Obsidience's terminal size.

After every project change, rebuild as needed and restart every affected live
process so the owner can test the exact current state. A compositor-config or
session-boundary change requires a fresh greetd/Hyprland session; ordinary pane
and service changes restart only their affected processes. Verify the API and
the actual target Surface, not only command exit codes.

## Required validation

Before handoff:

1. run the vault validator and require zero broken load-bearing edges;
2. compile all Python source files;
3. run `pnpm --dir obsidience/ui typecheck` and
   `pnpm --dir obsidience/ui build`;
4. confirm Source integrity and the exact Tool-to-Skill-to-Capability pairing;
5. restart affected live processes and verify the greetd/Hyprland session and
   its exact units;
6. verify `/api/status`, `/api/graph`, `/api/tasks`, and the actual target
   Surface;
7. ensure accepted graph text contains no stale framework architecture or Tool
   claim without its exact Capability binding and singular entrypoint.

Realtime keeps the fixed Pipecat/NeMo speech connection available between
requests. Each requested outcome completes as an ordinary Task while the
connection remains enabled; starting or stopping audio creates no work Task,
Thinking Packet, or model selection of its own.

An idle enabled speech connection is not a global scheduler pause. Foreground
admission, speech transitions and the existing physical GPU reservations gate
work that actually conflicts. User-requested research remains explicitly bound
to its creating execution; arguments cannot manufacture that provenance.
No additional scheduler, resident model, or per-Agent physics engine is needed.
Tool calls remain steps, and causal order never creates Task hierarchy.

Create a timestamped rollback copy before broad or destructive changes. Keep
unrelated user work intact.


## Obsidience Computer Use repair: 2026-09-05

- `computer.act` uses the current Shell Scene and the same native Wayshot
  toplevel capture as `computer.observe`; it no longer contacts retired KWin
  or JARVIS observation/CUA sockets. The obsolete `jarvis-cua-driver.service`
  is masked, stopped and has no socket. Its old refresh timer is disabled; a
  retired recovery guardian had been pulling it back through Hermes dependencies.
  Keep that obsolete actuation owner masked.
- Gemma selects one point from the image attached by the immediately preceding
  `computer.observe`. Model coordinates are integers 0-999 on that image's
  normalized 1000-by-1000 grid. The executor binds them privately to those exact
  image bytes and a one-use process/window/capture lease; any intervening Tool,
  invalid response, completion or cancellation discards that opportunity.
  Points, pixels and leases never enter durable trace, Source or Vault.
- The existing Shell window adapter owns coordinate conversion and one
  foreground click. It validates the process start time, exact window identity,
  geometry, image age (at most ten seconds), focus, awake/unlocked Surface,
  actual pointer position and occluding layers. There is no OCR or pixel-score
  gate, point relocation, additional model, game-specific Tool or input daemon.
  Animated TFT controls disproved both exact-pixel and correlation thresholds
  as reliable semantic target checks; do not restore them as proof of identity.
- The private two-phase Wayland virtual-pointer client provides framed motion,
  one committed down/up, and actual sync callback receipts with explicit output
  binding. Its immutable selection is `/var/lib/ai/opt/obsidience-pointer/current`;
  source/build and narrow upstream reuse provenance live in the Shell adapter
  and its existing REUSE_MANIFEST.json. A sync receipt proves protocol delivery,
  never semantic application success.
- The original requesting Shell connection, lock generation, exact revision
  and one-use token are guarded immediately before commit. STOP closes that
  connection; uncertain delivery is never replayed. Input scope permits one
  attempt. State scope permits at most three distinct steps, each requiring a
  new observe image after the preceding verified step; failed or uncertain input
  ends that sequence. After acknowledgement, a fresh observation-only
  lease may admit changed title/layout for the same process/window and supplies
  the post-image; it never authorizes another click. Completion verifies input
  delivery and fresh post-evidence, while Gemma evaluates the visible outcome.
  A requested label or `game_started` postcondition cannot assert success.
- Quickshell Source changes use the existing guarded
  `obsidience/shell/session/restart-shell` helper. The supported
  `Quickshell.watchFiles = false` setting prevents automatic overlapping QML
  generations from competing for the sole Shell command socket; do not replace
  this with retry timers or a second listener. The helper still refuses a
  normal restart during an active secure lock.
- Source preimages, diagnostic fixture and acceptance evidence are under
  `/home/wissenschafter/backups/obsidience-hyprland-click-20260905-215010`.
- Realtime microphone startup accepts complete clocked silent PCM. Quiet
  samples are not a readiness failure. Unique device resolution, hardware mute
  and UAC checks, exact packet count and delivery timeout remain authoritative;
  do not add signal-amplitude thresholds or repeated startup delays. This fixes
  the OBSBOT startup rejection `selected microphone produced only digital
  silence` without changing audio defaults or adding another microphone path.
  Backup: `/home/wissenschafter/backups/obsidience-microphone-silence-20260905-224510`.


## Contextual Executive admission and completion: 2026-09-05

The existing Conversation coordinator prepares current context before semantic
Task admission. Bounded non-reasoning admission through the configured Executive model selects
only the assigned Query or Computer Use Task from the accepted outcome catalog,
exact request and current semantic Shell Scene. A context-dependent request may
use one further grounding pass over recent dialogue and bounded historical Tool evidence. It creates no additional Agent, Task, model,
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

## Read-path latency contract

Repeated status and scheduler reads reuse syntax, not authority. The existing
Vault reader rereads each file and memoizes YAML/Markdown parsing by exact
decoded content plus relative link-resolution path, bounded to 512 entries
and 128 Ki characters per cached Article. It returns private mutable copies
and projects Task state from SQLite on every read. File existence, checkout,
expiry, review and Source integrity decisions remain fresh. Changed bytes,
including same-size/same-mtime edits, cannot reuse an old parse. Oversized
Articles bypass the cache. Source evidence retains per-read validation.
The two existing safe YAML loaders use installed LibYAML when available,
retaining timestamp and duplicate-key rules; serialization is unchanged.
Resource admission reuses the current scheduler pass's accepted snapshot;
actual resource reservations and execution authority are still rechecked.


Realtime admission repair, 2026-09-11: the selector returns one exact closed
choice binding outcome, target, and input/state scope together; the controller
maps that tuple to an assigned Task. It cannot independently predict contradictory
fields. Registered aliases come from the existing application registry.
Classify the current owner message against the accepted catalog and fresh scene
first. Only an explicit context choice supplies the existing bounded history for
one further grounding pass, under the same model lease. A named current request
must not inherit earlier assistant refusals or invented capabilities. Execution
still receives its normal Immediate Observations; no history or context limit
is deleted, compacted, or lowered by admission. Ambiguous references can clarify.
Polite execution requests remain effects; explanations, quotations, withdrawals,
and bare corrections do not. Choice and context usage are diagnostic routing,
not an additional Agent, Tool, memory store, or current-text keyword fallback.
An interactive Query attempt to task.create Computer Use is rejected before
dispatch and requests the existing recheck once, only before effects, delegation,
or applied/pending owner clarifications. The original user turn remains bound;
attempted Tool target arguments do not authorize its corrected operation.
Cancellation, missing assignments, or an unresolved recheck prevent execution.
The trace retains an undispatched attempted call, never synthetic effect success.
