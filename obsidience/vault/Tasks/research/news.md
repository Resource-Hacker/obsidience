---
type: task
title: News
obsidience:
  acceptance:
  - Ten distinct current world stories, each backed by a fetched direct article Source.
  - One concise dated briefing delivered to the physical Source Inbox for Alexandria.
  assignee: '[[Agents/Darwin/Darwin]]'
  auto_done: true
  enabled: true
  model: obsidience-qwen38-27b-q8
  reasoning_effort: high
  runbook: '[[Runbooks/research/news]]'
  schedule: 0 * * * *
  taxonomy_path: research/news
  triggers:
  - task.create
---

Provide the Executive's [News & Research](/News%20%26%20Research/News%20%26%20Research.md) branch with
a researched Top 10 world-news briefing. Default scope is English-language
world news over the previous 48 hours, refreshed hourly. An explicit request
may narrow the topic, but must not invent stories to fill a quota.

Darwin preserves the raw publisher feeds and fetched story material in Source,
then hands one bounded cited briefing to Alexandria. Completion means research
was delivered; it does not claim that Ingest has published the edition yet.
Ingest maintains [Top 10](/News%20%26%20Research/Top%2010/Top%2010.md) as a parent
condensation with ten individual summarized story Articles beneath it.
