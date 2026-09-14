---
type: tool
title: model.benchmark
description: Measure one registered model using model_id and devices.
obsidience:
  binding: capability:model.benchmark
  source: obsidience/harness/capabilities/model/benchmark.py
---

## Runtime

Measure one registered model using model_id and devices. The existing resource owner validates the layout and restores saved assignments. Preserve measured failures as failures. CPU offload or an unapproved model substitution is not authorized.

## Reference

Run one standalone comparison for one registered text-generating model on one exact valid GPU layout.

Arguments: `{"model_id": str, "devices": ["rtx4080"|"rtx4000", ...]}`.
The device list must be nonempty and match one declared layout for that exact
model revision.

Every model, including a component that is normally paired, runs alone with the exact common prompt, a 256-token ceiling, temperature zero where supported, one discarded warmup, and three measured samples.

Primary TTFT is the median duration from request dispatch to first public output. Primary end-to-end throughput is aggregate actual public completion tokens divided by aggregate complete request wall time, including TTFT and prompt processing.

Pair, frame, interruption, audio, startup, planner-quality, and confirmation measurements are secondary diagnostics only. They never substitute for the model's standalone result.

The Tool temporarily leases only the requested GPUs, returns TTFT, end-to-end
tok/s, duration, token count, sample metrics, and the Source receipt path, then
restores the saved Hardware selection. Every successful call records a new
measurement; repeat it only when another sample is intended. Invalid effective
layouts fail and model layers never spill to CPU.
