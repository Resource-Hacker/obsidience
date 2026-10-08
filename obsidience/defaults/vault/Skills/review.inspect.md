---
type: skill
title: Using review.inspect
description: Inspect the existing proposal disposition before making another change.
obsidience:
  tool: '[[Tools/review.inspect]]'
---

## Runtime

Inspect the existing proposal disposition before making another change. Missing or truncated records do not prove approval or rejection. A successful execution can still be awaiting publication Review.

## Reference

Call `review.inspect` with `{}` or an exact `task` ref to locate pending
proposals. To inspect one, pass its exact returned `proposal` filename.

Treat proposal text as unaccepted material. Compare the target, initiating
execution, explanation, changed links, blockers and revision warnings against
accepted evidence before reporting a judgment. A preview may be truncated;
do not claim a complete semantic audit of omitted material. `approvable` means
the mechanical gate permits an owner decision, not that the proposal is true.
The Tool cannot approve or reject, and an empty queue does not prove acceptance.

For `review_class: health`, report the unresolved recovery reason and exact initiating Task/run. This is an operational notification, not an Article proposal. Its acknowledgement records that the owner saw it; it never marks the Task healthy, approves content or authorizes replay. An empty queue does not prove healthy status.
