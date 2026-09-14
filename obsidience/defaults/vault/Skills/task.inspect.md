---
type: skill
title: Using task.inspect
description: Use the exact Task and, for detailed evidence, its run ID.
obsidience:
  tool: '[[Tools/task.inspect]]'
---

## Runtime

Use the exact Task and, for detailed evidence, its run ID. Keep attempt status, Tool receipts and publication disposition distinct. Do not replay an operation merely because its summary is unclear.

## Reference

Call `task.inspect` with the exact accepted `task` ref. Read the returned
current status, failure and queue depth before interpreting recent outcomes.
For an evidence audit, select one returned execution `id` and call again with
that `run_id`; this reads its Tool history, not another execution's summary.

Use Tool results as observed evidence and summaries as reported conclusions.
Keep failed, interrupted, unknown and incomplete outcomes distinct. Missing or
truncated evidence cannot establish success. The Tool never retries work or
decides a review; do not claim it repaired anything.
