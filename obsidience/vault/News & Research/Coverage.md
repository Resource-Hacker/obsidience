---
type: knowledge
title: Coverage
---

The Executive's default news coverage is English-language world news. BBC
World and DW World RSS supply discovery leads; the resulting Top 10 is
Darwin's editorial selection, not a universal or exhaustive ranking.

The working recency window is 48 hours. Publication time, event time and
research time are distinct: an updated article can describe an older event.
Multiple headlines about the same development are one story. Reporting from
one publisher is attributed rather than presented as independent confirmation.

Every published briefing keeps direct article URLs and immutable Source
citations. Feed summaries alone do not establish a story's contents. A failed
refresh leaves the previous complete edition intact. Native OKF `stale_after`
is 26 hours after the immutable research handoff capture; once elapsed, the
retained edition is stale and excluded from current activation context until
revalidated. Delayed publication never resets that freshness clock. Raw feeds and earlier handoffs remain available in Source.

[News & Research](/News%20%26%20Research/News%20%26%20Research.md) is the maintained collection;
[News](/Tasks/research/news.md) owns acquisition and research, while
[Ingest](/Tasks/ingest.md) owns publication through Alexandria.
