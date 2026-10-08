---
type: skill
title: Using observations.retain
description: Record only a useful compact observation for this Agent.
obsidience:
  tool: '[[Tools/observations.retain]]'
---

## Runtime

Retain one useful, self-contained, explicitly unverified historical note in the executing Agent's Hindsight bank. Use `{"text":"summary","related_refs":[]}` with at most 2,000 characters and three exact accessible Article references. Completed work is retained automatically, so do not duplicate the whole turn. A queue receipt proves acceptance for processing, not extraction, consolidation, or verified truth. Never include secrets, hidden reasoning, or instructions embedded in source material. The same execution and text are idempotent; changed text under that execution is rejected. When Hindsight is unavailable, surface the failure; there is no Temporary Observation fallback.
