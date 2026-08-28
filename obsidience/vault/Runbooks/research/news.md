---
title: News procedure
kind: runbook
owner_maintained: true
for_agent: '[[Agents/Darwin/Darwin]]'
task: '[[Tasks/research/news]]'
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/searching-the-web]]'
- '[[Skills/fetching-web-sources]]'
- '[[Skills/reading-source-evidence]]'
- '[[Skills/handing-off-research]]'
---

1. Define one current topic and a narrow recency window.
2. Discover concrete current-event articles. Reject category, search,
   publication-home, encyclopedia, reference, and generic explainer pages.
3. Canonicalize source identity conceptually and keep unique direct URLs; two
   differently titled summaries of one URL are one story.
4. Fetch the selected pages, read their captured Source bytes, and distinguish
   event time from publication time.
5. Produce one bounded finding with dates, direct URLs, `source://` citations,
   uncertainty, and material disagreements. Drop it once into the physical
   Source Inbox through `source.handoff`.
6. Complete after the handoff is attested; a batch without enough valid sources
   fails closed without creating an intermediate Review.
