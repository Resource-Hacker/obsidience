---
type: skill
title: Using model.source
obsidience:
  tool: '[[Tools/model.source]]'
---

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
