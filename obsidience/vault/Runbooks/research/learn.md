---
title: Learn procedure
kind: runbook
owner_maintained: true
for_agent: '[[Agents/Darwin/Darwin]]'
task: '[[Tasks/research/learn]]'
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/searching-the-web]]'
- '[[Skills/fetching-web-sources]]'
- '[[Skills/reading-source-evidence]]'
- '[[Skills/handing-off-research]]'
---

1. If activated by `source.added`, require its exact Source identity and read
   that Source first. Otherwise, use the bound objective to select one narrow,
   consequential knowledge gap. Do not manufacture work when the graph is
   sufficient.
2. Search accepted Knowledge, frame one bounded question, and acquire only the
   small direct-source set needed to answer it. Supporting Sources captured
   during this activation reuse its activation key instead of recursively
   creating another Learn commitment.
3. Read the captured bytes and compare authority, independence, date,
   relevance, consistency, uncertainty, and limitations.
4. Produce one reusable finding rather than a transcript or source dump. Use
   `source.handoff` once with every exact `source://` citation. The Tool writes
   the physical `obsidience/evidence/inbox/` handoff and emits `source.inbox` for Ingest.
5. Complete when the handoff is attested, or complete honestly with no change
   when no useful safe finding is justified. Do not stage an intermediate
   Review or activate Ingest manually.
