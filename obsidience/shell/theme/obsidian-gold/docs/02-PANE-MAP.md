# Pane and surface map

Inspected registry: `obsidience/shell/qml/workspace/PaneWorkspace.qml`. This file remains the sole pane registry. The map below is a design plan, not a second runtime registration list. Existing component paths are relative to the repository; proposed paths are explicitly labeled.

## Inventory

| Design | Stable pane | State | Integration path |
|---|---|---|---|
| [Desktop overview](../preview/index.html#desktop) | `composition/transient` | Composition | `obsidience/shell/qml/surfaces/wordmark/StageContent.qml` |
| [Computer / Conversation](../preview/index.html#chat) | `chat` | Existing | `obsidience/shell/qml/panes/chat/ChatPane.qml` |
| [Library / Capability catalog](../preview/index.html#library) | `library` | Existing | `obsidience/shell/qml/panes/library/LibraryPane.qml` |
| [Tasks / Execution queue](../preview/index.html#tasks) | `tasks` | Existing | `obsidience/shell/qml/panes/tasks/TasksPane.qml` |
| [Reviews / Change approval](../preview/index.html#reviews) | `reviews` | Existing | `obsidience/shell/qml/panes/reviews/ReviewsPane.qml` |
| [Reader / Article and evidence](../preview/index.html#reader) | `reader` | Existing | `obsidience/shell/qml/panes/reader/ReaderPane.qml` |
| [Knowledge / Explorer](../preview/index.html#knowledge) | `knowledge` | Existing | `obsidience/shell/qml/panes/knowledge/KnowledgePane.qml` |
| [Graph / Knowledge](../preview/index.html#graph-knowledge) | `knowledge-graph` | Existing | `obsidience/shell/qml/panes/graph/GraphViewerPane.qml` |
| [Graph / Historical memory](../preview/index.html#graph-memory) | `knowledge-graph` | Existing | `obsidience/shell/qml/panes/graph/GraphViewerPane.qml` |
| [Graph / Code](../preview/index.html#graph-code) | `knowledge-graph` | Existing | `obsidience/shell/qml/panes/graph/GraphViewerPane.qml` |
| [Source / Provenance explorer](../preview/index.html#source) | `source` | Existing | `obsidience/shell/qml/panes/source/SourcePane.qml` |
| [Models / Residency and capacity](../preview/index.html#models) | `status` | Existing | `obsidience/shell/qml/panes/models/StatusPane.qml` |
| [Hardware / Performance](../preview/index.html#hardware) | `hardware` | Existing | `obsidience/shell/qml/panes/hardware/HardwarePane.qml` |
| [Hardware / Processes](../preview/index.html#hardware-processes) | `hardware` | Existing | `obsidience/shell/qml/panes/hardware/HardwarePane.qml` |
| [Camera / Preview](../preview/index.html#camera) | `camera` | Existing | `obsidience/shell/qml/panes/camera/CameraPane.qml` |
| [Media / Library and playback](../preview/index.html#media) | `media` | Existing | `obsidience/shell/qml/panes/media/MediaPane.qml` |
| [Media / Discovery and readiness](../preview/index.html#media-discover) | `media` | Existing | `obsidience/shell/qml/panes/media/MediaPane.qml` |
| [Applications / Installed software](../preview/index.html#applications) | `applications` | Existing | `obsidience/shell/qml/panes/applications/ApplicationsPane.qml` |
| [Applications / Updates](../preview/index.html#application-updates) | `applications` | Proposed extension | `obsidience/shell/qml/panes/applications/ApplicationsPane.qml` |
| [Terminal / Console and agent canvas](../preview/index.html#terminal) | `terminal` | Existing | `obsidience/shell/qml/panes/terminal/TerminalPane.qml` |
| [Development / Workspace composition](../preview/index.html#development) | `composition/transient` | Composition | `obsidience/shell/qml/workspace/PaneWorkspace.qml` |
| [TFT / Ledger companion](../preview/index.html#tft) | `tft-companion` | Existing | `obsidience/shell/qml/panes/tft/TftCompanionPane.qml` |
| [Settings / Graph presentation](../preview/index.html#settings-graph) | `settings` | Existing | `obsidience/shell/qml/panes/settings/graph/GraphSettings.qml` |
| [Settings / Input](../preview/index.html#settings-input) | `settings` | Existing | `obsidience/shell/qml/panes/settings/input/InputSettings.qml` |
| [Settings / Workspace](../preview/index.html#settings-workspace) | `settings` | Existing | `obsidience/shell/qml/panes/settings/workspace/WorkspaceSettings.qml` |
| [Settings / AI & Voice](../preview/index.html#settings-ai-voice) | `settings` | Existing | `obsidience/shell/qml/panes/settings/ai_voice/AiVoiceSettings.qml` |
| [Settings / Obsidience Themes](../preview/index.html#appearance) | `settings` | Proposed extension | `obsidience/shell/qml/panes/settings/appearance/AppearanceSettings.qml (proposed)` |
| [Launcher / Global search](../preview/index.html#launcher) | `composition/transient` | Proposed extension | `obsidience/shell/qml/workspace/ApplicationLauncher.qml` |
| [Workspace overview / Window switcher](../preview/index.html#workspaces) | `composition/transient` | Proposed extension | `obsidience/shell/qml/workspace/PaneWorkspace.qml + adapter/windows` |
| [Quick settings / System tray](../preview/index.html#quick-settings) | `composition/transient` | Missing presentation | `obsidience/shell/qml/workspace/QuickSettings.qml (proposed)` |
| [Notifications / History and focus](../preview/index.html#notifications) | `composition/transient` | Missing presentation | `obsidience/shell/qml/workspace/NotificationCenter.qml (proposed)` |
| [Settings / Network & VPN](../preview/index.html#network) | `settings` | Missing presentation | `obsidience/shell/qml/panes/settings/network/NetworkSettings.qml (proposed)` |
| [Settings / Bluetooth](../preview/index.html#bluetooth) | `settings` | Missing presentation | `obsidience/shell/qml/panes/settings/bluetooth/BluetoothSettings.qml (proposed)` |
| [Settings / Sound & media](../preview/index.html#audio) | `settings` | Missing presentation | `obsidience/shell/qml/panes/settings/audio/AudioSettings.qml (proposed)` |
| [Settings / Displays](../preview/index.html#displays) | `settings` | Missing control surface | `obsidience/shell/qml/panes/settings/displays/DisplaySettings.qml (proposed)` |
| [Settings / Accessibility](../preview/index.html#accessibility) | `settings` | Missing presentation | `obsidience/shell/qml/panes/settings/accessibility/AccessibilitySettings.qml (proposed)` |
| [Settings / Keyboard shortcuts](../preview/index.html#shortcuts) | `settings` | Missing editor | `obsidience/shell/qml/panes/settings/input/InputSettings.qml` |
| [Settings / Power & idle](../preview/index.html#power) | `settings` | Missing presentation | `obsidience/shell/qml/panes/settings/power/PowerSettings.qml (proposed)` |
| [Session / Lock and power actions](../preview/index.html#session) | `composition/transient` | Missing unified surface | `obsidience/shell/qml/workspace/SessionMenu.qml (proposed)` |
| [Lock screen / Native secure surface](../preview/index.html#lock) | `composition/transient` | Existing owner; redesign | `obsidience/shell/qml/lock/` |
| [Login / Session entry](../preview/index.html#login) | `composition/transient` | Design only | `obsidience/shell/session/greetd.toml + supported greeter integration (proposed)` |
| [Permissions / Privileged action](../preview/index.html#permissions) | `composition/transient` | Acceptance gap | `Existing system polkit + supported native authentication agent` |
| [Files / General filesystem](../preview/index.html#files) | `composition/transient` | External integration | `Existing native file manager + XDG portals; appearance adapter (proposed)` |
| [Files / Open and save dialog](../preview/index.html#file-dialog) | `composition/transient` | External integration | `xdg-desktop-portal FileChooser + active backend` |
| [Clipboard / Private history](../preview/index.html#clipboard) | `composition/transient` | Missing optional feature | `obsidience/shell/qml/workspace/ClipboardHistory.qml (proposed)` |
| [Capture / Screenshot and sharing](../preview/index.html#capture) | `composition/transient` | Missing presentation | `obsidience/shell/qml/workspace/CaptureSheet.qml (proposed)` |
| [Clock / Calendar](../preview/index.html#calendar) | `composition/transient` | Missing presentation | `obsidience/shell/qml/workspace/ClockCalendar.qml (proposed)` |
| [Settings / Removable devices](../preview/index.html#storage) | `settings` | Missing presentation | `obsidience/shell/qml/panes/settings/storage/StorageSettings.qml (proposed)` |
| [Settings / Printers](../preview/index.html#printers) | `settings` | Missing presentation | `obsidience/shell/qml/panes/settings/printers/PrinterSettings.qml (proposed)` |
| [Settings / Privacy & permissions](../preview/index.html#privacy) | `settings` | Missing overview | `obsidience/shell/qml/panes/settings/privacy/PrivacySettings.qml (proposed)` |
| [Settings / Defaults & locale](../preview/index.html#defaults) | `settings` | Missing presentation | `obsidience/shell/qml/panes/settings/defaults/DefaultsSettings.qml (proposed)` |
| [Settings / Startup applications](../preview/index.html#autostart) | `settings` | Missing presentation | `obsidience/shell/qml/panes/settings/startup/StartupSettings.qml (proposed)` |
| [Settings / Accounts & identity](../preview/index.html#accounts) | `settings` | Missing presentation | `obsidience/shell/qml/panes/settings/accounts/AccountSettings.qml (proposed)` |

## Per-design specifications

Each design has an exported PNG and an interactive atlas route. Action controls in the atlas are inert system-wise; they demonstrate layout and visual states only.

### 01. Desktop overview

[PNG](../designs/desktop.png) · [Interactive design](../preview/index.html#desktop)

**Classification:** Composition. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/surfaces/wordmark/StageContent.qml`

**Owner:** Stage + PaneWorkspace + existing API projections.

**Workflow:** Inspect system, queued work, recent receipts and the current workspace without leaving the desktop. This is a composition, not another scheduler or agent.

**Acceptance boundary:** Offline and model-unavailable states leave launcher, windows, clock and system controls usable. No invented health score or agent roster.

### 02. Computer / Conversation

[PNG](../designs/chat.png) · [Interactive design](../preview/index.html#chat)

**Classification:** Existing. **Pane:** `chat`.

**Where it goes:** `obsidience/shell/qml/panes/chat/ChatPane.qml`

**Owner:** Executive conversation + RealtimeState.

**Workflow:** Converse with Computer, review action receipts and select the existing voice mode. Keep the composer, context budget and stop control visible.

**Acceptance boundary:** Stopping dispatch cancels through the existing owner. Audio indicators reflect actual capture state; the theme never acquires a microphone.

### 03. Library / Capability catalog

[PNG](../designs/library.png) · [Interactive design](../preview/index.html#library)

**Classification:** Existing. **Pane:** `library`.

**Where it goes:** `obsidience/shell/qml/panes/library/LibraryPane.qml`

**Owner:** Existing Library projection and Reader.

**Workflow:** Browse Tasks, paired Tool–Skill entries and Agents. Filters select existing identities, then open the one Reader.

**Acceptance boundary:** No fictional ontology categories, no duplicate Article writer, and no click that executes a Tool simply because it appears in the catalog.

### 04. Tasks / Execution queue

[PNG](../designs/tasks.png) · [Interactive design](../preview/index.html#tasks)

**Classification:** Existing. **Pane:** `tasks`.

**Where it goes:** `obsidience/shell/qml/panes/tasks/TasksPane.qml`

**Owner:** Task runtime, scheduler, existing ADK execution.

**Workflow:** See trigger, Agent, model, runtime status and receipts together. Open the Task definition separately from a particular activation.

**Acceptance boundary:** Runtime transitions never rewrite the Article. Cancel, retry and activation actions keep their existing permission and uncertain-outcome semantics.

### 05. Reviews / Change approval

[PNG](../designs/reviews.png) · [Interactive design](../preview/index.html#reviews)

**Classification:** Existing. **Pane:** `reviews`.

**Where it goes:** `obsidience/shell/qml/panes/reviews/ReviewsPane.qml`

**Owner:** Existing Review owner and revision-checked writer.

**Workflow:** Inspect proposed text and relationship changes alongside evidence; accept or reject one exact revision.

**Acceptance boundary:** A stale revision disables approval and requests a new comparison. Green text indicates additions, not proof of factual correctness.

### 06. Reader / Article and evidence

[PNG](../designs/reader.png) · [Interactive design](../preview/index.html#reader)

**Classification:** Existing. **Pane:** `reader`.

**Where it goes:** `obsidience/shell/qml/panes/reader/ReaderPane.qml`

**Owner:** Single native Reader + existing writers.

**Workflow:** Read an Article, inspect links, evidence and agent checkouts, edit through revision checks; dock Knowledge and Source at the edges.

**Acceptance boundary:** One viewer, one loaded identity; binary, truncated, read-only and externally managed Sources remain clearly distinguished.

### 07. Knowledge / Explorer

[PNG](../designs/knowledge.png) · [Interactive design](../preview/index.html#knowledge)

**Classification:** Existing. **Pane:** `knowledge`.

**Where it goes:** `obsidience/shell/qml/panes/knowledge/KnowledgePane.qml`

**Owner:** Knowledge projection + PaneDockLayout.

**Workflow:** Search the real Article tree grouped by agent assignment; open selected refs in Reader or locate them in the shared graph.

**Acceptance boundary:** Node names and assignments come from graph.navigation. Docking changes the existing layout record, not a second file tree or renderer.

### 08. Graph / Knowledge

[PNG](../designs/graph-knowledge.png) · [Interactive design](../preview/index.html#graph-knowledge)

**Classification:** Existing. **Pane:** `knowledge-graph`.

**Where it goes:** `obsidience/shell/qml/panes/graph/GraphViewerPane.qml`

**Owner:** Single canonical graph presenter; frame-viewer pane.

**Workflow:** Navigate the six Article types and current agent identities with an inspector and readable evidence list.

**Acceptance boundary:** Theme changes must not reheat simulation, rewrite positions, invent links or alter selection/picking. Miniature atlas graph is an illustrative diagram only.

### 09. Graph / Historical memory

[PNG](../designs/graph-memory.png) · [Interactive design](../preview/index.html#graph-memory)

**Classification:** Existing. **Pane:** `knowledge-graph`.

**Where it goes:** `obsidience/shell/qml/panes/graph/GraphViewerPane.qml`

**Owner:** Existing Hindsight provider + same viewer.

**Workflow:** Switch the existing viewer to Memory, select a bank and time range, open an exact returned memory record.

**Acceptance boundary:** Memory records remain provider records, never invented Article types; chronology and actual returned IDs remain intact.

### 10. Graph / Code

[PNG](../designs/graph-code.png) · [Interactive design](../preview/index.html#graph-code)

**Classification:** Existing. **Pane:** `knowledge-graph`.

**Where it goes:** `obsidience/shell/qml/panes/graph/GraphViewerPane.qml`

**Owner:** Existing code graph provider + same viewer.

**Workflow:** Switch to Code, select a project, inspect symbol dependencies and observed tool activity.

**Acceptance boundary:** No second code graph solver. Proximity does not imply dependency; activity labels never expose hidden reasoning or imply success.

### 11. Source / Provenance explorer

[PNG](../designs/source.png) · [Interactive design](../preview/index.html#source)

**Classification:** Existing. **Pane:** `source`.

**Where it goes:** `obsidience/shell/qml/panes/source/SourcePane.qml`

**Owner:** Immutable Source + system projection + Reader.

**Workflow:** Inspect System, Knowledge and Evidence trees, coverage and checkouts. Keep path, provenance and read-only status obvious.

**Acceptance boundary:** Source is not a general-purpose file manager. Opening evidence never grants execution or changes its immutable provenance.

### 12. Models / Residency and capacity

[PNG](../designs/models.png) · [Interactive design](../preview/index.html#models)

**Classification:** Existing. **Pane:** `status`.

**Where it goes:** `obsidience/shell/qml/panes/models/StatusPane.qml`

**Owner:** Model admission and residency owner.

**Workflow:** Inspect available task models, allowed GPUs, context limits and measured performance. Make configuration and benchmark costs explicit.

**Acceptance boundary:** A presentation theme never loads, evicts or benchmarks a model. Unknown performance is unavailable, not a fabricated estimate.

### 13. Hardware / Performance

[PNG](../designs/hardware.png) · [Interactive design](../preview/index.html#hardware)

**Classification:** Existing. **Pane:** `hardware`.

**Where it goes:** `obsidience/shell/qml/panes/hardware/HardwarePane.qml`

**Owner:** Existing read-only hardware monitor.

**Workflow:** Inspect Summary, CPU, memory, GPUs, storage and network with one selected resource and bounded charts.

**Acceptance boundary:** Keep on-demand sampling, missing-data gaps and read-only process identity. No new sampler thread or polling daemon.

### 14. Hardware / Processes

[PNG](../designs/hardware-processes.png) · [Interactive design](../preview/index.html#hardware-processes)

**Classification:** Existing. **Pane:** `hardware`.

**Where it goes:** `obsidience/shell/qml/panes/hardware/HardwarePane.qml`

**Owner:** Same hardware monitor.

**Workflow:** Sort read-only processes by resource use; show sample time, process identity and unavailable measurements.

**Acceptance boundary:** Do not quietly add kill-process controls to this read-only interface. Sorting remains presentation only.

### 15. Camera / Preview

[PNG](../designs/camera.png) · [Interactive design](../preview/index.html#camera)

**Classification:** Existing. **Pane:** `camera`.

**Where it goes:** `obsidience/shell/qml/panes/camera/CameraPane.qml`

**Owner:** Existing camera owner; video-only preview.

**Workflow:** See the selected camera and explicit preview state, retry a failed preview, and open AI & Voice device settings.

**Acceptance boundary:** No microphone, no second capture owner, no camera-power change on close. A closed preview must never be shown as recording.

### 16. Media / Library and playback

[PNG](../designs/media.png) · [Interactive design](../preview/index.html#media)

**Classification:** Existing. **Pane:** `media`.

**Where it goes:** `obsidience/shell/qml/panes/media/MediaPane.qml`

**Owner:** Existing media/TV owner and command receipts.

**Workflow:** Select a library item, target playback, resume or seek, and verify the matching command receipt.

**Acceptance boundary:** Keep target identity and command status explicit; no invented universal playback authority or second media server.

### 17. Media / Discovery and readiness

[PNG](../designs/media-discover.png) · [Interactive design](../preview/index.html#media-discover)

**Classification:** Existing. **Pane:** `media`.

**Where it goes:** `obsidience/shell/qml/panes/media/MediaPane.qml`

**Owner:** Existing media search and acquisition owner.

**Workflow:** Search metadata, choose season/episode, inspect eligible sources and readiness before sending an authorized acquisition request.

**Acceptance boundary:** Distinguish metadata match, source availability, acquisition eligibility, command accepted and actual playback.

### 18. Applications / Installed software

[PNG](../designs/applications.png) · [Interactive design](../preview/index.html#applications)

**Classification:** Existing. **Pane:** `applications`.

**Where it goes:** `obsidience/shell/qml/panes/applications/ApplicationsPane.qml`

**Owner:** Existing Applications + PackageKit adapter.

**Workflow:** Find installed software, launch through the existing app owner, search packages and inspect install/remove confirmation.

**Acceptance boundary:** Package metadata is untrusted display content; launching and package mutations retain their own validation and authorization.

### 19. Applications / Updates

[PNG](../designs/application-updates.png) · [Interactive design](../preview/index.html#application-updates)

**Classification:** Proposed extension. **Pane:** `applications`.

**Where it goes:** `obsidience/shell/qml/panes/applications/ApplicationsPane.qml`

**Owner:** Existing PackageKit adapter; extend transaction projection.

**Workflow:** Inspect the update set, dependencies, restart requirements and transaction history before applying a system update.

**Acceptance boundary:** Never perform Arch partial upgrades; expose transaction failure honestly. Existing install/search does not prove update UI completeness.

### 20. Terminal / Console and agent canvas

[PNG](../designs/terminal.png) · [Interactive design](../preview/index.html#terminal)

**Classification:** Existing. **Pane:** `terminal`.

**Where it goes:** `obsidience/shell/qml/panes/terminal/TerminalPane.qml`

**Owner:** Existing persistent obsidience-ui tmux view.

**Workflow:** Keep Local Console, Active Trace and Agent Canvas as views of the existing terminal owner, with explicit session labels and copy/paste.

**Acceptance boundary:** Theme reload cannot detach, recreate or replace tmux sessions. ANSI colors retain distinct semantics on an opaque background.

### 21. Development / Workspace composition

[PNG](../designs/development.png) · [Interactive design](../preview/index.html#development)

**Classification:** Composition. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/workspace/PaneWorkspace.qml`

**Owner:** Existing Source + Reader + Terminal + Graph Code.

**Workflow:** Arrange the existing code explorer, terminal, Reader and code graph as a workspace; external editors remain native windows.

**Acceptance boundary:** Do not build a duplicate IDE, source writer or window manager to imitate an old concept image.

### 22. TFT / Ledger companion

[PNG](../designs/tft.png) · [Interactive design](../preview/index.html#tft)

**Classification:** Existing. **Pane:** `tft-companion`.

**Where it goes:** `obsidience/shell/qml/panes/tft/TftCompanionPane.qml`

**Owner:** Existing read-only TFT ledger WebEngine view.

**Workflow:** Read round, board, shop, items, observations and historical decisions from the ledger.

**Acceptance boundary:** Visual refresh adds no gameplay control, no second state recorder and no training workload. Stale observations must be labeled.

### 23. Settings / Graph presentation

[PNG](../designs/settings-graph.png) · [Interactive design](../preview/index.html#settings-graph)

**Classification:** Existing. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/graph/GraphSettings.qml`

**Owner:** Existing graph-settings owner.

**Workflow:** Choose presentation profile, graph Surface and existing layout controls without altering graph semantics.

**Acceptance boundary:** Do not add a second graph or fixed branch sectors; style-only edits leave simulation state intact.

### 24. Settings / Input

[PNG](../designs/settings-input.png) · [Interactive design](../preview/index.html#settings-input)

**Classification:** Existing. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/input/InputSettings.qml`

**Owner:** Existing compositor input projection.

**Workflow:** Inspect the applied keyboard and mouse profile with hardware and effective sensitivity separated.

**Acceptance boundary:** Do not create per-Surface sensitivity, a second mouse profile store or direct pane-issued compositor commands.

### 25. Settings / Workspace

[PNG](../designs/settings-workspace.png) · [Interactive design](../preview/index.html#settings-workspace)

**Classification:** Existing. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/workspace/WorkspaceSettings.qml`

**Owner:** SurfaceLayout + PanePlacement + compositor adapter.

**Workflow:** Configure each Surface grid and the existing native tile/OLED behavior.

**Acceptance boundary:** Keep one 10-px grid, 5-px compositor-owned gaps and one persisted placement record per pane; no browser drag engine.

### 26. Settings / AI & Voice

[PNG](../designs/settings-ai-voice.png) · [Interactive design](../preview/index.html#settings-ai-voice)

**Classification:** Existing. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/ai_voice/AiVoiceSettings.qml`

**Owner:** Existing hardware slots + Realtime owner.

**Workflow:** Choose residency defaults and speech/camera devices; show when changes take effect.

**Acceptance boundary:** Opening Settings never starts audio or changes residency. Apply audio device changes through the existing session boundary.

### 27. Settings / Obsidience Themes

[PNG](../designs/appearance.png) · [Interactive design](../preview/index.html#appearance)

**Classification:** Proposed extension. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/appearance/AppearanceSettings.qml (proposed)`

**Owner:** Existing palette owner + staged theme catalog.

**Workflow:** Browse Obsidience Themes, preview a package and review the exact affected surfaces before applying it.

**Acceptance boundary:** This package is not currently activated. Keep palette.json authoritative, validate first, commit atomically, retain previous theme and provide rollback.

### 28. Launcher / Global search

[PNG](../designs/launcher.png) · [Interactive design](../preview/index.html#launcher)

**Classification:** Proposed extension. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/workspace/ApplicationLauncher.qml`

**Owner:** Existing launcher + explicit search providers.

**Workflow:** Search applications, panes, files and existing knowledge as clearly separated result groups.

**Acceptance boundary:** Basic launching requires no model. Search results never auto-execute shell text; AI interpretation is an explicit opt-in action.

### 29. Workspace overview / Window switcher

[PNG](../designs/workspaces.png) · [Interactive design](../preview/index.html#workspaces)

**Classification:** Proposed extension. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/workspace/PaneWorkspace.qml + adapter/windows`

**Owner:** Compositor Scene + existing placement owner.

**Workflow:** Inspect current windows and Surfaces; activate a specific native target or restore a named layout.

**Acceptance boundary:** The overview is a projection, not a second geometry owner. Native window identity and stale-revision handling remain mandatory.

### 30. Quick settings / System tray

[PNG](../designs/quick-settings.png) · [Interactive design](../preview/index.html#quick-settings)

**Classification:** Missing presentation. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/workspace/QuickSettings.qml (proposed)`

**Owner:** Existing Linux services via thin Shell adapters.

**Workflow:** Open audio, network, Bluetooth, power and device controls from a compact status drawer.

**Acceptance boundary:** Reuse StatusNotifierItem and service adapters. Do not embed the KDE or GNOME shell or register competing service owners.

### 31. Notifications / History and focus

[PNG](../designs/notifications.png) · [Interactive design](../preview/index.html#notifications)

**Classification:** Missing presentation. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/workspace/NotificationCenter.qml (proposed)`

**Owner:** Existing mako notification owner; bounded history projection.

**Workflow:** Read grouped notifications, activate explicit actions and toggle Do Not Disturb with app-level controls.

**Acceptance boundary:** Keep one org.freedesktop.Notifications owner. Do not start a Quickshell notification server beside mako; lock screen redacts private bodies.

### 32. Settings / Network & VPN

[PNG](../designs/network.png) · [Interactive design](../preview/index.html#network)

**Classification:** Missing presentation. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/network/NetworkSettings.qml (proposed)`

**Owner:** NetworkManager; thin typed Shell service adapter.

**Workflow:** Choose Wi-Fi/Ethernet/VPN, inspect link state and handle connection requests through the proper secret agent.

**Acceptance boundary:** Never store or log passwords in theme state; bounded transactions report real connection state, not only requested state.

### 33. Settings / Bluetooth

[PNG](../designs/bluetooth.png) · [Interactive design](../preview/index.html#bluetooth)

**Classification:** Missing presentation. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/bluetooth/BluetoothSettings.qml (proposed)`

**Owner:** BlueZ through one adapter.

**Workflow:** Discover, pair and disconnect devices with explicit pairing codes and per-device state.

**Acceptance boundary:** Never approve unknown pairing automatically; do not replace the system pairing agent without lifecycle handoff.

### 34. Settings / Sound & media

[PNG](../designs/audio.png) · [Interactive design](../preview/index.html#audio)

**Classification:** Missing presentation. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/audio/AudioSettings.qml (proposed)`

**Owner:** PipeWire/WirePlumber + MPRIS; Realtime remains separate.

**Workflow:** Choose system input/output, adjust app streams and control existing MPRIS players.

**Acceptance boundary:** No competing audio capture pipeline. Mute/input and playback indicators reflect actual stream state.

### 35. Settings / Displays

[PNG](../designs/displays.png) · [Interactive design](../preview/index.html#displays)

**Classification:** Missing control surface. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/displays/DisplaySettings.qml (proposed)`

**Owner:** Existing compositor adapter + SurfaceLayout.

**Workflow:** Inspect output geometry, scaling, refresh, HDR and VRR; preview changes with a keep/revert deadline.

**Acceptance boundary:** Never change GPU routing or accepted HDR defaults on theme apply. Any output transaction must have timed rollback and a recovery path.

### 36. Settings / Accessibility

[PNG](../designs/accessibility.png) · [Interactive design](../preview/index.html#accessibility)

**Classification:** Missing presentation. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/accessibility/AccessibilitySettings.qml (proposed)`

**Owner:** Qt accessibility + AT-SPI/upstream assistive tools.

**Workflow:** Adjust text scale, contrast, focus visibility, motion and keyboard navigation; inspect actual screen-reader support.

**Acceptance boundary:** Palette contrast alone is not accessibility conformance. Validate semantic labels, focus order, speech and magnification on the real native UI.

### 37. Settings / Keyboard shortcuts

[PNG](../designs/shortcuts.png) · [Interactive design](../preview/index.html#shortcuts)

**Classification:** Missing editor. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/input/InputSettings.qml`

**Owner:** Existing input/compositor adapter; no parallel shortcut store.

**Workflow:** Review current shortcuts and edit only supported commands with collision detection and rollback.

**Acceptance boundary:** Do not silently overwrite working tiling, recovery or accessibility shortcuts. Planned bindings require conflict review.

### 38. Settings / Power & idle

[PNG](../designs/power.png) · [Interactive design](../preview/index.html#power)

**Classification:** Missing presentation. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/power/PowerSettings.qml (proposed)`

**Owner:** Existing hypridle + logind + power-profiles-daemon.

**Workflow:** Inspect current power profile, lock/blank deadlines and inhibitors; expose platform-supported actions.

**Acceptance boundary:** Preserve this installation’s no-suspend policy. A theme does not rewrite idle/security listeners or allow applications to inhibit security locking.

### 39. Session / Lock and power actions

[PNG](../designs/session.png) · [Interactive design](../preview/index.html#session)

**Classification:** Missing unified surface. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/workspace/SessionMenu.qml (proposed)`

**Owner:** Existing LockController, logind and session helpers.

**Workflow:** Choose lock, sign out, restart or power off; inspect unsaved work and active tasks before destructive session actions.

**Acceptance boundary:** Never bind theme activation to a restart; do not imply lock complete before the existing owner confirms secure state.

### 40. Lock screen / Native secure surface

[PNG](../designs/lock.png) · [Interactive design](../preview/index.html#lock)

**Classification:** Existing owner; redesign. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/lock/`

**Owner:** Existing WlSessionLock + native PamContext.

**Workflow:** Restyle native identity and unlock controls on the existing opaque secure surface.

**Acceptance boundary:** The HTML sample is not a locker and accepts no credentials. Preserve black opaque output coverage, PAM isolation and fail-secure restart behavior.

### 41. Login / Session entry

[PNG](../designs/login.png) · [Interactive design](../preview/index.html#login)

**Classification:** Design only. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/session/greetd.toml + supported greeter integration (proposed)`

**Owner:** greetd and its chosen greeter.

**Workflow:** Present user/session selection and native authentication for a fresh login.

**Acceptance boundary:** Login and lock are different owners. No HTML password collection; no unreviewed greeter replacement or changes to active boot/session configuration.

### 42. Permissions / Privileged action

[PNG](../designs/permissions.png) · [Interactive design](../preview/index.html#permissions)

**Classification:** Acceptance gap. **Pane:** `none: composition or transient surface`.

**Where it goes:** `Existing system polkit + supported native authentication agent`

**Owner:** polkit; graphical agent integration must be verified.

**Workflow:** Show requesting app, exact action and consequences with a trusted native authentication prompt.

**Acceptance boundary:** Expected hyprpolkitagent package was absent during inspection; another registered agent must be checked before declaring the whole service absent. Never authenticate through webviews or AI.

### 43. Files / General filesystem

[PNG](../designs/files.png) · [Interactive design](../preview/index.html#files)

**Classification:** External integration. **Pane:** `none: composition or transient surface`.

**Where it goes:** `Existing native file manager + XDG portals; appearance adapter (proposed)`

**Owner:** Maintained upstream file manager, not Article/Source writer.

**Workflow:** Browse home/devices/trash, move files, inspect properties and conflicts in a normal native application.

**Acceptance boundary:** Source remains provenance explorer. Prefer theming and launching Dolphin or another maintained file manager over building a duplicate file engine.

### 44. Files / Open and save dialog

[PNG](../designs/file-dialog.png) · [Interactive design](../preview/index.html#file-dialog)

**Classification:** External integration. **Pane:** `none: composition or transient surface`.

**Where it goes:** `xdg-desktop-portal FileChooser + active backend`

**Owner:** Existing portal backend.

**Workflow:** Select a file or destination with clear filter, path, overwrite and sandbox permission boundaries.

**Acceptance boundary:** Do not bypass a sandbox with a custom raw filesystem chooser. Theme toolkit surfaces within supported limits.

### 45. Clipboard / Private history

[PNG](../designs/clipboard.png) · [Interactive design](../preview/index.html#clipboard)

**Classification:** Missing optional feature. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/workspace/ClipboardHistory.qml (proposed)`

**Owner:** One optional Wayland clipboard history provider.

**Workflow:** Search a bounded local history, pin deliberate snippets, clear items and pause collection.

**Acceptance boundary:** Basic clipboard already exists. History is opt-in, secret/private selections excluded where supported, and lock clears or hides content; never harvest clipboard into AI memory.

### 46. Capture / Screenshot and sharing

[PNG](../designs/capture.png) · [Interactive design](../preview/index.html#capture)

**Classification:** Missing presentation. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/workspace/CaptureSheet.qml (proposed)`

**Owner:** Existing capture/portal owner + ScreenCast session lifecycle.

**Workflow:** Choose one window, region or output; inspect save destination and explicit recording/sharing state.

**Acceptance boundary:** Keep visible recording indicators and stop/revoke controls. Do not create an additional continuous capture service or expose hidden windows.

### 47. Clock / Calendar

[PNG](../designs/calendar.png) · [Interactive design](../preview/index.html#calendar)

**Classification:** Missing presentation. **Pane:** `none: composition or transient surface`.

**Where it goes:** `obsidience/shell/qml/workspace/ClockCalendar.qml (proposed)`

**Owner:** System clock + explicit optional calendar provider.

**Workflow:** View date and timezone with an optional separately connected event source.

**Acceptance boundary:** No invented meetings. Offline calendar works without AI or account integration; source timezone is visible.

### 48. Settings / Removable devices

[PNG](../designs/storage.png) · [Interactive design](../preview/index.html#storage)

**Classification:** Missing presentation. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/storage/StorageSettings.qml (proposed)`

**Owner:** UDisks2 + existing hardware read-only telemetry.

**Workflow:** Inspect devices, filesystem capacity and mount state, then safely eject an exact target.

**Acceptance boundary:** Destructive disk formatting is not a casual quick action. Keep busy/mounted/error states and permissions explicit.

### 49. Settings / Printers

[PNG](../designs/printers.png) · [Interactive design](../preview/index.html#printers)

**Classification:** Missing presentation. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/printers/PrinterSettings.qml (proposed)`

**Owner:** Supported CUPS/upstream settings integration.

**Workflow:** Choose a printer, inspect queue and job status, and open maintained configuration tools.

**Acceptance boundary:** Installed printer service and permissions must be checked before enabling controls. Never install drivers silently.

### 50. Settings / Privacy & permissions

[PNG](../designs/privacy.png) · [Interactive design](../preview/index.html#privacy)

**Classification:** Missing overview. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/privacy/PrivacySettings.qml (proposed)`

**Owner:** Existing portal permissions, Realtime state, Secret Service.

**Workflow:** Review app capture permissions, actual mic/camera activity and local data boundaries.

**Acceptance boundary:** KWallet was installed; do not claim no secret store. Show provider availability, never secret values; system permissions and AI Tool grants remain different.

### 51. Settings / Defaults & locale

[PNG](../designs/defaults.png) · [Interactive design](../preview/index.html#defaults)

**Classification:** Missing presentation. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/defaults/DefaultsSettings.qml (proposed)`

**Owner:** XDG MIME defaults + supported locale/time services.

**Workflow:** Choose default apps, language, formats and timezone through existing host services.

**Acceptance boundary:** Honor registered desktop IDs and MIME associations. Locale changes can require a new session; do not restart without confirmation.

### 52. Settings / Startup applications

[PNG](../designs/autostart.png) · [Interactive design](../preview/index.html#autostart)

**Classification:** Missing presentation. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/startup/StartupSettings.qml (proposed)`

**Owner:** Existing systemd user units + XDG autostart ownership.

**Workflow:** Inspect login applications and services with exact source and dependency information.

**Acceptance boundary:** No second startup scheduler; protect shell/lock/portal/audio owners and distinguish user apps from required session services.

### 53. Settings / Accounts & identity

[PNG](../designs/accounts.png) · [Interactive design](../preview/index.html#accounts)

**Classification:** Missing presentation. **Pane:** `settings`.

**Where it goes:** `obsidience/shell/qml/panes/settings/accounts/AccountSettings.qml (proposed)`

**Owner:** System account services + explicitly connected providers.

**Workflow:** Inspect local identity and session avatar, then manage online connections through their real providers.

**Acceptance boundary:** Local account identity is not an Agent identity. Password/keyring changes remain native authenticated operations; no credentials in theme files.

## Placement rules

Native standalone panes retain their existing IDs and minimum sizes. Settings subviews do not become extra pane IDs. Graph Knowledge/Memory/Code remain selectors on `knowledge-graph`. Models remains stable ID `status`, despite its visible title. Source and Knowledge dock into the existing Reader through PaneDockLayout. Development and Agent Orchestration are compositions of existing views, not parallel workbench/runtime engines.

Wide desktop: prioritize the active reading/work column; diagnostics and AI context are secondary columns. On auxiliary 1920×1200 logical space, use at most two columns or one focused pane. On a 1920×550 strip, show a compact focused view and internal scrolling rather than compressing the entire atlas. At narrow widths, collapse secondary context into tabs/drawers. The atlas navigation is review scaffolding, not shipping pane chrome.
