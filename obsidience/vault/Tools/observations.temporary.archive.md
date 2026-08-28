---
binding: capability:observations.temporary.archive
kind: tool
source: obsidience/harness/capabilities/observations/temporary/archive.py
title: observations.temporary.archive
---

Archive the exact committed Temporary Observation Articles bound by the active
Alexandria promotion event into Obsidience Source blob storage.

Arguments: `{}`. The runtime supplies the conversation, promotion key, final
sequence, and Article refs. The Tool rejects model-selected paths, uncommitted
or mismatched Articles, and altered event scope. It copies canonical Markdown
with its original SHA-256, returns stable `source://` citations, and is
idempotent. It never summarizes, deletes Temporary context, edits Knowledge,
or accepts a proposal.
