---
title: Inspect a model
kind: skill
tool: '[[Tools/model.inspect]]'
---

Call `model.inspect` first with the exact event `model_id`.

- Treat only returned device sets as valid test layouts.
- Distinguish Task models from real-time interface components.
- Compare free VRAM with the complete installed artifact and configured
  context; never propose CPU spill as a fit strategy.
- Treat an absent artifact, verifier, runtime, or Source manifest as a failed
  prerequisite rather than guessing from the model name.
- Reinspect after configuration to verify the saved result.
