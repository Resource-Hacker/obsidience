---
title: Research question procedure
kind: runbook
owner_maintained: true
for_agent: '[[Agents/Darwin/Darwin]]'
task: '[[Tasks/research/question]]'
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/searching-the-web]]'
- '[[Skills/fetching-web-sources]]'
- '[[Skills/reading-source-evidence]]'
- '[[Skills/handing-off-research]]'
---

1. Frame one bounded question, success criterion, scope, and freshness need.
2. Search the accepted graph first. If current external evidence is needed,
   discover a small source set and fetch only direct pages.
3. Read the captured Source bytes and compare authority, independence, date,
   relevance, consistency, and limitations.
4. Synthesize one self-contained finding with direct URLs, access dates,
   uncertainty, and every returned `source://` citation.
5. Use `source.handoff` once to drop the complete cited synthesis into the
   physical Source Inbox. Its `source.inbox` event activates Alexandria's
   centralized Ingest Task.
6. Complete after the handoff is attested; report failed or partial acquisition
   honestly without staging an intermediate Review.
