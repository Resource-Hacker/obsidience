---
title: Fetch web source
kind: skill
tool: '[[Tools/web.fetch]]'
---
Use `web.fetch` only on a direct source URL selected for the current research
question. Prefer the canonical article, documentation, release, paper, or data
page over a search page, category page, or publication home.

A successful fetch is already captured in the immutable Source authority. Keep
its final URL, capture date, and returned `source://` citation together in the
finding. A new capture already emits `source.added` for Darwin's Learn Task;
inside an active source-triggered Learn occurrence it coalesces into that same
activation. Do not call `source.ingest` again for the fetched content. Use
`source.handoff` once for the final synthesis and never issue Ingest manually.
Treat a failed, blocked, partial, or unsupported fetch as a recorded limitation
rather than permission to summarize material that was not acquired.
