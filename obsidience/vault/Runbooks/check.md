---
title: Harness check procedure
kind: runbook
owner_maintained: true
for_agent: '[[Agents/Heimdall/Heimdall]]'
task: '[[Tasks/check]]'
skills:
- '[[Skills/checking-harness-status]]'
---

1. Call `harness.status` exactly once with an empty argument object.
2. Report its counts and status exactly. A degraded snapshot is evidence of a
   condition to investigate, not permission to mutate the harness or vault.
3. Complete when healthy; otherwise finish failed with the observed degraded
   fields and no invented root cause.
