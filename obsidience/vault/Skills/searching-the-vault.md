---
title: Search vault
kind: skill
tool: '[[Tools/vault.search]]'
---
How to use `vault.search` to find candidate context.

- Query with plain descriptive words, not unsupported path/kind/tag operators.
- Vary wording before concluding that material does not exist.
- Treat every result as a lead only; call `vault.read` on the exact ref before
  relying on its content.
