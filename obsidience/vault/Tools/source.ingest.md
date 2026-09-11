---
type: tool
title: source.ingest
description: Preserve external evidence as immutable Source using content, source_ref,
  source_type, media_type and optional captured_at.
obsidience:
  binding: capability:source.ingest
  source: obsidience/harness/capabilities/source/ingest.py
---

## Runtime

Preserve external evidence as immutable Source using content, source_ref, source_type, media_type and optional captured_at. The ordinary source.added event may admit research. This does not create accepted Knowledge or grant capabilities. Do not duplicate an already preserved source.

## Reference

Capture one bounded source payload in the immutable raw-evidence ledger.

Arguments:

- `content`: 1-500,000 characters of exact text, Markdown, or JSON;
- `source_ref`: optional acquisition reference, at most 2,000 characters;
- `source_type`: `user`, `tool`, `document`, `import`, `recovery`, or
  `research`; defaults to `tool`;
- `media_type`: `text/plain`, `text/markdown`, or `application/json`; defaults
  to `text/markdown`;
- `captured_at`: an optional timezone-aware ISO-8601 timestamp.

The Tool returns a stable `source://<uuid>` citation. Creating a new raw Source
emits the ordinary `source.added` event exactly once and activates Darwin's
existing Learn research Task. Re-capturing identical material returns the
existing Source and emits no event. Supporting Sources captured inside that
active Learn occurrence coalesce into it rather than recursively queueing the
same research. The Tool never writes the physical Inbox or a Knowledge Article;
it only preserves raw evidence.
