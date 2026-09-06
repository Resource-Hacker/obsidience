---
type: runbook
title: Computer Use procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Executive/Executive]]'
  task: '[[Tasks/executive/operate]]'
  skills:
  - '[[Skills/application.launch]]'
  - '[[Skills/computer.observe]]'
  - '[[Skills/window.activate]]'
  - '[[Skills/window.place]]'
  - '[[Skills/computer.act]]'
  - '[[Skills/task.create]]'
  - '[[Skills/task.complete]]'
  approved_at: '2026-09-05T22:33:10'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

Produce one bounded computer effect requested by the owner.

1. Read the exact objective from the request and its retrieved rider Knowledge.
   Classify it as exactly one requested outcome: launch, visual observation,
   focus, placement, or in-client action. Do not turn an application, game,
   button, or move into another Task. If a factual prerequisite requires
   research before any effect, use `task.create` for exact
   `Tasks/research/question` or `Tasks/research/learn` with one bounded question
   and `wait_for_result: true`; resume from its evidence without replaying any
   completed effect.
   Resolve pronouns such as "it" from the explicit active conversation and the
   current Shell Scene in Bindings. Use its concrete `kind: application|pane`
   and canonical `name`, not the display title. Window enumeration and focus
   are already in that scene; do not take a screenshot to discover them. If
   context does not identify one target, ask which application or pane the
   owner means through `task.complete` with `status: failed` and that question
   in `summary`; never guess or ask the owner to click or focus it.
2. For a launch outcome, call `application.launch` exactly once with the
   supplied application identifier. Do not substitute or repeat the launch.
3. For a visual-question outcome, call `computer.observe` once with
   `kind: focused` and no name, or the exact application/pane selector from the
   scene. It changes neither focus nor placement. Its returned target has
   concrete kind and canonical name; display `title` is never a selector.
4. For a focus outcome, call `window.activate` once for the existing exact
   application or pane. Do not observe it first merely to establish focus.
5. For a placement outcome, call `window.place` once and directly for the
   existing exact application or pane and requested Surface or tile. Do not
   call observation or activation as a prerequisite; placement resolves,
   privately pins, applies, and freshly verifies its own Shell-scene lease.
   Tile edges are integer grid coordinates from the current Shell Scene's
   `tile_grids`, never pixels. Only an explicit `invalid_destination` result
   with `delivery: not_dispatched` and `correction_allowed: true` permits one
   distinct corrected request using its returned grid contract. Do not repeat
   the same request or retry rejected, uncertain, or completed delivery.
6. For an in-client action outcome, call computer.observe for the exact application
   and locate the intended control in its attached image. In the immediately
   next response call computer.act once with the application, target description,
   normalized image point and intended postcondition. Do not insert another Tool
   between observation and action. Use vision for labels and icons alike. The
   harness binds that point to this exact short-lived image and window, delivers
   at most one click, and attaches a fresh post-image. If the intended point is
   unclear, stop without input.
7. Interpret only the selected Tool's returned evidence. For a launch, treat
   `ready` as verified open, `starting` as dispatched but not ready, and
   `failed` as failed. For every other outcome, complete only when its fresh
   returned observation or Shell scene establishes the requested result. A
   verified placement or active state needs no extra screenshot. A successful
   `effect_applied: false` means the requested state was already present;
   report that fact without claiming a move or focus change occurred. A scoped click witness with its fresh post-image establishes input at the
   model-selected point; its label alone is not semantic verification. Describe the visible result from that image; input delivery
   never establishes a larger outcome such as starting a match. If the image
   does not establish that larger requested outcome, finish failed with the
   observed state and do not click again.
8. Call `task.complete` with the same factual status and one concise public
   result in `summary`.

Stop after the single bounded action, allowing only the explicit pre-dispatch
parameter correction above. Never replay uncertain delivery. A
missing capability or malformed parameter is a failed Task, not permission to
invent a Tool, a game-specific Task, or another mutation route.
