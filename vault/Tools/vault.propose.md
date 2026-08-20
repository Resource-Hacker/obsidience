---
title: vault.propose
kind: tool
binding: builtin:vault.propose
---
Stage a note change for owner review — never writes the vault directly.
args: `{"action": "create|update", "target": "Folder/name.md", "title": str,
"body": str, "reason": str}`. `update` must carry the FULL corrected body.
