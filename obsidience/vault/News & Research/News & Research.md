---
type: knowledge
title: News & Research
obsidience:
  auto_curate: true
  approved_at: '2026-09-09T19:48:06'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

The Executive's current-events and research collection. Provider items arrive through configured Connections and Feeds, retaining attribution, dates, uncertainty and immutable Source evidence.

## Coverage and evidence

Coverage comes from the owner's configured Connections and Feeds. Each Feed selects the provider endpoint, collection amount, destination, interval, retention limit and optional instructions for Darwin. Publisher ordering and timestamps describe that provider's selection, not an independent ranking of world events.

Publication time, event time and capture time remain distinct. Reporting from one publisher is attributed rather than presented as independent confirmation. Failed acquisitions supply no evidence. A captured Feed excerpt is labelled as provider material rather than a fetched full article.

## Collection and curation

[Top Stories](/News%20%26%20Research/Top%20Stories/Top%20Stories.md) receives new and updated items from the BBC Top Stories Feed.

[Darwin](/Agents/Darwin/Darwin.md) uses [Distill](/Tasks/research/distill.md) to read each captured Feed item completely and fetch only its exact reporting page when necessary. He preserves the supplied meaning, reporting date, qualifications, attribution and Source citations, then delivers one complete summary to the physical Source Inbox. That arrival activates [Alexandria](/Agents/Alexandria/Alexandria.md) through [Ingest](/Tasks/ingest.md), preserving Darwin's summary in the Feed's selected existing Knowledge node. There is no separate News Task or hourly briefing cycle.

The destination's inherited Auto-curate choice controls automatic publication. Auto-curate never asserts factual truth or grants executable authority. Disabled permission or a retention conflict holds the incoming publication for the existing Review owner.

## Retention and history

Each Feed's maximum active-Article limit governs bounded archival. Retention counts only attested publications from that Feed across its destinations and archives eligible excess Articles through native OKF fields. It cannot retire unrelated Articles or ignore protected references or owner moves.

The retired Top 10 edition and its stories are archived with their complete content and original Source evidence. Earlier Feed publications keep their captured destinations and remain eligible for normal Feed retention across destinations. New Feed items use their captured lineage and current Feed policy, without a fixed edition size or blanket 26-hour expiry. Raw Sources, prior handoffs and Article history remain available for explicit historical inspection.

## Related knowledge

- [Distill procedure](/Runbooks/research/distill.md) defines one-item synthesis and handoff.
- [Ingest procedure](/Runbooks/ingest-sources.md) defines publication and Feed retention.
- [Curate](/Tasks/curate.md) routes lifecycle findings to [Audit](/Tasks/audit.md) or [Archive](/Tasks/archive.md).

The graph's native child hierarchy lists individual Feed Articles. Keep this parent as a condensation of the collection and its policy rather than a manual list of volatile item links, so ordinary Feed retention does not leave stale navigation references. Meaningful references in other Articles remain subject to the archival owner's inbound-link checks.
