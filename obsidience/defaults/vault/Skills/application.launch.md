---
type: skill
title: Using application.launch
description: Use the controller's registered identifier.
obsidience:
  tool: '[[Tools/application.launch]]'
---

## Runtime

Use the controller's registered identifier. Let the original call observe readiness. ready with dispatched:false means already open, not newly launched. Focus and visibility are separate outcomes. Report timeout as unverified. Report terminated_before_ready as a failed managed launch, never still loading. Do not launch again.

## Reference

Use `application.launch` to dispatch one registered desktop application through
the managed graphical launcher.

- Pass exactly `{"application": "battle_net|world_of_warcraft|teamfight_tactics|microsoft_edge"}`
  with one registered identifier and no additional fields.
- Interpret `state: ready` only with the returned current window witness.
  An unfocused or minimized application can already be open; inspect the
  witness's `focused` and `visible` fields before claiming it is visible.
  Launching never brings an existing window forward implicitly.
  `state: unverified` means no ready window was established; the loading state
  is unknown. `state: failed` reports a managed-launch error or the exact launch
  ending before readiness (`wait_status: terminated_before_ready`). A cancelled
  wait may retain provisional `starting`; it does not prove continued loading.
- `dispatched` reports whether this call issued a launch; it does not override
  the returned readiness state.
- Invoke the Tool once for one launch request. Stop on an unknown identifier,
  invalid arguments, managed-launch failure, cancellation, or `unverified`; never repeat a
  dispatch merely because readiness has not yet been observed.
