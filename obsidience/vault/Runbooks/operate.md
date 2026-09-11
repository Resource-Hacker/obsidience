---
type: runbook
title: Computer Use procedure
obsidience:
  operation_tools:
    launch:
    - '[[Tools/application.launch]]'
    focus:
    - '[[Tools/window.activate]]'
    placement:
    - '[[Tools/window.place]]'
    observe:
    - '[[Tools/computer.observe]]'
    action:
    - '[[Tools/computer.observe]]'
    - '[[Tools/computer.act]]'
    - '[[Tools/vault.read]]'
    - '[[Tools/vault.search]]'
    - '[[Tools/task.create]]'
    - '[[Tools/observations.temporary.append]]'
  runtime_sections:
    launch: Launch
    focus: Focus
    placement: Placement
    observe: Observe
    action: Action
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
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/observations.temporary.append]]'
  approved_at: '2026-09-06T01:04:55'
  provenance: proposed by Codex (task codex:knowledge-handoff)
  required_context:
  - '[[ADMECH Workstation/Workstation Observations/agent-launch-and-gui-application-management--339f2788]]'
---

## Runtime

Follow only the current owner Objective and controller computer_outcome/scope. Historical dialogue resolves references, not permission for a new effect. Use exact semantic targets and current evidence. Stop on ambiguity, lock, stale identity, missing capability, cancellation or uncertain delivery. Never invent another Tool or replay an uncertain effect. Finish through task.complete with the actual evidenced result.

## Launch

Call application.launch once with the supplied registered identifier. Its bounded scene wait belongs to that same dispatch. ready means open, not focused. Report already open when dispatched:false. A readiness timeout is unresolved, not permission to launch again. Complete only with the returned ready witness.

## Focus

Call window.activate on the exact current target. Its verified scene establishes focus; no prerequisite screenshot is needed. An already active result is not a new effect.

## Placement

Call window.place using the exact target and current Surface tile edges. Use its verified post-scene. Only an explicit not_dispatched correction allowance permits one distinct corrected request. Never repeat uncertain delivery.

## Observe

Call computer.observe for the exact target and question. Interpret the attached current image and report its limitations. Observation does not change focus, placement, or application state.

## Action

Use sufficient supplied context; retrieve only a specific missing fact from this Agent's graph. If external evidence is essential, delegate a bounded Question/Learn before input. Then observe the exact application and immediately call computer.act at the image-selected point. input means one click; state means the requested result, with at most three verified distinct steps. Inspect each post-image, stop at the requested goal, and obtain a new observe lease before another click. For completed state outcomes provide verification:{status:established,observation:<current visible evidence>}. Inconclusive images permit read-only observation, never repeating uncertain input.

## Reference

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


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Do not record hidden reasoning or create a note merely to narrate routine work.
