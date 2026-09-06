---
type: skill
title: Using vault.propose
obsidience:
  approved_at: '2026-08-21T04:02:08'
  provenance: proposed by Codex (task research generation kit)
  tool: '[[Tools/vault.propose]]'
---

Use `vault.propose` to submit one complete Article change through the proposal
validator. The destination's owner policy determines publication or Review.

- Pass exactly `{"action": "create|update|archive", "target": str,
  "title": str, "body": str, "reason": str, "metadata": object optional}`.
  `target` is a safe vault-relative Markdown path outside system folders.
  `create` and `update` require a complete nonempty body of at most 131,072
  characters; `archive` accepts only an existing ordinary Knowledge Article.
- `metadata.type` declares `knowledge`, `task`, `runbook`, `tool`, `skill`, or
  `agent` when explicitly changing or creating that type. Application fields
  belong in `metadata.obsidience`: `acceptance`, `assignee`, `binding`, `model`,
  `owner_maintained`, `reasoning_effort`, `runbook`, `skills`, singular `source`,
  `subrunbooks`, `subskills`, `subtasks`, `subtools`, `taxonomy_path`, singular
  `tool`, and `triggers`. The Tool also accepts its existing flat argument
  shape, but accepted files have only the canonical namespaced format. Omitted
  accepted metadata is preserved on update. Native document fields
  `description`, `resource`, `sources`, `generated`, `stale_after`, and `status`
  belong at the metadata root. Document `status` is `draft`, `stable`, or
  `deprecated`; it is never Task execution state. Never submit Auto-curate,
  trust, verification, runtime state, or internal review-control fields.
- Write body links using standard Markdown with exact Article paths, such as
  `[Read](/Tools/vault.read.md)`. Legacy wikilink input is normalized on staging.
- Generated Runbooks require an explicit minimal `metadata.skills` selection,
  or native `metadata.obsidience.skills`, containing exact accepted Skill refs
  from the supplied shared catalog. Include every Skill paired with a called
  Tool; do not copy the entire catalog or rely on body mentions. The controller
  binds exact `task` and `for_agent` applicability. Approval supplies that
  dependency set without writing Agent Tool, Skill, or Runbook grants; the
  assigned Task waits while its procedure is unapproved.
- `Proposal staged for owner review` means pending, not accepted. `Article
  published` means the existing approval path accepted this scoped Knowledge
  change under owner Auto-curate. Report only the result actually returned.
  An exact repeat may return the existing staged proposal. Never change
  Auto-curate, move a proposal to another scope, or call a direct file writer
  to avoid review. Auto-curate does not establish factual truth.
- For the exact News Ingest handoff, submit one complete ten-section briefing
  to `News & Research/Top 10/Top 10.md`, with only `metadata.type: knowledge`.
  The controller compiles its parent, ten story Articles, documentary fields,
  and eligible outgoing archives. It approves or stages the whole edition;
  do not publish individual stories independently or invent generated metadata.
  A blocked automatic decision reports its reason in the Tool result.
- Stop on `Proposal rejected`, an unsafe target, invalid action or metadata,
  empty/oversized body, stale base, invalid Capability contract, or any existing
  different unresolved proposal for the target. Do not overwrite or parallel a
  pending proposal.
- For Link, use `update` without `metadata`, exact accepted Article refs, and a
  sentence explaining each connection in the body. The harness records its
  location and endpoint revision; do not supply confidence or evidence metadata.
  If the source Article or staged body changes, reject the stale proposal and
  reread both Articles before drafting again. An endpoint-revision warning asks
  the reviewer to inspect its current text; it does not rewrite the proposal.
  A recorded Markdown link proves only
  that the proposed text contains it, not that the relationship is true.
