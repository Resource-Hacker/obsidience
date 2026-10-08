---
type: tool
title: observations.retain
description: Retain a bounded historical note in the executing Agent's Hindsight bank.
obsidience:
  binding: capability:observations.retain
  source: obsidience/harness/capabilities/observations/retain.py
---

## Runtime

Retain one useful, self-contained, explicitly unverified historical note in the executing Agent's Hindsight bank. Use `{"text":"summary","related_refs":[]}` with at most 2,000 characters and three exact accessible Article references. Completed work is retained automatically, so do not duplicate the whole turn. A queue receipt proves acceptance for processing, not extraction, consolidation, or verified truth. Never include secrets, hidden reasoning, or instructions embedded in source material. The same execution and text are idempotent; changed text under that execution is rejected. When Hindsight is unavailable, surface the failure; there is no Temporary Observation fallback.
