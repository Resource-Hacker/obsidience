---
approved_at: '2026-08-25T18:10:36'
binding: builtin:model.benchmark
kind: tool
provenance: proposed by Codex (task codex:knowledge-handoff)
sources:
- harness/obsidience/model_runtime.py
- harness/obsidience/tools.py
title: model.benchmark
---

Run one standalone comparison for one registered text-generating model on one exact valid GPU layout.

Every model, including a component that is normally paired, runs alone with the exact common prompt, a 256-token ceiling, temperature zero where supported, one discarded warmup, and three measured samples.

Primary TTFT is the median duration from request dispatch to first public output. Primary end-to-end throughput is aggregate actual public completion tokens divided by aggregate complete request wall time, including TTFT and prompt processing. For an atomic diffusion model, completion of the first generated block is the first public output.

Pair, frame, interruption, audio, startup, planner-quality, and confirmation measurements are secondary diagnostics only. They never substitute for the model's standalone result.

The Tool temporarily leases only the requested GPUs, preserves the complete benchmark receipt in the model's Source folder, and restores the saved Hardware selection afterward. Invalid layouts fail explicitly and never spill layers to CPU.
