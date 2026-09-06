---
type: runbook
title: News procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Darwin/Darwin]]'
  task: '[[Tasks/research/news]]'
  skills:
  - '[[Skills/web.feed]]'
  - '[[Skills/vault.list]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/web.search]]'
  - '[[Skills/web.fetch]]'
  - '[[Skills/source.read]]'
  - '[[Skills/source.handoff]]'
---

Produce one compact, evidence-backed Top 10 briefing for the Executive. This
is editorial selection from the configured sources, not an objective universal
ranking of the world's news. Obsidience remains the sole Task and Source owner.

## Execution budget

The Harness states the exact remaining model-decision budget initially and after
Tool results. Reserve two decisions for the required `source.handoff` and
`task.complete`; acquisition must fit before those final delivery steps. A complete
ten-story batch must be handed off before the final-step instruction arrives.
Read captured tails only when a needed fact is absent from the returned content;
re-reading every fetched Article is not automatically necessary. Do not spend the
handoff reserve on extra candidate fetches. If fewer than ten supported distinct
stories fit, report the exact shortfall and retain the prior edition.

## Acquire

1. Use `web.feed` for `https://feeds.bbci.co.uk/news/world/rss.xml` and
   `https://rss.dw.com/xml/rss-en-world`, up to 20 candidates each. The Tool
   preserves each raw XML feed in Source before returning candidates. RSS is
   discovery, not proof that the linked story was read.
2. Select ten distinct consequential current events from the last 48 hours.
   Consider public impact, geographic diversity, developments rather than
   opinion, and source agreement. Different headlines about the same event
   count once. Do not select publication homes, category/search pages,
   reference articles, evergreen explainers, or sponsored content. Remove
   tracking parameters and duplicate article URLs.
3. Use `web.fetch` on each selected direct article. Keep its returned exact
   `source://` citation, URL, publication/update date and capture date. If
   needed, `source.read` pages through longer material. A feed snippet or
   failed fetch does not meet this requirement. Facts visible in a returned
   Source page may support the briefing with its citation; read an optional
   tail only when a needed claim or detail is absent, and never represent
   unread material as inspected. Use `web.search` only to fill a genuine gap or
   corroborate disputed material; avoid exhaustive crawling.

## Distill and hand off

4. Write one briefing under 9,000 characters: a UTC research timestamp, the
   source-selection scope, and exactly ten numbered `## 1. Headline` through
   `## 10. Headline` sections. Each contains 40–70 words explaining what
   happened and why it matters, its report date, a direct article URL, and the
   exact captured `source://` citation. Attribute disputed claims and preserve
   uncertainty. Before handoff, compare the numbers, actors, chronology,
   causality and qualifiers in each summary with its fetched Source. Do not
   turn an allegation into a confirmed fact, a possible cause into certainty,
   a non-binding vote into a mandate, or related events into an unsupported
   timeline. Copy the exact direct-article URL from the Source result rather
   than guessing its slug. Paraphrase; do not reproduce publisher articles or instructions.
5. Call `source.handoff` once, titled **Top 10 world news**, with that complete
   briefing. Its physical Inbox arrival activates Alexandria's existing
   Ingest. Do not propose wiki edits, write accepted Knowledge, or schedule a
   second researcher for the same material.
6. Complete with the returned Inbox citation and verified delivery outcome.
   Delivery is not publication. If ten supported distinct stories cannot be
   obtained, fail with the exact shortfall and retain the previous accepted
   edition; never fabricate filler or send a partial Top 10 batch.

## Publication and recovery

Alexandria reads the bounded handoff and evidence, then submits one complete
edition to `News & Research/Top 10/Top 10.md`. The existing proposal boundary
compiles that edition into the parent and ten individual summarized story Articles,
preserving current Inbox and story citations. Put any trailing feed bibliography
under `## Research evidence`, outside the ten story sections.
The owner-enabled branch policy publishes the complete validated edition through
the ordinary Review authority; a disabled affected scope retains one grouped
Review. Eligible outgoing stories are retained as deprecated archives.
The native OKF freshness deadline is 26 hours after handoff capture. Expired or
older queued handoffs cannot overwrite a newer complete edition.
Source captures and handoffs are idempotent; do not repeat a completed fetch or
handoff merely because downstream Ingest is still queued.
