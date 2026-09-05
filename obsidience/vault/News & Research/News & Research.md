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

The Executive's current-events briefing and source-backed research context.
News is time-sensitive reporting, not permanent truth. Each briefing states
when it was researched, distinguishes reports from confirmed facts, and links
its evidence back to immutable Source material.

## Contents

- [Coverage](/News%20%26%20Research/Coverage.md) states the default English-language world-news coverage, BBC World and DW World discovery leads, 48-hour recency window, and story-attribution rules.
- [Top 10](/News%20%26%20Research/Top%2010.md) is the current source-backed briefing edition, replacing the prior edition while preserving history and raw evidence.

[Darwin](/Agents/Darwin/Darwin.md) selects ten distinct important world stories,
reads their direct sources, and sends one concise, cited briefing to the
physical Source Inbox. [Alexandria](/Agents/Alexandria/Alexandria.md) checks the
handoff and maintains the **Top 10** Article through [Ingest](/Tasks/ingest.md).
[News](/Tasks/research/news.md) refreshes hourly when autonomous work is permitted.

Auto-curate authorizes routine source-backed Knowledge creates and updates
inside this branch. Turning the checkbox off sends those changes to the Review
queue instead. It does not authorize deletions, permission changes, replacement
of this policy, or publication outside this branch. Research and Ingest keep
their ordinary Task-selected models and reasoning settings.

Raw feeds, fetched story text, and prior research handoffs remain in Source.
The latest briefing replaces the current Top 10 Article; its history and the
raw evidence preserve earlier editions without filling the graph with copies.
The graph's dotted rings identify this Auto-curated branch and its descendants.

## Related knowledge

- [Executive](/Agents/Executive/Executive.md) uses this branch when a request needs current events.
- [News procedure](/Runbooks/research/news.md) defines selection, evidence, and publication criteria.
- [Ingest procedure](/Runbooks/ingest-sources.md) keeps publication centralized with the Curator.
