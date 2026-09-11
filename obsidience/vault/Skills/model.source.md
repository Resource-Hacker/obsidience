---
type: skill
title: Using model.source
description: Register only a present, known artifact.
obsidience:
  tool: '[[Tools/model.source]]'
---

## Runtime

Register only a present, known artifact. Source identity is not performance evidence. Follow the model characterization Task for measurement and leave existing accepted model selections unchanged unless explicitly authorized.

## Reference

Use `model.source` to register or verify the immutable Source manifest for one
registered local model artifact.

- Pass exactly `{"model_id": str}` using one exact registered model ID.
- Success returns the manifest's project-relative Source path and artifact
  fingerprint. An unchanged artifact is an idempotent verification; no model
  weights are copied.
- A different fingerprint identifies a different artifact revision and must
  not be interpreted as verification of the prior revision.
- Stop on `Model Source registration rejected`, an unknown model ID, missing
  artifact, failed verifier, or incomplete path/fingerprint result. Do not
  retry with an approximate ID or reconstructed manifest.
