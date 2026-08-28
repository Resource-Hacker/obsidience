---
binding: capability:model.configure
kind: tool
source: obsidience/harness/capabilities/model/configure.py
title: model.configure
---

Apply one bounded configuration to a registered local model through the same
validator used by the Models Reader.

Arguments:

- `model_id`: exact registered model ID;
- `allowed_devices`: optional list containing `rtx4080`, `rtx4000`, or
  one validated combination;
- `context_tokens`, `max_output_tokens`, `gpu_memory_utilization`, and
  `max_num_seqs`: optional bounded settings.

The call rejects invalid device layouts, CPU offload, output larger than
context, and values outside the model contract. It may restart that model,
preserves unrelated hardware slots, and stores an immutable configuration
record in Source.
