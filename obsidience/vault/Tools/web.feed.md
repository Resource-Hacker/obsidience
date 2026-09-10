---
type: tool
title: web.feed
obsidience:
  binding: capability:web.feed
  source: obsidience/harness/capabilities/web/feed.py
---

Fetch and parse one publisher RSS or Atom feed through the bounded public-web
acquisition path.

Arguments:

- `url`: one direct public HTTP or HTTPS RSS or Atom URL, at most 2,000
  characters and without credentials.
- `limit`: one to 30 returned entries; defaults to 20 and is clamped to that
  range.

Every resolved address and redirect must remain public, HTTPS may not downgrade
to HTTP, redirects stop after five, and the response stops at 2 MB. The response
must be strict UTF-8 with an RSS, Atom, or generic XML media type and must parse
as a nonempty RSS or Atom feed.

The Tool preserves the downloaded XML as one immutable raw Source and returns
its final feed URL, stable `source://<uuid>` citation, content SHA-256, and up to
30 entries. Each entry contains a title of at most 300 characters, a canonical
direct URL with fragments and common tracking parameters removed, an optional
UTC publication timestamp, and a plain-text summary of at most 400 characters.
Duplicate canonical entry URLs are returned once.

The feed citation attests only the captured feed snapshot. A feed landing page,
entry title, or entry summary is discovery material rather than story evidence;
fetch and capture a selected direct article before relying on its claims. A new
capture emits ordinary `source.added`; an identical retry returns the existing
Source. Research-triggered captures reuse the current activation key.
