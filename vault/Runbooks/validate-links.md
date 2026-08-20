---
title: validate-links
kind: runbook
skills: ["[[Skills/reading-the-vault]]", "[[Skills/proposing-changes]]"]
---
Validate the vault's graph edges.

1. Run `vault.validate` (args: {}) — one call checks every load-bearing edge.
2. If it reports no broken references, complete "completed" with the count.
3. For each broken edge: `vault.read` the source note, then stage one
   `vault.propose` fix (correct the link when the intended target is obvious;
   otherwise flag it in the reason).
4. Complete with counts: checked, broken, proposals staged.
