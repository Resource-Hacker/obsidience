---
type: skill
title: Using computer.observe
description: Use the scene to select an exact target; focused targets omit name.
obsidience:
  tool: '[[Tools/computer.observe]]'
---

## Runtime

Use the scene to select an exact target; focused targets omit name. Observe without a prerequisite focus change. Interpret the attached image, not an invented screen description. After observing for a click, make computer.act the next Tool call or obtain a new observation. If capture_session_unavailable is returned, report the missing graphical session and stop; trying other applications cannot repair it.

For a current-view question with multiple windows of the named application, use kind: focused with its exact Surface only when the Scene identifies one focused matching window. If the owner names a particular window, copy its exact displayed Scene title into target.title alongside its application name and Surface. Otherwise ask which visible window title the owner means. Never substitute an unrelated focused application or repeat an ambiguous selector.

## Reference

Use `computer.observe` to answer one bounded visual question about one current
native application or module pane without changing focus or placement.
Use the Shell Scene already in Bindings to list windows or read focus; that
does not require a screenshot.

- Pass exactly `{"target": {"kind": "focused|application|pane", "name": str
  optional, "surface": "samsung|usb-c|dp-4" optional}, "query": str}`.
  Omit `name` for `focused`. For `application`, use the canonical application
  ID, such as `teamfight_tactics`, or exact current `app_id` (1-256 printable
  characters); existing registry aliases also resolve. For `pane`, use exact
  `pane_id` (1-48 printable characters). Never substitute a display title or
  fuzzy name. Keep `query` between 1 and 500 characters. Add a current Surface
  only to make the same identifier unique. For application observation only, optional `title` must exactly match the current Scene title (including any ellipsis); it narrows the named application to one window. No fuzzy matching or title-only identity is accepted.
- Success returns `observation.status: observed`, validated attached visual
  evidence, and `action_authorized: false`. Its `target: {kind, name, surface}`
  has concrete `kind: application|pane` and the canonical application ID,
  exact `app_id` fallback, or exact `pane_id`. `focused` is input-only as a
  target kind; display `title` and the `focused` boolean are separate observation
  fields. Reuse the target object, not the title, for an authorized window
  effect; the effect still resolves and validates its own current scene.
- Visual evidence is valid only for its returned scene and capture revision.
  An effect Tool's freshly verified result is sufficient for that effect;
  another observation is needed only for a separate visual question.
- `target_missing`, `target_ambiguous`, `target_not_visible`, and
  `observation_failed` are terminal for the supplied selector. Do not guess,
  substitute another target, wake a Surface, or ask the owner to focus it.
- A result marks `scene_unavailable`, `stale_scene`, or `capture_unavailable`
  as retryable when a fresh read may succeed. Retry only as a new observation
  against current state; never treat the failed result as evidence.
