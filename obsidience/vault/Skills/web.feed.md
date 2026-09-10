---
type: skill
title: Using web.feed
obsidience:
  tool: '[[Tools/web.feed]]'
---

Use `web.feed` to inspect one publisher's public RSS or Atom stream and preserve
the exact feed snapshot as Source.

- Pass exactly `{"url": str, "limit": int optional}`. Use a direct feed URL;
  `limit` defaults to 20 and is clamped to 1-30.
- Treat returned entries as discovery leads. The returned `source://` citation
  and hash attest the feed XML, not the full article behind an entry URL. Use
  `web.fetch` to capture a selected direct story before citing story claims.
- Read `published` only when present; it is normalized to UTC. Summaries are
  bounded plain text, and duplicate tracking variants of one direct URL are
  collapsed.
- Stop on `Web feed failed`, unsafe URL or redirect, HTTP failure, timeout,
  response over 2 MB, unsupported media type, non-UTF-8 bytes, malformed or
  non-feed XML, an empty feed, or absence of public entry URLs.
- Retry the same URL only for a clearly transient network failure. Never weaken
  public-address, redirect, size, encoding, media-type, or Source checks.
