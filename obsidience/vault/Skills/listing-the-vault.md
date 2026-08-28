---
title: List vault articles
kind: skill
tool: '[[Tools/vault.list]]'
---
Use `vault.list` for deterministic graph enumeration.

- Pass one supported graph root or safe subfolder when completeness matters.
  Raw Source, including the physical `obsidience/evidence/inbox/`, is a separate filesystem
  and is not available through this Tool.
- Use the returned exact refs for later reads; do not treat a truncated list as
  a semantic search result.
- Prefer `vault.list` for “every item in this folder” and `vault.search` for
  finding material by meaning.
