---
title: Computer Use procedure
kind: runbook
owner_maintained: true
for_agent: '[[Agents/Executive/Executive]]'
task: '[[Tasks/executive/operate]]'
skills:
- '[[Skills/launching-an-application]]'
- '[[Skills/observing-the-computer]]'
- '[[Skills/acting-on-the-computer]]'
---

Produce one bounded computer effect requested by the owner.

1. Read the exact objective from the request and its retrieved rider Knowledge.
   Do not turn an application, game, button, or move into another Task.
2. For an application launch, call `application.launch` exactly once with the
   supplied application identifier. Do not substitute or repeat the launch.
3. For an interaction, call `computer.observe` with the exact application and
   semantic target. Stop on a missing, ambiguous, hidden, or changed target.
4. Call `computer.act` once with that same target and the intended
   postcondition. The Tool reobserves, revalidates, delivers at most one click,
   and returns a fresh post-observation without exposing privileged coordinates
   or tokens.
5. Read the returned `assistant_status` for a launch. Treat `ready` as verified open,
   `starting` as dispatched but not ready, and `failed` as failed.
   For an interaction, treat delivery acknowledgement only as input evidence;
   complete only when the fresh post-observation establishes the requested
   result.
6. Call `task.complete` with the same factual status in one concise sentence.

Stop after the single bounded action. Never replay uncertain delivery. A
missing capability or malformed parameter is a failed Task, not permission to
invent a Tool, a game-specific Task, or another mutation route.
