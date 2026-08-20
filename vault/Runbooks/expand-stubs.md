---
title: expand-stubs
kind: runbook
skills: ["[[Skills/reading-the-vault]]", "[[Skills/proposing-changes]]"]
---
Expand a short article (Wikipedia Task Center pattern).

1. `vault.list` Agent; identify the stubbiest note (shortest body that
   is not the index).
2. `vault.search` the vault for related material (receipts excluded); read
   what you find.
3. If the vault contains enough grounded material to enrich the stub,
   `vault.propose` (update) the expanded note — full corrected body, every
   claim traceable to a vault note cited as a [[wikilink]]. Keep the whole
   body under ~40 lines: one focused improvement per pass, not a rewrite. NEVER pad with
   invented content: if there is nothing grounded to add, complete
   "completed" and say the stub must wait for sources.
