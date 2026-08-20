---
title: categorize-notes
kind: runbook
skills: ["[[Skills/reading-the-vault]]", "[[Skills/proposing-changes]]"]
---
Categorization pass (Wikipedia Task Center pattern).

1. `vault.list` Agent; `vault.read` [[Agent/index]].
2. Find notes missing from the index, notes without inbound/outbound
   [[wikilinks]] (orphans), and notes whose title/kind mismatch their content.
3. Propose: index updates, added cross-links between related notes, or a
   corrected `kind`. Max three proposals, each citing the notes it read.
4. A clean pass is a valid completed result.
