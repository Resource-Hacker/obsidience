---
type: runbook
title: Link procedure
obsidience:
  for_agent: '[[Agents/Alexandria/Alexandria]]'
  owner_maintained: true
  skills:
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.validate]]'
  - '[[Skills/vault.propose]]'
  - '[[Skills/observations.temporary.append]]'
  task: '[[Tasks/link]]'
---

1. Read both exact `candidate_refs` Articles and their current accepted
   relationships. The maintenance signal is only a lead, not an access grant.
   If either endpoint is outside this Agent's checked-out graph or cannot be
   read, finish `failed` with that blocker. Do not search other Agents' private
   Observations, infer a missing body, or add a link to satisfy completion.
2. Confirm neither Article is an ancestor or descendant of the other at any
   depth. Native folder hierarchy and Agent Knowledge checkout already supply
   those connections; another written link is redundant. If such a pair reaches
   inspection, report the evidenced no-change result without a proposal.
   Otherwise confirm the Articles are distinct, not already directly linked, and share a
   specific relationship that improves retrieval or explains a real dependency,
   constraint, implementation, effect, or evidence path. Shared words, folder
   placement, and a generic sense of relevance are insufficient.
3. Choose the smallest directional update. Add one contextual wikilink to the
   Article where the relationship is most useful, with one concise sentence
   explaining the exact connection. Add a reciprocal link only when each
   Article independently benefits from it.
4. Preserve every existing fact, qualifier, Source reference, and useful link.
   Do not invent a relationship label or claim unsupported by either Article.
5. Call `vault.validate` once to confirm the accepted baseline is sound, then
   stage the complete replacement body for each affected Article through
   `vault.propose`. The harness classifies these as Link review objects from
   this accepted Task and displays the exact relationship delta; never attempt
   to set or describe a review class in Tool arguments.
   Use exact accepted Article refs and no metadata changes. Each proposed
   connection stays a suggestion; its body line and endpoint revision are
   captured by the harness, not self-certified by the model. An edited endpoint
   produces a visible review warning, including after a reciprocal Link is
   approved. If Review blocks a stale proposal, reject it and reread both Articles
   before a fresh proposal can be staged.
6. While this execution's proposal is pending, call `task.complete` with
   `{"status":"review","summary":"the staged Article and relationship"}`.
   If the owner has already approved it, finish `completed` with
   `outcome:"changed"`; do not stage another proposal. If rejected, finish
   `failed` and report the decision. When both endpoints were read and no useful
   change is warranted, use `{"status":"completed","outcome":"no_change",
   "evidence":["the exact Articles and relationship inspected"],"summary":"why no link was warranted"}`.
   `outcome` and `evidence` are separate argument fields, not prose inside
   `summary`. An incomplete inspection is a failure, not an evidenced no-change.


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Do not record hidden reasoning or create a note merely to narrate routine work.
