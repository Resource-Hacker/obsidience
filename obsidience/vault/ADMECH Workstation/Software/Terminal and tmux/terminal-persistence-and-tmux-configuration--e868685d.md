---
kind: knowledge
tags:
- software
- terminal
- service
title: Terminal Persistence and tmux Configuration
---

tmux.service: Type=simple, foreground. Resurrect/Continuum: timer-based save, no status-line save. DP-4 terminal: dp4-codex-tmux, codex-dp4 session. Resume: dp4-resume-codex-once. Layout: nonblocking systemctl --no-block. Unset SESSION_MANAGER for isolated services.

## Relationships

- `related_to` [[ADMECH Workstation/Hardware/Displays/DP-4 Display/dp-4-workspace-and-service-management--c6db7c16|DP-4 Workspace and Service Management]] — Terminal persistence and tmux configuration provides the underlying session management for the DP-4 workspace terminal.
