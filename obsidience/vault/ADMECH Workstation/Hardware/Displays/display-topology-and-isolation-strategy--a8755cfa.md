---
approved_at: '2026-09-02T03:01:41'
kind: knowledge
provenance: proposed by Codex (task codex:knowledge-handoff)
tags:
- hardware
- display
- invariant
title: Display topology and isolation strategy
---

The Samsung Odyssey OLED G9, USB-C display, and logical DP-4 display are three
logical Surfaces inside one Hyprland compositor session. Surface is a placement
identity for panes and the knowledge graph; it is not a compositor, process,
service, input, or clipboard boundary.

Hyprland uses the RTX 4080 SUPER for Samsung `HDMI-A-1` and the AMD iGPU for
USB-C `DP-8` plus logical DP-4 `HDMI-A-2`. The accepted live desktop geometry is:

- Samsung: `5120x1440 @ 239.99899 Hz`, position `0x0`, scale 1, 10-bit
  `XBGR2101010`; fullscreen-only VRR is configured but idle at the desktop.
- Logical DP-4: `3840x1100 @ 59.998 Hz`, position `0x1440`, scale 2.
- USB-C: `3840x2400 @ 60 Hz`, position `1920x1440`, scale 2.

One Quickshell host renders the shared pane registry, stage, and bar on all three
Surfaces. One WebKitGTK host presents the canonical Three.js graph on whichever
Surface is selected by `graph_surface_id`. Hyprland natively owns pointer
crossing, focus, clipboard, output adjacency, and ordinary application-window
movement. There is no per-Surface compositor or shell service and no active
Xorg, Openbox, input-router, pointer/edge bridge, or clipboard bridge.

Pane dragging remains local to its current Surface. `Meta+Shift+Arrow` moves the
active Obsidience pane to the nearest mapped Surface through the single pane
placement authority. The physically connected JetKVM sink remains outside the
ordinary desktop topology.

HDR, physical fullscreen VRR and World of Warcraft performance remain explicit
acceptance gates; the unified desktop topology alone does not establish them.

## Relationships

- `related_to` [[ADMECH Workstation/Workstation Observations/Incident/incident-samsung-vrr-blackscreen-and-nvidia-610-regression--bcacd849|Incident: Samsung VRR Blackscreen and NVIDIA 610 Regression]] — The historical display incident remains relevant to Samsung fullscreen VRR acceptance.
- `related_to` [[ADMECH Workstation/Hardware/Displays/DP-4 Display/dp-4-workspace-and-service-management--c6db7c16|DP-4 Workspace and Service Management]] — The older DP-4 workspace article requires reconciliation with the unified Hyprland topology.
- `related_to` [[ADMECH Workstation/Hardware/Displays/Samsung Odyssey OLED G9/samsung-display-vrr-and-edid-configuration--96ccfd7b|Samsung Display VRR and EDID Configuration]] — The Samsung mode and EDID contract remain separate from the shell topology.
