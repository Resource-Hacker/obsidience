---
approved_at: '2026-08-26T03:02:43'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/link)
sources:
- AGENTS.md
- DESIGN.md
title: LLM-wiki knowledge pattern
---

Obsidience instantiates [Andrej Karpathy's LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) as the durable brain of the agent fleet. Knowledge compounds in concise, linked, human-editable Articles instead of being buried in transcripts or one oversized prompt. Agents continuously ingest, improve, verify, and retrieve this wiki through explicit Tasks and Runbooks.

## Layers

1. **Raw Source** preserves immutable external material in ordinary files under `obsidience/evidence/`, including captured pages, documents, code, data, and images.
2. **The wiki** is the maintained synthesis in ordinary Markdown under `obsidience/vault/`. Every Article is readable, and any Article with descendants is their index and condensation.
3. **The schema** is the project law in `AGENTS.md` and `DESIGN.md`; it tells agents how to maintain the wiki and operate the harness.
4. **Typed Articles** separate knowledge, outcomes, procedures, executable interfaces, capability guidance, and accountable executors into Knowledge, Task, Runbook, Tool, Skill, and Agent kinds.
5. **RAPTOR activation** fuses direct lexical and semantic matches, adds at most two linked Knowledge neighbors, and packs the useful result with the exact capability spine into one semantically labeled activation packet.

The packet's labels, packing order, and Knowledge allowance are specified in [[Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad|Activation packet protocol]].

The capability spine is the exact accepted Task's resolved Runbook, Skills, and Tools, as defined in [[Agents/Executive/Architecture/task-activation--b30a4642|Task activation]].

The graph stays useful by changing accepted Articles in place, removing duplicates and filler, and preserving exact raw Source outside retrieval. The Source explorer also exposes the wiki, application code, and stable System descriptors at their literal project-relative disk paths. Its `SYSTEM`, `OBSIDIENCE`, `HARDWARE`, `DRIVES`, `DEVICES`, and `NETWORK` groupings are presentation namespaces only; every leaf retains and opens its exact disk bytes. Similarity supplies context; exact graph edges select what may run; every index remains a rebuildable derivative of the files.

New immutable raw Source follows one visible research edge: `source.added` is
one trigger on Darwin's existing Learn Task. Darwin researches the exact Source
and writes at most one cited synthesis beneath the physical `obsidience/evidence/inbox/`.
That durable write emits `source.inbox` for Alexandria's centralized Ingest
Task. Source writes do not create Knowledge; Ingest reads the handoff and every
nested citation, searches the current wiki, and stages only justified Article
changes. Duplicate capture or handoff emits no event.

## Maintenance loop

- Darwin researches one bounded gap and preserves direct evidence.
- Alexandria ingests each Source Inbox handoff into the smallest coherent set of Knowledge Articles.
- Heimdall verifies evidence, contradictions, and graph integrity when needed.
- Executive queries the updated graph and continues the owner's outcome.

This pattern is designed to make a low-parameter local model effective by supplying the right knowledge and procedural context at activation time rather than demanding broad latent recall.

## Relationships

- `governs` [[Agents/Alexandria/Alexandria|Alexandria]] - Alexandria maintains accepted Knowledge.
- `governs` [[Agents/Darwin/Darwin|Darwin]] - Darwin acquires missing external knowledge.
- `governs` [[Agents/Heimdall/Heimdall|Heimdall]] - Heimdall verifies evidence and graph integrity.
