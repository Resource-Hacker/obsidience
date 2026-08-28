---
binding: capability:source.handoff
kind: tool
source: obsidience/harness/capabilities/source/handoff.py
title: source.handoff
---

Drop one bounded, source-backed Darwin synthesis into the physical Source
Inbox. This Tool is available only inside a Darwin Research Task.

Arguments:

- `title`: a short human title for the finding.
- `content`: the self-contained Markdown synthesis, including at least one
  exact `source://<uuid>` citation.

The Tool resolves every citation before it writes an immutable file beneath
`obsidience/evidence/inbox/`. A new handoff emits `source.inbox` exactly once; Alexandria's
centralized Ingest Task is the sole subscriber. It never creates a Knowledge
Article, stages a Review, or writes the vault.
