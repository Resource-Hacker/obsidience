---
type: skill
title: Using vault.list
obsidience:
  tool: '[[Tools/vault.list]]'
---

Use `vault.list` to enumerate accepted Articles beneath one safe vault folder.

- Pass `{"folder": "News & Research", "offset": 0}` or another accepted
  Knowledge or Library folder. An empty folder enumerates all accepted roots.
  No empty, hidden, private, `.`, or `..` segment is allowed.
- A nonempty result contains at most 60 exact Article refs and titles in
  deterministic order. `<folder>/ is empty.` is a successful empty result.
- Follow `Next offset` until `End of folder`. Offsets count Articles, not
  characters. Private staging, archives, and paths outside the Vault are excluded.
- Stop on `Invalid folder` or an unavailable read. Do not retry with filesystem
  paths, traversal syntax, or an inferred alternate root.
