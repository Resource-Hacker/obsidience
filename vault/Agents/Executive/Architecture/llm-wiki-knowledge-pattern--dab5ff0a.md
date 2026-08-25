---
approved_at: '2026-08-25T05:44:31'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/merge)
title: LLM-wiki knowledge pattern
---

Obsidience uses a Karpathy-style wiki as the durable brain of the agent fleet.
Knowledge compounds in concise, linked, human-editable Articles instead
of being buried in transcripts or one oversized prompt. Agents continuously
ingest, improve, verify, and retrieve this wiki through explicit Tasks and
Runbooks.

## Layers

1. **Source** preserves immutable external blobs such as captured pages,
   documents, code, data, and images.
2. **Knowledge Articles** contain the maintained synthesis. Every Article is
   readable, and any Article with descendants is their index and condensation.
3. **Typed work Articles** separate outcomes, procedures, capability,
   capability guidance, and accountable executors into Task, Runbook, Tool,
   Skill, and Agent kinds.
4. **RAPTOR activation** fuses direct lexical and semantic matches, adds at
   most two linked Knowledge neighbors, and packs the useful result with the
   exact capability spine into one semantically labeled activation packet.

The capability spine is the exact accepted Task's resolved Runbook, Skills,
and Tools, as defined in [[Agents/Executive/Architecture/task-activation--b30a4642|Task activation]].

The graph stays useful by changing accepted Articles in place, removing
duplicates and filler, and preserving exact Source material outside retrieval.
Similarity supplies context; exact graph edges select what may run.

## Maintenance loop

- Darwin researches one bounded gap and preserves direct evidence.
- Alexandria reconciles the finding into the smallest coherent set of
  Knowledge Articles.
- Heimdall verifies evidence, contradictions, and graph integrity when needed.
- Executive queries the updated graph and continues the owner's outcome.

This pattern is designed to make a low-parameter local model effective by
supplying the right knowledge and procedural context at activation time rather
than demanding broad latent recall.

## Relationships

- `governs` [[Agents/Alexandria/Alexandria|Alexandria]] - Alexandria maintains accepted Knowledge.
- `governs` [[Agents/Darwin/Darwin|Darwin]] - Darwin acquires missing external knowledge.
- `governs` [[Agents/Executive/Subagents/heimdall-guardian-role--3d93da53|Heimdall role charter]] - Heimdall verifies evidence and graph integrity.
