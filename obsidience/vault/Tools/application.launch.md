---
type: tool
title: application.launch
description: Open one registered application with application:<registered identifier>.
obsidience:
  binding: capability:application.launch
  source: obsidience/harness/capabilities/application/launch.py
---

## Runtime

Open one registered application with application:<registered identifier>. Dispatch occurs at most once. The same call waits up to ten seconds for a current matching window. ready establishes an open window, not focus; dispatched:false means it was already open or starting. starting with wait_status means readiness remains unresolved. Never redispatch after timeout, cancellation, ambiguity or uncertain delivery.

## Reference

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
