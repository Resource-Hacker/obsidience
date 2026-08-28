---
assignee: '[[Agents/Darwin/Darwin]]'
enabled: true
kind: task
last_run: 49e32b5c8fa4
model: obsidience-qwen38-27b-q8
params:
  benchmark_kind: tokens
  change: revision
  event: model.added
  hardware_assignable: true
  model_event_id: model-18cfe3f9ddb292ec
  model_fingerprint: sha256:090d8281842545e20c7dc18989085e4b0ca9ae8e1ee64bde16a17a486c3ba26e
  model_id: obsidience-gemma
  model_label: Gemma 4 26B-A4B
  source_path: obsidience/evidence/models/obsidience-gemma/artifact--090d8281842545e2.json
  task_capable: true
  valid_device_sets:
  - - rtx4000
reasoning_effort: xhigh
runbook: '[[Runbooks/research/model]]'
status: completed
status_updated: '2026-08-27T23:29:17'
summary: 'Characterized the revised model obsidience-gemma (Gemma 4 26B-A4B, fingerprint
  sha256:090d8281842545e20c7dc18989085e4b0ca9ae8e1ee64bde16a17a486c3ba26e) as a task-capable
  task_reasoning model for responsive Executive conversation and Task dispatch (capabilities:
  text, reasoning, tools; llama.cpp b10078, Q4_K_XL, 14,249,047,104 B). Immutable
  Source manifest verified at obsidience/evidence/models/obsidience-gemma/artifact--090d8281842545e2.json.
  Benchmarked the single valid device set, rtx4000 alone (contract obsidience.model-comparison.v1,
  common prompt, 256-token ceiling, temperature zero, 1 warmup, 3 samples): TTFT 56.85
  ms (p95 71.12 ms), 102.03 aggregate end-to-end tok/s over 768 completion tokens
  in 7.527 s, receipt preserved at obsidience/evidence/models/obsidience-gemma/benchmarks/benchmark--20260827-232558-18cfe415a6b6c8d6.json;
  no other valid layout exists (rtx4080 is outside valid_device_sets), so no layouts
  were rejected by fit. Applied the smallest coherent configuration and re-inspected:
  allowed_devices [rtx4000], context_tokens 16384, max_output_tokens 3584, gpu_memory_utilization
  0.9, max_num_seqs 1 — it passed the runtime validator without CPU offload (14.25
  GB artifact fits the 20,475 MiB RTX 4000 Ada at 0.9 utilization, leaving output
  reserve within context). Final inspection confirmed the saved settings, manifest
  fingerprint, latest benchmark record, and restored Hardware state (rtx4000 assigned,
  no active lease, model inactive) all match the pre-benchmark snapshot. Verified
  compatibility result: safe, fully GPU-resident standalone operation on one RTX 4000
  Ada for Task work.'
taxonomy_path: research/model
title: Model
triggered_at: '2026-08-27T23:24:03'
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
