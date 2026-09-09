---
type: knowledge
title: News & Research
obsidience:
  auto_curate: true
  approved_at: '2026-09-09T14:48:37'
  provenance: proposed by Codex (owner-requested maintenance) (task codex:owner-maintenance)
---

The Executive's current-events and research collection. Provider items arrive through configured Connections and Feeds, retaining attribution, dates, uncertainty and immutable Source evidence.

## Collection

- [Coverage](/News%20%26%20Research/Coverage.md) states the publisher discovery scope, recency window, and evidence rules.
- [Top Stories](/News%20%26%20Research/Top%20Stories/Top%20Stories.md) is the destination for new and updated items from the BBC Top Stories Feed.

[Darwin](/Agents/Darwin/Darwin.md) distills each captured Feed item through [Distill](/Tasks/research/distill.md) and delivers its complete cited summary to the physical Source Inbox. That arrival activates [Alexandria](/Agents/Alexandria/Alexandria.md) through [Ingest](/Tasks/ingest.md), preserving Darwin's summary in the Feed's selected existing Knowledge node. There is no separate News Task or hourly briefing cycle.

Each Feed controls its collection interval, amount, destination, optional distillation instructions and maximum active Articles. The destination's inherited Auto-curate choice controls automatic publication. Feed retention counts only attested publications from that Feed across its destinations and retains eligible excess Articles through native OKF archival. It cannot retire unrelated articles or ignore protected references or owner moves. Disabled permission or a retention conflict holds the incoming publication for the existing Review owner.

The retired Top 10 edition and its stories are archived with their complete content and original Source evidence. Earlier Feed publications keep their captured destinations and remain eligible for normal Feed retention across destinations. New Feed publications do not inherit a fixed edition size or a blanket 26-hour expiry. Source and Article history are retained; Auto-curate never asserts factual truth or grants executable authority.

## Related knowledge

- [Distill procedure](/Runbooks/research/distill.md) defines one-item synthesis and handoff.
- [Ingest procedure](/Runbooks/ingest-sources.md) defines publication and Feed retention.
- [Curate](/Tasks/curate.md) routes lifecycle findings to [Audit](/Tasks/audit.md) or [Archive](/Tasks/archive.md).

The graph’s native child hierarchy lists individual Feed articles. Keep this parent as a condensation of the collection and its policy rather than a manual list of volatile item links, so ordinary Feed retention does not leave stale navigation references. Meaningful references in other Articles remain subject to the archival owner’s inbound-link checks.
