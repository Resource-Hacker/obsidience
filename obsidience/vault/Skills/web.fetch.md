---
type: skill
title: Using web.fetch
obsidience:
  tool: '[[Tools/web.fetch]]'
---

Use `web.fetch` to acquire and immutably capture direct public web evidence.
Pass exactly `{"url": "https://publisher.example/story"}` for one page or
`{"urls": ["https://publisher.example/story-one", "https://other.example/story-two"]}`
for one to ten independent pages. Select a batch when all URLs are already known;
each item has its own Source citation and failure result. Do not include duplicate
URLs or rely on fragment differences to make them distinct.

Article extraction removes navigation and related-page clutter while retaining
article content and available attribution/date. Generic documents retain headings,
lists, tables, code and safe absolute HTTP(S) links. Linked pages are discovery
references only; fetch a selected URL explicitly when its evidence is needed.

A single success reports its final URL, capture/reuse state, `source://` citation,
SHA-256 and actual first range of up to 6,000 characters. Batch JSON contains
ordered `results` with requested `url`, boolean `ok`, and the same per-item `result`
text; total output is capped at 60,000 characters so returned ranges can be smaller.
Use each visible fact with that item's citation. Call `source.read` with its exact
citation and next offset only when a needed detail lies beyond the returned range.
Never claim that unread tails or failed items were inspected.

URLs are at most 2,000 encoded characters, every resolved address and redirect
must remain public, HTTPS cannot downgrade, each response is at most 2 MB and
stored extraction at most 240,000 characters. Stop on failure; do not infer missing
facts. Retry only a failed item after a clearly transient condition, rather than
repeating successful batch items or weakening these boundaries.
