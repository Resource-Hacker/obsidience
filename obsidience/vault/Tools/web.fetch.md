---
binding: capability:web.fetch
kind: tool
source: obsidience/harness/capabilities/web/fetch.py
title: web.fetch
---

Fetch one public HTTP or HTTPS page through the bounded research acquisition
path. Private, loopback, link-local, credential-bearing, oversized, binary,
and unsafe redirect targets fail closed.

Argument: `url` is one direct public source URL.

The Tool extracts readable text and atomically passes that exact output to
`source.ingest` before returning it. Success includes the readable material,
final URL, content hash, and stable `source://<uuid>` citation. A genuinely new
capture therefore emits the same ordinary `source.added` event; a duplicate
fetch does not. When the fetch occurs inside the active source-triggered Learn
Task, the new raw Source joins that activation instead of recursively queueing
another copy of the same research commitment.
