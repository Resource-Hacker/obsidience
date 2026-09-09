---
type: knowledge
title: News & Research
obsidience:
  curation_task: '[[Tasks/ingest]]'
  research_task: '[[Tasks/research/news]]'
  auto_curate: true
  approved_at: '2026-09-09T13:15:46'
  provenance: proposed by Alexandria (task Tasks/improve)
---

The Executive's current-events collection. News is time-sensitive reporting,
not permanent truth. Each edition preserves its research capture time,
attribution, uncertainty, and immutable Source evidence.

## Contents

- [Coverage](/News%20%26%20Research/Coverage.md) states the publisher discovery scope, recency window, and evidence rules.
- [Top 10](/News%20%26%20Research/Top%2010/Top%2010.md) condenses the current edition and links its ten individual summarized story Articles.
- [Police launch criminal investigation into Reform UK donations](/News%20%26%20Research/item--daf978ee85d4107bfdf85298.md) is a retained source-backed story Article at the branch root.
- [Miliband rejects chief rabbi's claim British Jews in greater danger after sanctions move](/News%20%26%20Research/item--03a0391514f979b430d54ff5.md)
- [National security can't come at expense of social security, Burnham says](/News%20%26%20Research/item--503c3f9f9e729b92fee324c0.md)
- [Hundreds mourn police officer killed in wrong-way A66 crash](/News%20%26%20Research/item--5c30a0c17c63824c9440c3a3.md)
- [Uganda pulling out of Prince Harry's Invictus Games, says military chief](/News%20%26%20Research/item--5df9062f5294ca787a2bc09a.md)
- [RNLI volunteer targeted online and branded 'traitor' after Portsmouth protests](/News%20%26%20Research/item--7719d40ec3db90a320bdc478.md)
- [Europe's royalty pay last respects to King Harald V in Norway](/News%20%26%20Research/item--a848cfb88ff64aed55527f5c.md)
- [Mother demands answers, weeks after black woman found hanging from Mississippi tree](/News%20%26%20Research/item--e0f4cdfd51f7553ef900fcab.md)

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
