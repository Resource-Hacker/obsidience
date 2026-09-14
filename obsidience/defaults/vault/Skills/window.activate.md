---
type: skill
title: Using window.activate
description: Use the current exact name and optional Surface to disambiguate.
obsidience:
  tool: '[[Tools/window.activate]]'
---

## Runtime

Use the current exact name and optional Surface to disambiguate. The returned scene is sufficient verification; an extra screenshot is not mandatory. Do not claim a new focus effect when the target was already active.

## Reference

Use `window.activate` when one existing native application or module pane must
become the focused front window.

- Pass exactly `{"target": {"kind": "application|pane", "name": str,
  "surface": "samsung|usb-c|dp-4" optional}}`. Take `kind` and `name` from the
  current Shell Scene or reuse an observation's exact target object. For
  `application`, use the canonical application ID, such as `teamfight_tactics`,
  or exact current `app_id` (1-256 printable characters); existing registry
  aliases also resolve. For `pane`, use exact `pane_id` (1-48 printable
  characters). Never substitute a display title, fuzzy name, or `kind: focused`.
  Add the current Surface only to disambiguate that identifier. No match or
  multiple matches fails closed.
- Success returns `status: completed`, the resolved target and Surface,
  `active: true`, `must_not_replay: true`, and `effect_applied`, which is false
  when the target was already active.
- Only the fresh returned active state verifies activation. It does not attest
  any content inside the window. Call directly once; no prerequisite
  observation or extra screenshot to verify the already-attested focus.
- Stop on `scene_unavailable`, `target_missing`, `target_ambiguous`,
  `stale_scene`, `effect_not_observed`, or
  `shell_scene_command_unavailable`. Every failure is non-retryable for this
  attempt; never replay uncertain delivery.
