---
title: Check harness status
kind: skill
tool: '[[Tools/harness.status]]'
---

Use `harness.status` for one deterministic read-only snapshot.

- Call it once with an empty object when a deterministic harness snapshot is
  the requested evidence.
- Report every status and count exactly; do not convert “degraded” into a
  diagnosis or infer that an unlisted subsystem is healthy.
- Treat recent failures as bounded ledger observations, not proof that the
  current condition has the same cause.
- This Tool is read-only. Use a separate authorized Task and Runbook for any
  investigation or repair.
