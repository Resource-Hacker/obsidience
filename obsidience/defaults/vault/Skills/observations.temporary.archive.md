---
type: skill
title: Using observations.temporary.archive
description: Archive only the exact event-bound bundle, preserving original hashes
  and Source citations.
obsidience:
  tool: '[[Tools/observations.temporary.archive]]'
---

## Runtime

Archive only the exact event-bound bundle, preserving original hashes and Source citations. Archival does not accept its claims. Promotion must independently reconcile useful findings with accessible durable Knowledge.

## Reference

Use `observations.temporary.archive` to preserve the exact temporary-observation
bundle already bound to the call.

- Pass exactly `{}`. The Tool does not accept a path, selector, or reconstructed
  content.
- A successful result returns the archive citation and content hash. An
  existing matching archive is an idempotent success and returns the same
  evidence.
- A new archive emits the ordinary `source.added` event and records its citation
  in each bound Temporary Article's metadata without changing the Article body.
- Treat the citation and hash as preservation evidence only; they do not attest
  the truth of the archived statements.
- On a missing runtime bundle, invalid scope, or failed content attestation,
  stop. Do not retry with modified arguments or reconstruct the bundle.
