---
type: knowledge
title: Native shell and surfaces
sources:
- resource: obsidience/shell/qml/shell.qml
- resource: obsidience/shell/qml/workspace/PaneWorkspace.qml
- resource: obsidience/shell/qml/workspace/PaneWindow.qml
- resource: obsidience/shell/qml/workspace/PaneDockLayout.qml
- resource: obsidience/shell/qml/api/ShellCommandServer.qml
- resource: obsidience/shell/surfaces/knowledge/host.py
- resource: obsidience/shell/systemd/obsidience-shell-knowledge.service
- resource: obsidience/harness/interfaces/api/app.py
obsidience:
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
  approved_at: '2026-09-10T23:49:22.333585+00:00'
---

One Hyprland compositor owns the desktop's outputs, native windows, input
routing and composition. The adapter translates compositor state and explicit
commands into stable Obsidience Shell contracts. Logical Surfaces identify
placement on displays; they do not create separate compositors or Agents.

One Quickshell host loads `obsidience/shell/qml/shell.qml` and the shared pane
workspace. An undocked module is a native `FloatingWindow`/Wayland toplevel.
Hyprland owns focus, stacking and outer move/resize behavior; `PaneFrame`
provides content and internal controls. The exact initial pane identity is
`io.obsidience.shell` with `obsidience-pane:<pane_id>`, rather than an arbitrary
mutable title. External application content remains owned by its application.

Reader is the native Article and Source viewer. Knowledge and Source explorers
can dock inside Reader or detach as ordinary panes. `PaneWorkspace`,
`PanePlacement` and the revisioned dock layout own presentation state; docking
does not create another document store. Exact selections travel through the
Shell command server and are read through the existing Harness API.

## Knowledge desktop and lifetime

`obsidience-shell-knowledge.service` launches a dedicated GTK/WebKit layer-shell
presenter. It displays the shared Three.js graph bundle from
`/shell/knowledge/` on the one `graph_surface_id` selected in the existing
Surface layout. It is not rendered by Quickshell, duplicated per display or
hosted by Electron. The API serves compiled `obsidience/ui/out/renderer` assets;
a TypeScript change requires rebuilding those assets before restarting the
presenter.

The shell host and knowledge presenter belong to
`obsidience-shell-session.target`. The graph requires the shell host but only
wants the Harness at startup: a Harness restart must not strand or close the
resident presenter. API reconnection refreshes its data. Normal pane or graph
updates do not require restarting the compositor session.

[Desktop scene and computer use](/Agents/Executive/Architecture/Shell/hyprland-shell-scene.md) covers effect
validation. [Knowledge graph rendering](/Agents/Executive/Architecture/Shell/knowledge-graph-rendering.md) covers
the graph's data and geometry. Linux, systemd, PipeWire and driver services
remain upstream infrastructure, not reimplemented shell subsystems.
