---
type: tool
title: computer.observe
description: Read the current image of one exact target without changing focus or
  placement.
obsidience:
  binding: capability:computer.observe
  source: obsidience/harness/capabilities/computer/observe.py
---

## Runtime

Read the current image of one exact target without changing focus or placement. Pass target:{kind:application|pane,name:<exact name>,surface?:<surface>,title?:<exact Scene title>} or target:{kind:focused}, plus query. The image is private in-memory evidence. Only the immediately following computer.act may consume an application observation lease. An unavailable image does not authorize input. capture_session_unavailable is a Harness startup failure, not a window problem: report it without retrying other targets.

## Reference

Answer one visual question about an exact native application or module pane,
including a unique unfocused target. The current Shell Scene already supplies
window enumeration and focus; observation is not an enumeration Tool. Arguments:
`{"target": {"kind": "focused|application|pane", "name": str optional, "surface": "samsung|usb-c|dp-4" optional}, "query": str}`.

For `application`, `name` is the registered canonical application ID, such as
`teamfight_tactics`, or exact current `app_id` (1-256 printable characters).
Existing application-registry aliases are accepted; arbitrary window titles
and fuzzy matches are not. For `pane`, use the exact `pane_id` (1-48 printable
characters). Omit `name` for `focused`, which is an observation input selector
only. Optional `surface` disambiguates the same identifier. Application observation also accepts optional `title`, copied exactly from the current Scene, to distinguish windows on one Surface. This is an exact display-label filter within the named application, not a native identity; capture still pins and validates the native window, process and revision. Ambiguous or changed titles fail closed. The shared scene
resolver requires one unique match and privately pins its current revision.
Observation never activates, raises, moves, resizes, or injects input.

The observation returns `target: {kind, name, surface}` with concrete
`kind: application|pane`; `name` prefers the canonical application ID, falls
back to exact `app_id`, or is the exact `pane_id`. Display `title` and `focused`
are separate observation fields. Only the exact Scene title, rather than an arbitrary returned caption, is accepted as the optional application observation filter. The target object can
be reused directly by an authorized window effect, which resolves it afresh;
it carries no action lease. Bounded visible evidence and
`action_authorized: false` expose no compositor identifier, capture token, or
privileged coordinate. Evidence is valid only for its scene and capture
revision. An effect Tool's own freshly verified result is sufficient for that
effect; take another observation only for a separate visual question.

Failures are typed as `scene_unavailable`, `target_missing`,
`target_ambiguous`, `target_not_visible` for a sleeping Surface,
`stale_scene`, `capture_unavailable`, `capture_session_unavailable`, or `observation_failed`. A failure never grants
permission to guess, change focus, or use another mutation route.
