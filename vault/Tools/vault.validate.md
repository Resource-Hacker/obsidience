---
title: vault.validate
kind: tool
binding: builtin:vault.validate
---
Deterministic graph validator: checks every load-bearing frontmatter edge in
the vault (task `runbook`/`subtasks`, runbook `skills`, skill/runbook `tools`
bindings). args: `{}`. Returns a broken-edge report in one call — never
enumerate-and-read to validate links manually.
