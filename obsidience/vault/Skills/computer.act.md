---
type: skill
title: Using computer.act
obsidience:
  tool: '[[Tools/computer.act]]'
  approved_at: '2026-09-05T22:01:57'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

Use `computer.act` once for an explicitly requested click on a visible text
label inside one existing application.

- Pass `{"application": str, "action": "click", "target": str,
  "postcondition": str optional}`. Use the canonical application name or exact
  current app_id from the Shell Scene. `target` must be the exact legible label,
  not an invented element index, icon description or coordinate.
- The Capability handles exact foreground activation, fresh capture, unique
  text grounding, private coordinate mapping, one click and post-observation.
  One invocation consumes the single action attempt, including a failed
  precondition. Never retry the click inside the same Task.
- A completed result with `verified_scope: click` establishes the named click
  plus a fresh attached post-image. Inspect that image. Say only what it shows:
  opening a mode-selection screen is not starting a match. A supplied
  `postcondition` is a question to verify, never evidence by itself.
- Stop on missing/ambiguous target, unreadable/duplicate label, stale identity,
  geometry or pixels, sleeping Surface, lock, cancellation, rejected/uncertain
  delivery, or unavailable post-image. Report the exact blocker; do not ask
  for another input path or replay uncertain delivery.
