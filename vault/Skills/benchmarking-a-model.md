---
approved_at: '2026-08-25T18:04:05'
kind: skill
provenance: proposed by Codex (task codex:knowledge-handoff)
title: Benchmark a model
tool: '[[Tools/model.benchmark]]'
---

Use `model.benchmark` with the exact registered model revision and one declared valid hardware layout. Compare only receipts carrying contract `obsidience.model-comparison.v1`.

Run the exact common prompt with a 256-token ceiling, temperature zero where supported, one discarded warmup, and three measured samples. Count actual public completion tokens with the model tokenizer or provider usage.

Report median request-to-first-public-output TTFT and aggregate end-to-end tok/s over complete request wall time. For an atomic diffusion model, treat completion of its first generated block as first public output.

Keep frame cadence, interruption acknowledgement, audio latency, startup, pair confirmation, and planner quality clearly labeled as secondary. Never compare a standalone receipt with a pair receipt, candidate-fragment timing, or a provider's steady-decode number.

Preserve the Source receipt, preserve explicit failures, prevent CPU spill, and confirm that the saved Hardware assignment has been restored before concluding.
