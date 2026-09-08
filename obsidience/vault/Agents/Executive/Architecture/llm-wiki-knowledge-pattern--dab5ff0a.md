---
type: knowledge
sources:
- resource: file:///home/wissenschafter/Projects/obsidience/AGENTS.md
- resource: file:///home/wissenschafter/Projects/obsidience/DESIGN.md
title: LLM-wiki knowledge pattern
obsidience:
  approved_at: '2026-09-08T12:46:54'
  provenance: proposed by Alexandria (task Tasks/link)
---

Obsidience applies [Andrej Karpathy's LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
as the durable brain of the Agent fleet. Knowledge compounds in concise,
linked, human-editable Articles instead of being buried in transcripts or one
oversized prompt.

## Layers

1. **Source** preserves immutable external material in ordinary files under
   `obsidience/evidence/`, including captured pages, documents, code, data, and
   images.
2. **Wiki** is the maintained synthesis in Markdown under `obsidience/vault/`.
   Every node is an Article; a parent Article is its descendants' index and
   condensation.
3. **Schema** is the project law in `AGENTS.md` and `DESIGN.md`.
4. **Activation** retrieves a small relevant Knowledge set and combines it with
   the exact Task capability spine in one semantically labeled Thinking Packet.

The packet's labels, packing order, and Knowledge allowance are specified in [Activation packet protocol](/Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad.md).

The capability spine is the exact accepted Task's resolved Runbook, Skills, and Tools, as defined in [Task activation](/Agents/Executive/Architecture/task-activation--b30a4642.md).

The graph stays useful by changing accepted Articles in place, consolidating
duplicates, removing filler and stale architecture, and preserving exact raw
Source outside retrieval. Similarity supplies context; exact graph edges select
what may run. Search indexes and navigation projections are rebuildable views of
the files, never competing truth stores.

New immutable Source follows one visible research route: `source.added` may
activate Darwin's existing [Learn](/Tasks/research/learn.md) Task. Darwin researches
the exact Source and writes at most one cited synthesis to the physical Source
Inbox. That write emits `source.inbox` for Alexandria's centralized
[Ingest](/Tasks/ingest.md) Task. Source writes do not create Knowledge; Ingest
reconciles the handoff and its cited Sources against the current wiki and stages
only justified Article changes.

This pattern is designed to make a low-parameter local model effective by supplying the right knowledge and procedural context at activation time rather than demanding broad latent recall.

## Relationships

- `implements` [Golden ontology](/Agents/Executive/Architecture/action-ontology.md) — The wiki stores the six canonical Article kinds without inventing folder or index kinds.
- `depends_on` [Activation packet protocol](/Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad.md) — Retrieval becomes useful model context through one bounded packet.
- `related_to` [Research requests](/Agents/Executive/Architecture/research-requests--7bf0113c.md) — The missing-knowledge loop obtains evidence before Alexandria changes the wiki.
- `related_to` [Darwin](/Agents/Darwin/Darwin.md) — The pattern's visible research route is executed by Darwin, whose Learn Task produces the Source Inbox handoff that emits `source.inbox`.
