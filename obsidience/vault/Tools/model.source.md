---
binding: capability:model.source
kind: tool
source: obsidience/harness/capabilities/model/source.py
title: model.source
---

Register or verify one local model artifact as an immutable Source manifest.

Argument: `model_id` is one exact registered model ID.

The manifest records the artifact locator, size, verification material,
runtime binding, quantization, capabilities, and supported device sets. It
does not copy multi-gigabyte weights, turn Source into Knowledge, or grant the
model execution authority.
