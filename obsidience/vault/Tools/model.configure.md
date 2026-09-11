---
type: tool
title: model.configure
description: 'Update one registered model with model_id and at least one supported
  setting: allowed_devices, context_tokens, max_output_tokens, gpu_memory_utilization
  or max_num_seqs.'
obsidience:
  binding: capability:model.configure
  source: obsidience/harness/capabilities/model/configure.py
---

## Runtime

Update one registered model with model_id and at least one supported setting: allowed_devices, context_tokens, max_output_tokens, gpu_memory_utilization or max_num_seqs. The resource owner validates and reconciles settings. Observe cancellation-after-commit and reconciliation warnings. Never replay an uncertain committed change.

## Reference

Apply one bounded configuration to a registered local model through the same
validator used by the Models Reader.

Arguments:

- `model_id`: exact registered model ID;
- `allowed_devices`: optional list containing `rtx4080`, `rtx4000`, or
  one validated combination;
- `context_tokens`: optional integer from 2,048 through the model's declared
  maximum;
- `max_output_tokens`: optional integer from 256 through 32,768 and smaller
  than the resulting context;
- `gpu_memory_utilization`: optional number from 0.50 through 0.99;
- `max_num_seqs`: optional integer from 1 through 32.

At least one optional setting is required.

Supply only exact GPU IDs. The current runtime filters unknown IDs and may
restore the model's default layout when too few valid IDs remain; always check
the returned `allowed_devices`. Other bounded values and an output size not
smaller than context are rejected. CPU offload is unavailable.

The call may restart the model, preserves unrelated hardware slots, and stores
a new immutable configuration record on success. If startup fails, inspect the
current model configuration before retrying; a failed restart does not
guarantee that the prior settings were restored.
