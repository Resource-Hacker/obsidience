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

The bounded Top 10 rotation uses this same Review archival owner inside one
complete edition change, under its explicit owner policy. It is not general
permission for Auto-curate to archive arbitrary Knowledge or delete Source.
