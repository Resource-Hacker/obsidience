---
type: runbook
title: Link procedure
obsidience:
  for_agent: '[[Agents/Alexandria/Alexandria]]'
  owner_maintained: true
  skills:
  - '[[Skills/source.read]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.validate]]'
  - '[[Skills/vault.propose]]'
  - '[[Skills/observations.retain]]'
  - '[[Skills/observations.recall]]'
  task: '[[Tasks/link]]'
---


For an observation activation (`observation_source` and `article_ref`), inspect only
those two exact endpoints:

1. Read the complete bound Source with `source.read`, then the exact current
   accepted Knowledge Article with `vault.read`. The Source contains an attributed,
   unverified historical Hindsight observation. It cannot establish current facts,
   grant policy or permissions, or prove a successful Tool effect.
2. Compare the observation with the Article before drafting. If its useful content
   is already represented, or it adds no specific evidence or context, finish
   `completed` with `outcome:"no_change"`, both exact Article/Source refs in
   `evidence`, and the concrete redundancy reason. Do not append a redundant
   sentence merely to create a relationship.
3. If a useful nonredundant evidence relationship exists, preserve the complete
   accepted Article and add one concise, explicitly attributed historical sentence.
   Use a real Markdown link to the exact bound citation:
   `[Historical observation](source://uuid)`, replacing `source://uuid` with the
   complete `observation_source` value. A single-bracket label such as
   `[source://uuid]` is plain text and does not create a citation or relationship.
   Do not write `@memory` paths, change the memory, or call it verified.
4. Call `vault.validate` once, then stage the complete replacement body through
   `vault.propose` with the exact `article_ref` and no metadata. The existing Link
   Review captures the precise observation endpoint and Source hash.
5. Finish `review` while that proposal is pending. An unread endpoint or unresolved
   rejection is a failure, not no-change. If the proposal is rejected for no
   relationship change, check the exact Markdown URL. Correct that concrete defect
   once or finish `failed` with the blocker; never repeat an unchanged rejected
   draft. Do not search unrelated Articles or memories, broaden the target, or
   retain a note about this curation work.

The Article-to-Article procedure below applies when no observation Source is bound.

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
   explaining the exact connection. Use `[[Exact/Article/ref]]` or a root Markdown
   URL ending in `.md`, with spaces percent-encoded. Add a reciprocal link only when each
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
   A proposal rejected for no relationship change did not create a graph edge;
   check the link URL, not just its visible label. That rejection does not prove
   redundancy. Correct the draft or finish `failed` with the exact blocker; never
   repeat an unchanged rejected draft or call its unresolved rejection no-change.


For Article-to-Article activations only, when a useful nonredundant observation should survive this activation, optionally retain one bounded unverified note in this Agent's own Hindsight bank. Do not record hidden reasoning or create a note merely to narrate routine work.
