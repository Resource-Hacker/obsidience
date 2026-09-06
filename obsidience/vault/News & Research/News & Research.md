---
type: knowledge
title: News & Research
obsidience:
  curation_task: '[[Tasks/ingest]]'
  research_task: '[[Tasks/research/news]]'
  auto_curate: true
  approved_at: '2026-09-05T06:54:59'
  provenance: proposed by Alexandria (task Tasks/improve)
---

The Executive's current-events collection. News is time-sensitive reporting,
not permanent truth. Each edition preserves its research capture time,
attribution, uncertainty, and immutable Source evidence.

## Contents

- [Coverage](/News%20%26%20Research/Coverage.md) states the publisher discovery scope, recency window, and evidence rules.
- [Top 10](/News%20%26%20Research/Top%2010/Top%2010.md) condenses the current edition and links its ten individual summarized story Articles.

[Darwin](/Agents/Darwin/Darwin.md) selects ten distinct world stories, reads
their direct sources, and delivers one complete briefing to the physical
Source Inbox through [News](/Tasks/research/news.md).
[Alexandria](/Agents/Alexandria/Alexandria.md) checks that exact handoff through
[Ingest](/Tasks/ingest.md). The existing proposal and Review authority publishes
one complete edition: the Top 10 parent and ten separate story Articles.
The hourly research schedule remains subject to ordinary autonomous-work availability.

The owner's Auto-curate permission authorizes source-backed Knowledge publication
inside this branch. For a complete Top 10 replacement, it also authorizes retaining
outgoing edition-owned story Articles below the existing archive, with native
OKF `status: deprecated`, an archive timestamp, and a reason. Only exact prior-edition
stories without remaining accepted inbound references qualify. No Source or
Article history is deleted. A failed or older edition leaves the complete current
edition intact. An explicit disabled selection on any affected Article retains
one grouped Review for the entire edition.

This permission cannot change Agent or executable authority, grant itself
permission, replace this policy, resolve unrelated conflicts, or publish outside
this branch. General archival still follows [Archive](/Tasks/archive.md).

Top 10 uses root OKF `resource`, `sources`, `description`, `generated`, and
`stale_after` fields. Its freshness boundary is 26 hours after the immutable
research handoff capture, not 26 hours after a delayed publication. Once that
instant passes, the retained edition is stale and must be revalidated before
being used as current context. Freshness and Auto-curate do not assert factual verification.

Raw feeds, fetched story material, and prior handoffs remain in Source.
The graph derives the Top 10 node and its children from this physical Article
hierarchy; dotted rings reflect the one inherited Auto-curate policy.

## Related knowledge

- [News procedure](/Runbooks/research/news.md) defines selection and evidence.
- [Ingest procedure](/Runbooks/ingest-sources.md) defines complete publication.
- [Curate](/Tasks/curate.md) routes explicit lifecycle leads to [Audit](/Tasks/audit.md) or [Archive](/Tasks/archive.md).
