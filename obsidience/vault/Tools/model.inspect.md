---
type: tool
title: model.inspect
obsidience:
  binding: capability:model.inspect
  source: obsidience/harness/capabilities/model/inspect.py
---

Read one registered local model's executable definition, installed artifact
state, immutable Source manifest, valid GPU layouts, active configuration,
capabilities, prior benchmark, and current NVIDIA memory snapshot.

Argument: `{"model_id": "<exact registered ID>"}`.

This Tool is read-only apart from idempotently verifying the model's immutable
Source manifest. It returns `model`, `source`, and the current two-GPU snapshot;
it does not load, benchmark, configure, or assign the model.
