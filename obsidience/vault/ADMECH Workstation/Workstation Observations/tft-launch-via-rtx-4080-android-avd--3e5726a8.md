---
type: knowledge
tags:
- tft
- linux
- emulator
- systemd
title: TFT launch through Waydroid and Gamescope
obsidience:
  approved_at: '2026-09-06T01:05:05'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

For an explicit request to open or launch “TFT” or “Teamfight Tactics”, the registered application route is `teamfight_tactics`; Executive calls `application.launch` with that semantic application name. A mention of TFT, an already open window, or a request to start a normal game or match is not another launch instruction. Resolve that in-application outcome through the current conversation, Shell Scene and Computer Use Runbook. If the launcher reports an already ready window, say it is already open rather than claiming a new launch. The shared application registry selects `tft-waydroid.desktop`, whose Exec is `/home/wissenschafter/.local/bin/tft-mobile`. The former `tft-mobile-waydroid.desktop`, RTX 4080 Android AVD launcher, and fixed emulator service are retired.

The current launcher runs the existing Waydroid Android session through the dedicated Gamescope 3.16.25 SDL build. Android renders on AMD; the accepted outer Gamescope path selects the RTX 4080. Its process-local `SDL_APP_ID=tft-waydroid` gives the native window one exact identity shared by launch readiness, observation, activation, and placement. Generic Gamescope windows and legacy emulator titles are not TFT evidence.

The managed GUI unit owns the launcher lifetime, and the launcher holds its existing nonblocking flock to prevent duplicate startup. Do not invent a fixed TFT unit or invoke an alternate emulator. A successful dispatch without a matching native window means starting; readiness requires the exact current window. Window readiness does not prove account login or a live match. Do not repeat uncertain dispatches or place and resize the window unless requested. Hyprland supplies ordinary placement on the current Surface.

Preserve the accepted fixed 1920x1080 Android image, stretch scaling, mouse-to-touch synthesis, touch mode 4, and the dedicated SDL guard against duplicate mouse events. Preserve the existing version- and UID-scoped Waydroid compatibility service and original Riot-signed application. On 2026-09-05 the corrected route and exact native capture reached TFT's sign-in screen. A trial forcing the outer renderer to AMD showed a black window despite valid Android pixels and was removed. An initial NVIDIA launch encountered a Wayland synchronization failure; the subsequent normal-renderer launch displayed TFT, so that isolated upstream failure is not claimed repaired by the registry change.

## Relationships

- `uses` [Application launch and window management](/ADMECH%20Workstation/Workstation%20Observations/agent-launch-and-gui-application-management--339f2788.md) — TFT uses the shared managed application route and exact window identity.
- `runs_on` [Unified display topology](/ADMECH%20Workstation/Workstation%20Observations/display-topology-and-isolation-strategy--a8755cfa.md) — The native TFT window participates in the existing unified Surface layout.
- `related_to` [TFT next-best-play policy](/Games/TFT/tft-next-best-play-policy--50fb5e13.md) — A verified game window is a prerequisite for bounded game observation and interaction.
