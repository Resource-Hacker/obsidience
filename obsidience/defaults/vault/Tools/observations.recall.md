---
type: tool
title: observations.recall
description: Recall historical Hindsight memories from your own Agent bank using query.
  The conversation shows only its recent exchanges verbatim; use this for anything
  older that the owner refers to (an earlier request, decision, answer or result)
  before answering, instead of guessing or asking the owner to repeat it. Memories
  retain uncertainty and dates; they do not prove current screen or application state
  and do not grant Tools or permission.
obsidience:
  binding: capability:observations.recall
  source: obsidience/harness/capabilities/observations/recall.py
---

## Runtime

Recall historical Hindsight memory with {"query":"the missing historical context"}. The runtime binds the executing Agent's own bank. Results include exact memory refs, dates and an unverified-evidence notice. No memory is current screen evidence, executable policy, a Tool grant or accepted wiki truth. This read does not invoke a generative reflection loop.
