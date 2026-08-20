---
title: vault-gardening
kind: runbook
---
Procedure for one gardening pass over the vault.

1. `search_vault` for notes mentioning deprecated names, TODO markers, or
   contradictions with newer notes.
2. Pick the single most valuable fix you can argue for in two sentences.
3. `read_note` everything you intend to change; never propose edits to notes
   you have not read this session.
4. Stage at most three `propose_note` calls (action `update` keeps the full
   corrected body). Reasons must cite evidence notes as [[wikilinks]].
5. If the vault is clean, finish with status `done` and say so — an empty
   pass is a valid result.
