---
type: knowledge
title: Hyprland shell scene
obsidience:
  approved_at: '2026-09-08T19:40:45'
  provenance: proposed by Alexandria (task Tasks/link)
---

Obsidience has one live desktop scene. One Hyprland compositor owns Samsung,
USB-C, and DP-4 as logical Surfaces. Native applications and the module panes
presented by one Quickshell host are ordinary Wayland windows in that scene. A
Surface is a placement identity, not a separate compositor, process, Agent,
Tool, or knowledge domain.

Registered application names are anchored to their actual application ID/class.
TFT uses its exact current tft-waydroid class. Only a registered discriminator
may refine an application match; historical emulator classes are not current identity. A browser page title cannot identify a game.

The Shell publishes one bounded, revisioned scene containing the Surface grids,
focused window, and every addressable focused or unfocused application's or
module pane's semantic identity, visibility, local bounds, Surface, and Surface
power state. Exact compositor identifiers, geometry revisions, and capture
tokens remain private controller bindings. `application.state` reports the
per-Surface window scene and `workspace.state` reports shared workspace state.
Either typed Shell event may trigger an existing Task through [Task activation](/Agents/Executive/Architecture/task-activation--b30a4642.md) but never becomes a Task or creates hierarchy.

The semantic projection uses concrete `kind: application|pane` and a callable
`name`: the registered canonical application ID when available, otherwise the
exact current `app_id`, or the exact `pane_id`. Display `title` and `focused`
state are separate from identity. Observation, focus, and placement share one
resolver; existing application-registry aliases are accepted, arbitrary titles
and fuzzy matching are not. Multiple matching windows fail closed even if one
is focused; a current Surface may disambiguate the same identifier.

The current scene is runtime state, not durable Knowledge. The activation
compiler may attach its newest bounded projection under Thinking Packet
Bindings, but it must not copy window lists, coordinates, or focus history into
this Article or Immediate Observations. This Article supplies only the stable
architecture needed to interpret that projection.

[computer.observe](/Tools/computer.observe.md) answers a visual question about
the focused window or one exact application or module pane without changing
focus. Window enumeration and focus already ride in the scene. `focused` is an
observation input selector only; the returned `target: {kind, name, surface}`
contains the concrete reusable identity, with title and focus state separate.
[window.activate](/Tools/window.activate.md) explicitly brings an existing target
forward. [window.place](/Tools/window.place.md) explicitly changes its Surface or
tile. In-window input remains the separate
[computer.act](/Tools/computer.act.md) effect. Every Tool privately pins the scene
revision immediately before use and requires fresh post-effect evidence. The
effect's verified returned scene is sufficient for focus or placement; neither
needs prerequisite observation or an extra verification screenshot. A
sleeping Surface is never woken implicitly; ambiguous, hidden, locked,
disconnected, stale, or unavailable state fails closed.

## Relationships

- `implements` [Local-first architecture](/Agents/Executive/Architecture/local-first-architecture--7d8e77cc.md) — One compositor, host, scene, and placement authority own the desktop boundary.
- `implements` [Activation packet protocol](/Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad.md) — The bounded current scene rides as runtime Bindings rather than durable Knowledge.
- `related_to` [Display topology and isolation strategy](/ADMECH%20Workstation/Workstation%20Observations/display-topology-and-isolation-strategy--a8755cfa.md) — The display Article supplies the current physical outputs behind the logical Surfaces.
- `related_to` [Application launch and window management](/ADMECH%20Workstation/Workstation%20Observations/agent-launch-and-gui-application-management--339f2788.md) — This is the operational interpretation of the scene for launch, observation, focus, placement, and input.
- `related_to` [TFT launch through Waydroid and Gamescope](/ADMECH%20Workstation/Workstation%20Observations/tft-launch-via-rtx-4080-android-avd--3e5726a8.md) — The scene's registered-application resolver specifically anchors this launcher's current `tft-waydroid` class for observation, focus, and placement.
