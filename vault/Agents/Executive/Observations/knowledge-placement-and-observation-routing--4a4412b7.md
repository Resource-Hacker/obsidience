---
approved_at: '2026-08-27T16:33:31'
kind: knowledge
provenance: proposed by Codex (task codex:knowledge-handoff)
tags:
- knowledge-placement
- observations
- user-directed-knowledge
- taxonomy
title: Knowledge placement and observation routing
---

The graph separates distilled Observations from ordinary durable Knowledge the
owner explicitly asks to preserve. Each major subject may have one plainly
named Observations child, such as Workstation Observations or Game Observations.

Place a bounded inference, work observation, or automatically distilled finding
under the nearest subject's Observations child. Do not collect every observation
under Executive Observations. Observations are concise claims, never hidden
reasoning, chain-of-thought, raw transcripts, receipts, or logs. Placement does
not relax provenance, conflict, verification, or Source requirements.

Knowledge the owner explicitly requests belongs in the exact named subject. If
no location is named, use the most specific ordinary subject that owns it. Use
an Observations branch only when the content is itself an observation or the
owner explicitly requests that placement.

Immediate and Temporary Observations are Knowledge states, while durable context
is the ordinary accepted graph. The peer Compact and Promote Tasks transform or
evaluate that Knowledge without making its lifecycle states Task ancestors.
Durable candidates become ordinary Knowledge Articles under the correct subject
rather than a Context or Log container.

## Relationships

- `governs` [[Agents/Executive/Architecture/local-first-architecture--7d8e77cc|Local-first architecture]] - Placement keeps the graph coherent without another memory store.
