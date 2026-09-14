---
type: tool
title: observations.temporary.archive
description: Preserve the exact controller-bound Temporary Observation bundle as immutable
  Source.
obsidience:
  binding: capability:observations.temporary.archive
  source: obsidience/harness/capabilities/observations/temporary/archive.py
---

## Runtime

Preserve the exact controller-bound Temporary Observation bundle as immutable Source. No arguments. This is provenance for promotion, not acceptance of durable claims. Do not replace Source history.

## Reference

Archive the exact committed Temporary Observation Articles bound by the active
Alexandria promotion event into Obsidience Source blob storage.

Arguments: `{}`. The runtime supplies the conversation, promotion key, final
sequence, and Article refs. The Tool rejects model-selected paths, uncommitted
or mismatched Articles, and altered event scope. It copies canonical Markdown
with each original SHA-256, returns the bundle citation and archived Article
refs, and records that citation in each Temporary Article's metadata without
rewriting its body. Repeating the same event is idempotent. A newly created
archive is an ordinary raw Source and emits its normal `source.added` event.
The Tool never summarizes, deletes context, edits durable Knowledge, or accepts
a proposal.
