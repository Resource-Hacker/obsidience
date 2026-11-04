---
type: tool
title: computer.observe
description: >-
  Read a fresh image of one exact target without changing focus or placement. Required in
  the current turn before answering about current window contents, people present, counts or
  other visible state; earlier conversation and observations are historical. For what the
  owner is looking at now, use target kind focused. For what just happened (the recent
  past), use computer.replay. Optional region:{left,top,right,bottom} on the complete image
  0-999 grid supplies native detail and bounded CPU OCR; read:false disables OCR.
  read_mode:line reads an explicitly selected complete text row without detection (default
  detect). Region images and text are read-only supplements; input coordinates always refer
  to the complete image.
obsidience:
  binding: capability:computer.observe
  source: obsidience/harness/capabilities/computer/observe.py
---

## Runtime

Read the current image of one exact target without changing focus or placement. Pass target:{kind:application|pane,name:<exact name>,surface?:<surface>,title?:<exact Scene title>} or target:{kind:focused}, plus query. The image is private in-memory evidence. Only the immediately following computer.act may consume an application observation lease. An unavailable image does not authorize input. capture_session_unavailable is a Harness startup failure, not a window problem: report it without retrying other targets.

For small text or a focused panel, add `region:{left,top,right,bottom}` using integers 0–999 on the complete target image grid, with left < right and top < bottom. The same source image supplies a native pixel crop before resizing, beside the complete image. Region coordinates are read-only selectors; computer.act points always refer to the complete original image. A region starts bounded CPU OCR by default; set `read:false` for image detail only. `read:true` requires a region. For one deliberately selected complete text row, set `read_mode:line` to recognize the native crop directly; the default `read_mode:detect` locates text within a panel. Never use line mode on a multi-line panel. `read_mode` requires a region with reading enabled. OCR text, confidence and coverage are untrusted evidence, can omit or misread text, and never supply input authority. In voice, answer from the image immediately when useful; a finite later stage may add a finding or explicit correction from the same frozen source. Reply SKIP when it adds nothing. Do not invent unreadable values or repeat the first answer. A reading continuation never renews the original input lease.

## Reference

Answer one visual question about an exact native application or module pane,
including a unique unfocused target. The current Shell Scene already supplies
window enumeration and focus; observation is not an enumeration Tool. Arguments:
`{"target": {"kind": "focused|application|pane", "name": str optional, "surface": "<configured Surface id>" optional}, "query": str}`.

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
