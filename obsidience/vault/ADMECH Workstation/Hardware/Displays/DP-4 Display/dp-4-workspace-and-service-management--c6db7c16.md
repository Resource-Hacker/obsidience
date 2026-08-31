---
approved_at: '2026-08-31T09:49:20'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/link)
tags:
- software
- display
- service
title: DP-4 Workspace and Service Management
---

DP-4: Xorg :1, Openbox, Discord, Codex terminal. Services: dp4-xorg, dp4-openbox, dp4-discord, dp4-side-terminal, dp4-clipboard-bridge. Clipboard bridge: event-driven, non-polling, suppresses stale text. Terminal: tmux codex-dp4 session. Layout: 80x24 initial, tiled by dp4-layout.

## Relationships

- `runs_on` [[ADMECH Workstation/Software/Terminal and tmux/terminal-persistence-and-tmux-configuration--e868685d|Terminal Persistence and tmux Configuration]]
- `related_to` [[ADMECH Workstation/Software/Desktop and Windowing/agent-launch-and-gui-application-management--339f2788|Agent Launch and GUI Application Management]]
- `implements` [[Agents/Executive/Architecture/local-first-architecture--7d8e77cc|Local-first Executive architecture preference]] — The dedicated DP-4 agent workspace realizes the local-first, agent-first workstation design.
- `related_to` [[ADMECH Workstation/Hardware/Input/input-mapping-and-mouse-configuration--5579dfc0|Input Mapping and Mouse Configuration]] — Its DP-4 mouse profile and `dp4-edge-bridge.service` cursor control provide the pointer input path for this isolated DP-4 workspace.
