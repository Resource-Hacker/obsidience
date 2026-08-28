---
binding: capability:vault.read
kind: tool
source: obsidience/harness/capabilities/vault/read.py
title: vault.read
---

Read one full Article. Argument: `{"ref": "Folder/name"}` using its exact ref.
Returns its title and body plus the deterministic accepted Articles that
currently reference it, truncated together at 8k characters. The backlink list
comes from exact graph resolution; semantic search is not a substitute for it.
