---
binding: capability:model.inspect
kind: tool
source: obsidience/harness/capabilities/model/inspect.py
title: model.inspect
---

Read one registered local model's executable definition, installed artifact
state, immutable Source manifest, valid GPU layouts, active configuration,
capabilities, prior benchmark, and current NVIDIA memory snapshot.

Arguments: `model_id` is one exact ID returned by the Models catalog.

This Tool is read-only apart from idempotently verifying the model's immutable
Source manifest. It does not load, benchmark, configure, or assign the model.
