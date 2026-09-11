---
type: knowledge
tags:
- software
- terminal
- service
title: Terminal persistence and tmux configuration
---

The enabled user `tmux.service` supervises `/usr/bin/tmux -D` as a foreground
`Type=simple` process and keeps the shared `codex` session alive. Resurrect is
saved by the five-minute `tmux-resurrect-save.timer` and again on service stop;
the status line must not run its own save loop.

The native Obsidience Terminal pane attaches to the linked `obsidience-ui`
view of the shared `codex` group through its fixed local helper. The retained
`codex-dp4` name is a compatibility view, not an isolated DP-4 terminal service
or a second terminal owner. Pane close detaches the view without killing the
shared session. Before disruptive compositor or machine work, save current
tmux state and verify the exact resumed Codex thread rather than treating a
running tmux process as proof of continuity.

## Relationships

- `related_to` [Local-first architecture](/Agents/Executive/Architecture/Harness/local-first-architecture--7d8e77cc.md) — The persistent local session survives shell presentation changes without creating another agent or terminal authority.
- `related_to` [Hyprland shell scene](/Agents/Executive/Architecture/Shell/hyprland-shell-scene.md) — Terminal is an ordinary addressable module pane in the unified Shell scene while tmux owns its process continuity.
