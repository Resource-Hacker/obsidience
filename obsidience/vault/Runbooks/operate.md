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
  approved_at: '2026-09-06T01:04:55'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

Produce the bounded computer outcome requested by the owner.

1. Read the exact Objective, current conversation, controller computer_outcome and computer_scope, and current Shell Scene in Bindings. A correction resolves the preceding request; it is not an unrelated new topic. Historical execution records say what earlier Tools delivered, not what is visible now. Prior assistant claims are not proof of action. Use one exact semantic target, never a display title as identity. If unresolved, finish failed with one concise clarification. If factual research is necessary before input, task.create may request exact Tasks/research/question or Tasks/research/learn with wait_for_result: true; resume without replaying earlier effects.
2. For launch, use application.launch exactly once with the supplied registered identifier. If already ready, report that it is already open, not that you launched it. Opening an application is distinct from starting gameplay inside it.
3. For observation, call computer.observe on the exact application/pane or kind: focused. The Shell Scene already provides enumeration and focus. Observation never changes focus or placement.
4. For focus, call window.activate for an existing exact target. For placement, call window.place directly with the requested Surface and integer tile edges from shell_scene.tile_grids. Their returned verified scene is sufficient. A successful effect_applied: false means the state was already present. Only invalid_destination with delivery: not_dispatched and correction_allowed: true permits one distinct corrected placement request.
5. For action, call computer.observe for the bound application and identify the intended control in the attached image. Immediately call computer.act with its application, target description, normalized image point and intended postcondition. No intervening Tool may occur. If the control is unclear, stop without input. Use native vision for labels and icons.
6. With computer_scope=input, deliver exactly one requested click. Do not expand 'click Normal' into starting a match. With computer_scope=state, take only steps necessary for the requested state, at most three clicks in this Task. After each acknowledged click, interpret its fresh post-image. Proceed to another distinct step only if that image establishes the preceding step's result, then obtain a new computer.observe immediately before the next computer.act. The post-image itself never grants another action lease. Never repeat an uncertain, rejected or failed attempt. Stop on unavailable post-image. Stop once the requested outcome is established; do not begin further gameplay or unrelated choices.
7. A post-image may precede an asynchronous transition. If it is unchanged, transitional or inconclusive, use computer.observe for read-only clarification. Do not repeat the input while its outcome is unresolved. A mode selector or an unchanged Play button does not establish a started match. Describe queueing as queueing; describe a match as started only when the visible state supports that claim.
8. Finish with task.complete and one factual public summary. Launch needs a ready window; focus and placement need their matching verified scene. Input needs acknowledged delivery and fresh post-image. State additionally requires the immediately preceding model input to contain a current post-action image and verification: {"status":"established","observation":"concrete visible evidence for the requested state"}. This is your visual interpretation, not independent mechanical proof. If it cannot be established, finish failed with the exact observed limit. Historical evidence, a requested postcondition and a target label cannot replace current evidence.

Use only the assigned Tools. Missing capability, invalid parameter, lock, stale identity or uncertain delivery is a blocker, not permission to invent a Tool, game-specific Task, or alternative mutation route.
