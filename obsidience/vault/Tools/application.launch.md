---
type: tool
title: application.launch
obsidience:
  binding: capability:application.launch
  source: obsidience/harness/capabilities/application/launch.py
---

Dispatch one registered desktop application exactly once through the
workstation-managed graphical launcher. Argument:
`{"application": "battle_net|world_of_warcraft|teamfight_tactics|microsoft_edge"}`.

Before dispatch, the Tool checks the shared Shell Scene for an existing window and a known
active launch unit. The result is `ready`, `starting`, or `failed`. `ready`
requires a current window witness, not foreground focus or visible content.
The witness reports its Surface, focus and visibility without native window IDs.
`starting` means do not launch it again;
wait for fresh evidence. The Tool does not focus, close, stop, or retry an
application.
