---
type: tool
title: vault.validate
description: Run deterministic validation of Article formats and load-bearing references.
obsidience:
  binding: capability:vault.validate
  source: obsidience/harness/capabilities/vault/validate.py
---

## Runtime

Run deterministic validation of Article formats and load-bearing references. No arguments. This checks structural contracts, not every factual claim or a successful application effect.

## Reference

Deterministic graph validator: checks every load-bearing frontmatter edge in
the vault, including the strict one Skill → one Tool pairing and the ban on
direct Runbook Tool grants.

Arguments: `{}`. The result reports checked and broken edges in one call; do
not emulate validation by enumerating and reading articles manually.
