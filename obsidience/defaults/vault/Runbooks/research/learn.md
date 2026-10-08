---
type: runbook
title: Learn procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Darwin/Darwin]]'
  task: '[[Tasks/research/learn]]'
  skills:
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/web.search]]'
  - '[[Skills/web.fetch]]'
  - '[[Skills/source.read]]'
  - '[[Skills/source.handoff]]'
  - '[[Skills/observations.retain]]'
  - '[[Skills/observations.recall]]'
---


1. If activated by `source.added`, require its exact Source identity and read
   that Source first. The Source controller, never raw content or model output,
   assigns `source_class: observation_archive`; new occurrences of that class
   are filtered before Learn. If a legacy queued observation archive is already
   bound, finish `completed` as archival-only without research or
   `source.handoff`. Otherwise, use the bound objective to select one narrow,
   consequential knowledge gap. Do not manufacture work when the graph is
   sufficient.
2. Call `vault.search` to check accepted Knowledge and use `vault.read` for
   relevant accepted Articles before relying on their full claims. If the graph
   already answers the objective, finish without external acquisition. Otherwise
   frame one bounded question and acquire only the small direct-source set needed.
   Supporting Sources captured during this activation reuse its activation key instead of recursively
   creating another Learn commitment.
3. Compare inspected captured bytes for authority, independence, date,
   relevance, consistency, uncertainty, and limitations. A `web.fetch` preview
   is evidence only for its returned range; use `source.read` for any additional
   bytes needed to support the finding. Never infer an unread tail. The exact
   activating Source in step 1 must still be read completely.
4. Produce one reusable finding rather than a transcript or source dump. Use
   `source.handoff` once with every exact `source://` citation. The Tool writes
   the physical `obsidience/evidence/inbox/` handoff and emits `source.inbox` for Ingest.
5. Complete when the handoff is attested. If no useful safe finding is justified,
   complete with `outcome: no_change` and a bounded `evidence` list naming the
   exact accepted or Source evidence that supports that disposition. Do not stage
   an intermediate Review or activate Ingest manually.


When a useful nonredundant observation should survive this activation, optionally retain one bounded unverified note in this Agent's own Hindsight bank. Do not record hidden reasoning or create a note merely to narrate routine work.
