---
type: knowledge
tags:
- hardware
- display
- invariant
title: Unified display topology
obsidience:
  approved_at: '2026-09-10T22:38:54'
  provenance: proposed by Alexandria (task Tasks/link)
---

The Samsung Odyssey OLED G9, USB-C display, and logical DP-4 display are three
Surfaces in one Hyprland compositor session. A Surface is a placement identity
for applications, module panes, and the knowledge graph; it is not another
compositor, process, service, input lane, or clipboard boundary.

Hyprland uses the RTX 4080 SUPER for Samsung `HDMI-A-1` and the AMD iGPU for
USB-C `DP-8` plus logical DP-4 `HDMI-A-2`. The accepted live desktop geometry is:

- Samsung: `5120x1440 @ 239.99899 Hz`, position `0x0`, scale 1, 10-bit
  `XBGR2101010`; fullscreen-only VRR is configured but idle at the desktop.
- Logical DP-4: `3840x1100 @ 59.998 Hz`, position `0x1440`, scale 2.
- USB-C: `3840x2400 @ 60 Hz`, position `1920x1440`, scale 2.

One Quickshell host renders the shared pane registry, stage, and bar on all
three Surfaces. One WebKitGTK host presents the canonical Three.js graph on the
Surface selected by `graph_surface_id`. Hyprland owns native pointer crossing,
focus, clipboard, output adjacency, and ordinary application-window movement.
The retired per-display Xorg, Openbox, input-router, pointer/edge-bridge, and
clipboard-bridge paths are not part of the live topology.

Pane dragging remains local to its current Surface. `Meta+Shift+Arrow` moves the
active Obsidience pane to the nearest mapped Surface through the single pane
placement authority. The physically connected JetKVM sink remains outside the
ordinary desktop topology.

HDR, physical fullscreen VRR and World of Warcraft performance remain explicit
acceptance gates; the unified desktop topology alone does not establish them.
The [World of Warcraft launch policy](/ADMECH%20Workstation/Workstation%20Observations/world-of-warcraft-launch-policy--3e5e73cc.md) is the evidence path for that performance gate, defining the registered launch route and readiness criteria.

## Relationships

- `related_to` [Hyprland shell scene](/Agents/Executive/Architecture/Shell/hyprland-shell-scene.md) — The Shell scene is the bounded semantic projection of this one live compositor topology.
- `related_to` [Shell](/Agents/Executive/Architecture/Shell/Shell.md) — The Quickshell host and WebKitGTK graph presenter in this topology are the ADMECH realization of the Shell's presentation boundary.
- `related_to` [Samsung display configuration](/ADMECH%20Workstation/Workstation%20Observations/samsung-display-vrr-and-edid-configuration--96ccfd7b.md) — Samsung mode, color, and VRR requirements remain a specific display contract inside the unified topology.

## Accepted inbound references
- [agent-launch-and-gui-application-management--339f2788](/ADMECH%20Workstation/Workstation%20Observations/agent-launch-and-gui-application-management--339f2788.md)
- [input-mapping-and-mouse-configuration--5579dfc0](/ADMECH%20Workstation/Workstation%20Observations/input-mapping-and-mouse-configuration--5579dfc0.md)
- [samsung-display-vrr-and-edid-configuration--96ccfd7b](/ADMECH%20Workstation/Workstation%20Observations/samsung-display-vrr-and-edid-configuration--96ccfd7b.md)
- [samsung-total-display-loss-incident-and-failover-contract--5c280a8c](/ADMECH%20Workstation/Workstation%20Observations/samsung-total-display-loss-incident-and-failover-contract--5c280a8c.md)
- [tft-launch-via-rtx-4080-android-avd--3e5726a8](/ADMECH%20Workstation/Workstation%20Observations/tft-launch-via-rtx-4080-android-avd--3e5726a8.md)
- [hyprland-shell-scene](/Agents/Executive/Architecture/Shell/hyprland-shell-scene.md)
