---
type: task
title: Model
obsidience:
  assignee: '[[Agents/Heimdall/Heimdall]]'
  enabled: true
  model: auto
  reasoning_effort: xhigh
  runbook: '[[Runbooks/research/model]]'
  taxonomy_path: harness/model
  triggers:
  - model.added
---

Characterize one newly registered or revised local model and leave it with an
attested Source manifest, measured valid hardware layouts, a bounded working
configuration, and a concise verified compatibility result.

Acceptance requires the exact event model to be inspected, every relevant
valid layout to have a preserved benchmark or explicit failure, the selected
settings to pass runtime validation without CPU offload, and the saved
Hardware selection to be restored.

Heimdall owns this operational model characterization. Darwin retains external model research. A removed event model is settled from exact receipts rather than benchmarked again. An external model without local configurable device sets is inspected and reported without invoking local benchmark or configuration.
