---
type: skill
title: Using vault.search
description: Identify the missing fact before lookup.
obsidience:
  tool: '[[Tools/vault.search]]'
---

## Runtime

Identify the missing fact before lookup. Search only the current Agent graph and prefer already sufficient supplied Knowledge. Related results do not prove the identity of an object on screen. Stop repeated or low-value searches instead of rephrasing indefinitely.

## Reference

Use `vault.search` to find candidate context in the accepted graph.

- Supply `{"query":"focused descriptive text"}` or batch independent queries with `{"queries":["first focused query","second focused query"]}`. A batch contains 1-10 distinct queries; each is 1-300 characters. Do not supply both query forms or encode unsupported filters in query text.
- A single query returns up to ten exact refs with Article kind and snippet; a batch returns up to five candidates for each exact supplied query. Inspect each item's `ok` and `result`.
- `No results.` is a successful empty search. Do not infer nonexistence from one empty result. An unavailable search is an error, not evidence that no match exists.
- Every hit is a candidate lead. Read the actual complete current Article with `vault.read` before using it as a new contextual-link endpoint. A snippet never substitutes for a complete read.
- For independent stories, use separate focused queries so each story's candidates remain attributable to that story. Batching changes the number of model decisions, not the evidence standard.
- Stop on an unavailable search. A new query may vary descriptive wording; do not fabricate a ref or claim an unread candidate was verified.

Use the optional `scope` when the task needs a restricted candidate corpus. For contextual links to current Knowledge outside a rotating branch, add `"scope":{"kind":"knowledge","current_only":true,"exclude_subtrees":["News & Research/Top Stories"]}` to the same query/batch call. Filtering happens before candidate limits, so excluded stories and stale or non-Knowledge Articles cannot consume the result slots. Omit scope for historical or general searches. An eligible candidate still needs a complete current read and a justified relationship.
