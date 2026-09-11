---
type: skill
title: Using model.configure
description: Change only the requested supported fields.
obsidience:
  tool: '[[Tools/model.configure]]'
---

## Runtime

Change only the requested supported fields. Preserve valid GPU residency and output/context bounds. A reconciliation warning may follow a committed setting; inspect the result before another call, rather than blindly repeating it.

## Reference

Use `model.configure` to apply one bounded configuration update to one
registered local model.

- Pass `model_id` plus at least one of `allowed_devices`, `context_tokens`,
  `max_output_tokens`, `gpu_memory_utilization`, or `max_num_seqs`; include no
  other settings. Use only exact supported `rtx4080`, `rtx4000`, or validated
  combinations in `allowed_devices`. `context_tokens` must be
  2,048 through that model's declared maximum; `max_output_tokens` must be 256
  through 32,768 and smaller than the resulting context; GPU memory utilization
  must be 0.50 through 0.99; and maximum sequences must be 1 through 32.
- A successful result echoes the saved model ID, device layout, context/output
  limits, memory utilization, sequence limit, and immutable Source manifest.
  The Tool may restart that model while preserving unrelated hardware slots.
- The current runtime discards unknown device IDs and may restore the model's
  default layout when too few valid IDs remain. Treat the returned
  `allowed_devices` as the saved truth. CPU offload and out-of-bounds numeric
  values remain invalid.
- Stop on `Model configuration rejected` or `Model configuration failed` and
  inspect the current configuration before another attempt: a failed restart
  does not guarantee restoration of the prior settings. Do not retry with
  guessed or relaxed limits.
