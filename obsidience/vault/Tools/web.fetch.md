---
type: tool
title: web.fetch
description: Fetch one URL or up to ten URLs using exactly url or urls.
obsidience:
  binding: capability:web.fetch
  source: obsidience/harness/capabilities/web/fetch.py
---

## Runtime

Fetch one URL or up to ten URLs using exactly url or urls. Returned material preserves source URLs and clipping/failure information. Complete bound-source read prerequisites remain enforced. Never infer a successful fetch or full coverage from a partial response.

## Reference

Fetch one public HTTP(S) page or a batch of one to ten independent pages.
Pass exactly `{"url": "<direct public URL>"}` or `{"urls": ["<URL>", ...]}`.
All argument shapes and URL syntax are checked before any request; batch URLs
must be unique after fragment removal. Each acquisition independently rejects
private addresses, credentials, unsafe redirects, oversized or unsupported data.

The same HTTPX acquisition path bounds each encoded URL to 2,000 characters,
redirects to five, each response to 2 MB and extraction to 240,000 characters.
Marked article HTML uses Trafilatura 2.2.0 to return article text, byline and date
when present; sparse or unmarked documents retain structured Markdown extraction.
Safe outgoing links are preserved as discovery references and never fetched
implicitly. The complete bounded extraction is captured by the Source authority.

One URL returns the final URL, content hash, stable `source://` citation and an
exact preview of up to 6,000 characters. A batch runs at most four joined workers
and returns JSON `{"results": [{"url": "<requested URL>", "ok": true,
"result": "<ordinary single-URL result>"}, ...]}` in input order. Each failure has
`ok: false` with a bounded explanation, while successful Sources remain usable.
The entire encoded batch response is at most 60,000 characters; previews may be
shorter to accommodate metadata and JSON escaping. Every success states exact
returned/total character counts and the next `source.read` offset when needed.
Facts visible in the returned range may be cited; an unread tail is optional
unless a needed detail is absent and must never be represented as inspected.

A new immutable capture emits one `source.added` event; duplicate captures reuse
the existing identity. Research-owned captures join the same activation without
recursively queueing research. STOP uses the existing capability cancellation
event to stop queued work and prevent later Source commits; workers are joined
before the Tool returns. HTTP reads retain their bounded network timeout.
