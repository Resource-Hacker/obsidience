---
type: tool
title: model.source
description: Register the current immutable Source identity of a registered model
  using model_id.
obsidience:
  binding: capability:model.source
  source: obsidience/harness/capabilities/model/source.py
---

## Runtime

Register the current immutable Source identity of a registered model using model_id. This attests artifact identity; it does not benchmark, download or accept performance claims.

## Reference

Register or verify one local model artifact as an immutable Source manifest.

Argument: `{"model_id": "<exact registered ID>"}`.

The manifest records the artifact locator, size, verification material,
runtime binding, quantization, capabilities, and supported device sets. It
returns the exact manifest path and fingerprint. Repeating the call for the
same artifact revision is idempotent. It does not copy multi-gigabyte weights,
load the model, or grant execution authority.
