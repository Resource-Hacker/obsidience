---
title: Configure a model
kind: skill
tool: '[[Tools/model.configure]]'
---

Use `model.configure` only after inspecting the model and benchmarking the
candidate layout.

- Change only settings supported by the returned contract.
- Prefer the smallest context that comfortably covers the assigned Task class;
  retrieval supplies focused Knowledge instead of an oversized idle KV cache.
- Preserve enough output room for the selected reasoning effort and visible
  answer.
- Keep all model layers on the selected GPU set. Never solve a fit failure by
  enabling CPU offload.
- Change one consequential variable at a time when comparing performance.
- Do not alter Task identity, reasoning effort, Tool authority, or unrelated
  Hardware slots through this Tool.
