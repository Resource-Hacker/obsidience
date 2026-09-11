---
type: skill
title: Using model.benchmark
description: Benchmark only valid layouts for the exact event model.
obsidience:
  approved_at: '2026-08-25T18:19:10'
  provenance: proposed by Codex (task codex:knowledge-handoff)
  tool: '[[Tools/model.benchmark]]'
---

## Runtime

Benchmark only valid layouts for the exact event model. Preserve every failure and restore the saved hardware selection. Compare equivalent settings; do not treat an incomplete measurement as a verified performance result.

## Reference

Use `model.benchmark` to measure one registered text-generating model by itself
on one declared valid device layout.

- Pass exactly `{"model_id": str, "devices": ["rtx4080"|"rtx4000", ...]}`
  with a nonempty device list that is valid for that exact model revision.
- A successful result carries contract `obsidience.model-comparison.v1`, the
  exact common-prompt measurements, an immutable receipt path, and confirmation
  that the prior hardware selection was restored. Compare only receipts with
  that contract and compatible standalone layouts.
- Interpret primary TTFT as median dispatch-to-first-public-output time and
  primary throughput as aggregate public completion tokens divided by complete
  request wall time. Treat all labeled frame, audio, startup, interruption, and
  pair measurements as secondary diagnostics.
- Stop on a missing model ID, empty or invalid device layout, artifact/runtime
  failure, CPU spill, incomplete receipt, failed restoration, or a returned
  `rejected`/`failed` result. Do not retry by changing the declared layout.
