---
type: knowledge
title: Shell
sources:
- resource: obsidience/shell/qml/shell.qml
- resource: obsidience/shell/systemd/obsidience-shell-host.service
- resource: obsidience/shell/systemd/obsidience-shell-knowledge.service
- resource: obsidience/shell/surfaces/knowledge/host.py
obsidience:
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
  approved_at: '2026-09-10T23:49:22.333585+00:00'
---

The Shell is Obsidience's desktop integration and presentation boundary in
`obsidience/shell/`, with shared web graph code in `obsidience/ui/`. Hyprland owns
composition, windows, input routing and output behavior. One Quickshell host
owns native shell controls and panes. A separate GTK/WebKit presenter displays
the canonical Three.js knowledge desktop on the selected Surface.

The executive and satellites are graph instances using one shared renderer and
one shared layout implementation. A Surface is a logical display/placement
identity, not a separate compositor, Agent, or knowledge authority.

- [Native shell and surfaces](/Agents/Executive/Architecture/Shell/native-shell-and-surfaces.md): session lifecycle,
  native panes, Reader docking and the graph presenter.
- [Desktop scene and computer use](/Agents/Executive/Architecture/Shell/hyprland-shell-scene.md): current window
  identity, capture, focus, placement and bounded input effects.
- [Knowledge graph rendering](/Agents/Executive/Architecture/Shell/knowledge-graph-rendering.md): data projection,
  shared cloud physics, hierarchy and thinking-path animation.

The [Harness](/Agents/Executive/Architecture/Harness/Harness.md) owns Task selection, models and execution.
The Shell displays state and accepts explicit typed commands; it does not
introduce another scheduler, memory store or reasoning engine. Current physical
inventory lives in [System](/ADMECH%20Workstation/ADMECH%20Workstation.md).
