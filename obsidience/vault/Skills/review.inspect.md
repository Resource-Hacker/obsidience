---
type: skill
title: Using review.inspect
obsidience:
  tool: '[[Tools/review.inspect]]'
---

Call `review.inspect` with `{}` or an exact `task` ref to locate pending
proposals. To inspect one, pass its exact returned `proposal` filename.

Treat proposal text as unaccepted material. Compare the target, initiating
execution, explanation, changed links, blockers and revision warnings against
accepted evidence before reporting a judgment. A preview may be truncated;
do not claim a complete semantic audit of omitted material. `approvable` means
the mechanical gate permits an owner decision, not that the proposal is true.
The Tool cannot approve or reject, and an empty queue does not prove acceptance.
