---
title: create-a-runbook
kind: runbook
owner_maintained: true
---
Procedure for drafting a new runbook when a task is blocked `awaiting-runbook`.

1. `search_vault` for existing runbooks covering the need. If one fits,
   propose updating the blocked task's `runbook:` link instead of writing a
   duplicate — then finish with status `review`.
2. Read the blocked task's note and acceptance criteria with `read_note`.
3. Draft the runbook body: imperative, numbered, deterministic steps; explicit
   stop-and-report conditions; expected artifacts stated so acceptance can be
   checked; safety boundaries (what must never be done).
4. `propose_note` with `action: create`, target `Runbooks/<slug>.md`,
   frontmatter kind `runbook`, and a reason linking the blocked task.
5. Finish with status `review` and a one-line summary naming the proposal.
