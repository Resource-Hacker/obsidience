---
type: skill
title: Using model.inspect
description: Inspect the named model's current Source and layouts.
obsidience:
  tool: '[[Tools/model.inspect]]'
---

## Runtime

Inspect the named model's current Source and layouts. Hardware capacity, valid placement and benchmark results are separate facts. Do not assume CPU fallback or combine incompatible device layouts.

## Reference

Use `model.inspect` to read the current registered definition and installed
state of one local model.

- Pass exactly `{"model_id": str}` using one exact registered model ID.
- Success returns the executable definition, role and capabilities, installed
  artifact state, immutable Source manifest, valid GPU layouts, active
  configuration, prior benchmark, and current NVIDIA memory snapshot.
- Treat only the returned device sets as valid layouts and distinguish a
  text-generating model from a real-time interface component using the returned
  role. The Tool is read-only apart from idempotent manifest verification.
- Stop on `Model inspection rejected`, an unknown model, or an absent artifact,
  verifier, runtime, or manifest. Do not infer missing properties from the
  model name or retry with an approximate ID.
