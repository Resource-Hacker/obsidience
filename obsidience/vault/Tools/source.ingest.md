---
binding: capability:source.ingest
kind: tool
source: obsidience/harness/capabilities/source/ingest.py
title: source.ingest
---

Capture one bounded source payload in the immutable raw-evidence ledger.

Arguments:

- `source_ref`: the direct URL, document identifier, or acquisition reference.
- `content`: the exact text, Markdown, or JSON being preserved.
- `source_type`: `tool`, `document`, `user`, `import`, or `recovery`.
- `media_type`: `text/plain`, `text/markdown`, or `application/json`.
- `captured_at`: an optional timezone-aware ISO-8601 timestamp.

The Tool returns a stable `source://<uuid>` citation. Creating a new raw Source
emits the ordinary `source.added` event exactly once and activates Darwin's
existing Learn research Task. Re-capturing identical material returns the
existing Source and emits no event. Supporting Sources captured inside that
active Learn occurrence coalesce into it rather than recursively queueing the
same research. The Tool never writes the physical Inbox or a Knowledge Article;
that distinct operation is `source.handoff`.
