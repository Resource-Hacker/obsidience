---
binding: capability:vault.list
kind: tool
source: obsidience/harness/capabilities/vault/list.py
title: vault.list
---

Deterministically list every Article below one safe vault folder. Argument:
`{"folder": "Tasks|Runbooks|Skills|Tools|Agents[/subfolder]"}`.
Use this to enumerate ("check every X") — search is for finding by meaning,
not for enumeration.

Raw Source, including the physical Source Inbox, is a separate filesystem and
cannot be enumerated through this Tool.
