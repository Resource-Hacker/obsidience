---
kind: knowledge
tags:
- tft
- waydroid
- linux
- emulator
- systemd
title: TFT launch via RTX 4080 Android AVD
---

“TFT” and “Teamfight Tactics” mean the registered `team_fight_tactics` application route. Executive calls the managed launcher exactly once. The route selects `tft-mobile-waydroid.desktop`, whose legacy name is misleading: its Exec is the idempotent `/home/wissenschafter/.local/bin/tft-4080-emulator` RTX 4080 Android AVD launcher. It does not use Waydroid.

Never probe or start Waydroid, a static TFT service, an alternate emulator, or a terminal command. The launcher creates or reuses its own transient `tft-4080-emulator.service` and owns Samsung placement. A successful dispatch with no matching window means TFT is starting; readiness requires explicit matching window or ADB evidence. Do not repeat dispatch while readiness is uncertain, and do not place or resize the window unless the owner asks.

## Relationships

- `uses` [[ADMECH Workstation/Software/Desktop and Windowing/agent-launch-and-gui-application-management--339f2788|Agent Launch and GUI Application Management]] — The TFT AVD is launched through the established managed GUI application route.
- `runs_on` [[ADMECH Workstation/Hardware/Displays/display-topology-and-isolation-strategy--a8755cfa|Display Topology and Isolation Strategy]] — The launcher places the RTX 4080 Android AVD on the Samsung gaming display in the established topology.
- `related_to` [[Games/TFT/tft-next-best-play-policy--50fb5e13|TFT next-best-play policy]] — The managed TFT launch route is the prerequisite for a bounded next-best-play action.
