---
type: skill
title: Using source.ingest
obsidience:
  tool: '[[Tools/source.ingest]]'
---

Use `source.ingest` to preserve one exact bounded raw-evidence payload.

- Pass `content` as 1-500,000 exact characters. `source_ref` is optional and
  capped at 2,000 characters. `source_type` is
  `user|tool|document|import|recovery|research` and defaults to `tool`;
  `media_type` is `text/plain|text/markdown|application/json` and defaults to
  `text/markdown`. `captured_at` is an optional timezone-aware ISO-8601 value.
  Include one independently attributable source and do not rewrite, merge,
  clean up, or complete missing content.
- Success reports `captured` or idempotent `already captured`, a stable
  `source://` citation, and the content SHA-256. A new capture may also report
  the count of emitted source-event activations.
- The citation and hash identify preserved bytes; they do not attest that the
  source is true or complete.
- Stop on `Source rejected`, invalid type or media type, empty content, invalid
  capture time, unsafe or oversized material, or failed
  persistence. Do not retry by altering the evidence bytes.
