---
type: runbook
title: Archive procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Alexandria/Alexandria]]'
  task: '[[Tasks/archive]]'
  skills:
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/source.read]]'
  - '[[Skills/vault.propose]]'
  - '[[Skills/observations.temporary.append]]'
---

1. Use the supplied exact maintenance candidate refs and signals. An ordinary
   Knowledge Article with native OKF `status: deprecated` is an explicit retirement
   lead; an exact `superseded_by` link is a replacement lead. Never select an
   Agent, Tool, Skill, Task, Runbook, or runtime Observation.
2. Read the candidate, its native lifecycle fields, accepted neighbors, and each
   exact Source needed to confirm the retirement or replacement. Do not invent a
   successor for an explicitly deprecated Article.
3. Distinguish freshness from truth: an elapsed timezone-aware `stale_after`
   means the Article is stale and needs revalidation. It does not prove a
   contradiction or authorize removal. Use [Audit](/Tasks/audit.md) for unresolved
   freshness; publication time or file age alone is insufficient.
4. Inspect the exact accepted inbound references returned by `vault.read`.
   Stage any necessary complete reference updates before archival; do not leave
   broken links or conceal an unresolved conflict. Duplicate consolidation belongs
   to [Merge](/Tasks/merge.md).
5. Stage `vault.propose` with `action: archive`, the exact target, and a concise
   evidence-grounded reason. Approval retains the complete Article below
   `_archived/`, records native `status: deprecated`, and adds namespaced
   `archived_at` and `archive_reason`. Body, Source references, unknown documentary
   metadata, and history remain intact. Remaining accepted inbound references
   block publication.
6. Finish with `review` for the staged proposal or `completed` with the exact
   no-change reason. After reading all supplied candidates, use
   `outcome: no_change` only when archival is affirmatively unwarranted, with
   the exact observed grounds in `evidence`. Missing evidence and unresolved
   inbound references are not clean completion.

Explicit Feed active-Article retention uses this same Review archival owner. Darwin's Feed handoff triggers Alexandria's Ingest
to retire the oldest excess Articles from that exact Feed while publishing its
incoming Article atomically. A Feed policy save can also reconcile the count,
including quiet feeds, in bounded groups. The Feed compiler attests membership,
current policy, exact bases, all affected Article permissions and surviving
inbound references. Full content, Sources and history remain below `_archived/`;
retention records retirement from the active collection without declaring an
old report false. This is not general permission to archive arbitrary Knowledge,
reclassify elapsed `stale_after`, or delete Source. No additional model Archive
execution is required for this deterministic policy application.


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Do not record hidden reasoning or create a note merely to narrate routine work.
