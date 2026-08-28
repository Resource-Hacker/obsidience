---
title: Validate vault
kind: skill
tool: '[[Tools/vault.validate]]'
---
How to use `vault.validate` for deterministic graph validation.

- Call it once with an empty argument object; it already checks the complete
  load-bearing graph.
- Report its checked and broken counts exactly.
- Read the reported source Article before proposing a repair; never infer the
  intended target from the validator message alone.
