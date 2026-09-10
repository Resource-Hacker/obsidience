---
type: knowledge
tags:
- software
- agent
- invariant
title: Application launch and window management
---

Launch a registered graphical application exactly once through
`application.launch`, which delegates to the workstation-managed launcher and
distinguishes dispatch from current window readiness. Do not use a terminal
background process, `nohup`, or `setsid` as a second launch route.

Hyprland owns native focus, stacking, placement, movement, and resize for both
applications and undocked Obsidience module panes. The Harness receives their
bounded semantic state through the Shell scene, including window enumeration
and focus. Use `computer.observe` for a visual question, `window.activate` to
bring one existing pane forward,
`window.place` to move one existing pane, and `computer.act` for one grounded
in-window input. Each effect requires one unique target and fresh evidence.
The scene's callable `name` is the registered canonical application ID, exact
`app_id` fallback, or exact module `pane_id`; display titles are not selectors.
Observation, focus, and placement share this identity contract. Resolve "it"
from the explicit active conversation and current scene, then focus or place
directly once. The effect's verified returned scene is sufficient; no
prerequisite observation or extra verification screenshot is needed.

## Relationships

- `implements` [Local-first architecture](/Agents/Executive/Architecture/Harness/local-first-architecture--7d8e77cc.md) — Managed launch and the single Hyprland scene preserve one authority for each desktop concern.
- `related_to` [Hyprland shell scene](/Agents/Executive/Architecture/Shell/hyprland-shell-scene.md) — The scene defines semantic application and module-pane targeting without exposing compositor identifiers.
- `runs_on` [Unified display topology](/ADMECH%20Workstation/Workstation%20Observations/display-topology-and-isolation-strategy--a8755cfa.md) — Application and module-pane effects operate across the three Surfaces owned by the one compositor.
