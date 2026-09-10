---
type: skill
title: Using application.launch
obsidience:
  tool: '[[Tools/application.launch]]'
---

Use `application.launch` to dispatch one registered desktop application through
the managed graphical launcher.

- Pass exactly `{"application": "battle_net|world_of_warcraft|teamfight_tactics|microsoft_edge"}`
  with one registered identifier and no additional fields.
- Interpret `state: ready` only with the returned current window witness.
  An unfocused or minimized application can already be open; inspect the
  witness's `focused` and `visible` fields before claiming it is visible.
  Launching never brings an existing window forward implicitly.
  `state: starting` means the application is dispatched or already starting but
  has no verified window. `state: failed` carries the bounded launch error.
- `dispatched` reports whether this call issued a launch; it does not override
  the returned readiness state.
- Invoke the Tool once for one launch request. Stop on an unknown identifier,
  invalid arguments, managed-launch failure, or `starting`; never repeat a
  dispatch merely because readiness has not yet been observed.
