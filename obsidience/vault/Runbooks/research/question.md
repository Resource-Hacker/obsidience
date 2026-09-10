---
type: runbook
title: Research question procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Darwin/Darwin]]'
  task: '[[Tasks/research/question]]'
  skills:
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/web.search]]'
  - '[[Skills/web.fetch]]'
  - '[[Skills/source.read]]'
  - '[[Skills/source.handoff]]'
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
6. Complete after the handoff is attested. If accepted evidence already answers
   the question and no handoff is justified, complete with `outcome: no_change`
   and cite the exact accepted evidence in the `evidence` list. Report failed or
   partial acquisition honestly without staging an intermediate Review.
