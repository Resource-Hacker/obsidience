---
type: skill
title: Using vault.validate
description: Use validation for structural integrity.
obsidience:
  tool: '[[Tools/vault.validate]]'
---

## Runtime

Use validation for structural integrity. A clean result says references and formats passed, not that all prose is correct or the requested external effect occurred. Preserve the reported coverage and unresolved findings.

## Reference

Use `vault.validate` to run the deterministic load-bearing graph validator.

- Pass exactly `{}` and invoke the Tool once for the vault snapshot being
  checked.
- A clean result states the exact number of resolved load-bearing edges and
  `No broken references.` A failing result reports checked and broken counts
  followed by at most 30 exact diagnostics.
- Preserve the returned counts and diagnostics verbatim. A diagnostic identifies
  a structural failure; it does not establish an intended replacement edge.
- Stop on any broken count or unavailable validator result. Repeating the same
  validation without a vault change is not new evidence.
