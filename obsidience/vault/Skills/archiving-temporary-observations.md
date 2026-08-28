---
kind: skill
title: Archive temporary observations
tool: '[[Tools/observations.temporary.archive]]'
---

Use `observations.temporary.archive` exactly once for the runtime-bound bundle.

- Pass only `{}`; never select paths or reconstruct source content.
- Treat a returned Source citation and hash as proof of preservation, not
  proof that each archived statement is true.
- Reuse the same citation when the Tool reports an existing archive.
- If the Tool rejects scope or attestation, stop without staging durable
  Knowledge. Never work around the failure with generic Source ingestion.
