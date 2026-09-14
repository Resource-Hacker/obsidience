---
type: task
title: Check
obsidience:
  assignee: '[[Agents/Heimdall/Heimdall]]'
  model: auto
  reasoning_effort: xhigh
  runbook: '[[Runbooks/check]]'
  taxonomy_path: wiki/check
---

Inspect one deterministic Obsidience harness snapshot and report its observed
health without shell access, repair attempts, or inferred success. Completion
means the inspection and report succeeded. A valid degraded finding remains a
successful Check with an explicitly degraded result; only failure to obtain or
report the required snapshot fails the Check execution.

Include relevant recurring execution patterns from that same snapshot, with
their bounded sample and recorded revision. Keep this historical evidence
separate from the present healthy or degraded finding.

After a completed degraded result, the existing controller emits
`harness.degraded` to Heimdall's separate Repair Task. Check remains inspection
and never performs recovery itself.
