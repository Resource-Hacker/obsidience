---
type: tool
title: application.launch
description: Open one registered application with application:<registered identifier>.
obsidience:
  binding: capability:application.launch
  source: obsidience/harness/capabilities/application/launch.py
---

## Runtime

Open one registered application with application:<registered identifier>. Dispatch occurs at most once. The same call waits up to ten seconds for a current matching window. ready establishes an open window, not focus; dispatched:false means it was already open or starting. If the exact managed launch ends without a ready window, state:failed and wait_status:terminated_before_ready report that observed failure. A readiness deadline returns state:unverified, not evidence of continued loading. Never redispatch after timeout, cancellation, ambiguity or uncertain delivery.

## Reference

Dispatch one registered desktop application exactly once through the
workstation-managed graphical launcher. Argument:
`{"application": "battle_net|world_of_warcraft|teamfight_tactics|microsoft_edge"}`.

Before dispatch, the Tool checks the shared Shell Scene for an existing window and a known
active launch unit. The result is `ready`, `unverified`, or `failed`. `ready`
requires a current window witness, not foreground focus or visible content.
The witness reports its Surface, focus and visibility without native window IDs.
`unverified` means readiness could not be established; loading is unknown.
`launch_lifetime: ended` with `wait_status: terminated_before_ready` means the
exact managed launch ended before a ready window was observed. An active unit
alone does not prove that an application is healthy or still loading. Cancellation
may retain the provisional `starting` state with `wait_status: cancelled`; it is
not a readiness result. Preserve the actual outcome for follow-up explanations. The Tool does not focus, close, stop, or retry an
application.
