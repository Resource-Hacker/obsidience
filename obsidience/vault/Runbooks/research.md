---
title: Research procedure
kind: runbook
owner_maintained: true
for_agent: '[[Agents/Darwin/Darwin]]'
skills:
- '[[Skills/searching-the-web]]'
- '[[Skills/fetching-web-sources]]'
- '[[Skills/capturing-source-evidence]]'
- '[[Skills/reading-source-evidence]]'
- '[[Skills/handing-off-research]]'
subrunbooks:
- '[[Runbooks/research/question]]'
- '[[Runbooks/research/learn]]'
- '[[Runbooks/research/news]]'
- '[[Runbooks/research/model]]'
---
Procedures owned by Darwin. Question, Learn, News, and Model are the four
requested outcomes. Framing, discovery, collection, screening, assessment, extraction,
analysis, and verification are steps inside these procedures rather than Task
taxonomy. Generate is a peer family used after research establishes evidence.

For ordinary research, Darwin discovers a bounded candidate set with
`web.search`, fetches selected direct pages with `web.fetch`, and carries each
returned immutable `source://` citation. Every new raw Source emits
`source.added`, one of the possible triggers on the existing Learn Task; raw
Sources captured inside that active Learn occurrence coalesce into it instead
of recursively queuing the same commitment.

Darwin produces one bounded, self-contained finding per topic with direct
URLs, publication and access dates, factual summary, provenance, uncertainty,
failed-fetch notes, and every Source citation. He then calls `source.handoff`
once. That Tool writes an immutable file under `obsidience/evidence/inbox/` and emits
`source.inbox`. Alexandria's centralized Ingest Task consumes that event and
stages the final wiki change for owner Review. Darwin never writes the vault or
creates an intermediate Review object.
