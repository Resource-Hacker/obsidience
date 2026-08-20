---
title: create-a-runbook
kind: runbook
owner_maintained: true
skills: ["[[Skills/reading-the-vault]]", "[[Skills/proposing-changes]]"]
---
Procedure for drafting a new runbook when a task is blocked `awaiting-runbook`.

1. `vault.search` for existing runbooks covering the need. If one fits,
   propose updating the blocked task's `runbook:` link instead — then
   complete with status "review".
2. `vault.read` the blocked task and its acceptance criteria.
3. Draft the runbook: imperative numbered steps; explicit stop-and-report
   conditions; which skills it needs (frontmatter `skills:` links — the
   skills grant the tools); expected artifacts stated checkably.
4. `vault.propose` with action `create`, target `Runbooks/<slug>.md`,
   frontmatter kind `runbook`, reason linking the blocked task.
5. Complete with status "review", naming the proposal.
