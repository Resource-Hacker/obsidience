---
type: tool
title: window.activate
description: Focus one exact current application or pane using target:{kind:application|pane,name:<exact
  name>,surface?:<surface>}.
obsidience:
  binding: capability:window.activate
  source: obsidience/harness/capabilities/window/activate.py
---

## Runtime

Focus one exact current application or pane using target:{kind:application|pane,name:<exact name>,surface?:<surface>}. The result uses the shared scene and verified post-state. An already active result is not a new effect. Missing, ambiguous, locked or stale targets fail closed.

## Reference

Bring one existing native application or module pane to the front and give it
focus. Argument:
`{"target": {"kind": "application|pane", "name": str, "surface": "samsung|usb-c|dp-4" optional}}`.

Use the current Shell Scene's concrete `kind: application|pane` and `name`,
or the exact target object returned by observation. For an application, `name`
is the canonical registered application ID, such as `teamfight_tactics`, or
exact current `app_id`, with 1-256 printable characters. Existing registry
aliases are accepted, not arbitrary window titles or fuzzy matches. For a
module pane, use exact `pane_id` with 1-48 printable characters. `focused` is
not a valid effect target kind. `surface` only disambiguates the same identifier;
no match or multiple matches fails closed.

Obsidience resolves one unique semantic target from the newest Shell scene,
privately pins its exact window and scene revision, requests one activation,
and returns a fresh scene showing whether that target became active, with the
normalized target identity. No prerequisite observation is needed; the returned
verified active state is sufficient focus evidence. It exposes no internal
window identifier. This Tool does not launch, move, resize, click, or type.

Failures are typed as `scene_unavailable`, `target_missing`,
`target_ambiguous`, `stale_scene`, `effect_not_observed`, or
`shell_scene_command_unavailable`. Failure or uncertain delivery means no
verified effect and must not be reported as success. Every result carries
`must_not_replay: true`; do not automatically repeat even a failed call.
