---
title: Complete task
kind: skill
tool: '[[Tools/task.complete]]'
---
How to use `task.complete` to end one task session.

- Call it exactly once after the runbook reaches a terminal condition.
- Use `completed`, `review`, or `failed` honestly and summarize the verified
  result, proposal, or blocker without claiming unobserved success.
- Use `review` only after this exact execution stages a proposal or reaches an
  explicit acceptance gate authored on its Task. A deferred downstream
  activation completes as an honest no-change result, not `review`.
- If completion reports that a Merge archive lacks redirect proposals, read
  every exact missing Article, stage each complete redirect update, and retry;
  never finish with an incomplete Merge warning.
- A runbook that cannot be followed ends `failed` with the concrete reason.
