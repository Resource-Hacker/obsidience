---
type: tool
title: vault.list
description: List readable Articles in the executing Agent's graph.
obsidience:
  binding: capability:vault.list
  source: obsidience/harness/capabilities/vault/list.py
---

## Runtime

List readable Articles in the executing Agent's graph. Optional folder narrows the physical prefix; offset pages through sixty rows. Counts and titles include only accessible Articles. This is discovery, not a capability grant.

## Reference

Deterministically list accepted Articles below one Knowledge or Library folder.
Arguments: `{"folder": "News & Research", "offset": 0}`. An empty folder lists
all accepted roots. Each page contains up to 60 rows with total and next offset.
Use this to enumerate ("check every X") — search is for finding by meaning,
not for enumeration. Follow the next offset until the explicit end marker.

Raw Source, including the physical Source Inbox, is a separate filesystem and
cannot be enumerated through this Tool.
