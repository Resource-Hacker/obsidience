---
type: knowledge
title: Research requests
obsidience:
  approved_at: '2026-08-31T07:38:14'
  provenance: proposed by Alexandria (task Tasks/link)
---

When accepted Knowledge is insufficient, Executive delegates one bounded outcome
to [Darwin](/Agents/Darwin/Darwin.md): [Question](/Tasks/research/question.md) for a
specific answer, [Learn](/Tasks/research/learn.md) for a reusable knowledge gap,
News for a current-events finding, or Model for local model characterization.

The selected Task states one gap, target, expected artifact, and acceptance
condition. Its Runbook owns framing, discovery, collection, screening,
assessment, extraction, analysis, verification, and handoff; those stages are
procedure, not automatic child Tasks. A recurring request adds a schedule to the
same Task instead of creating a scheduling object or duplicate Task.

Darwin searches accepted Knowledge first, then acquires only the direct evidence
needed. He preserves the selected Source and uses `source.handoff` once to write
one self-contained cited finding into `obsidience/evidence/inbox/`. The resulting
`source.inbox` event activates [Ingest](/Tasks/ingest.md) for
[Alexandria](/Agents/Alexandria/Alexandria.md). Darwin does not write accepted
Knowledge, and Alexandria does not perform the research acquisition.

If the evidence establishes a reusable capability gap, Executive may activate
the appropriate peer Generate Task. A Tool remains unusable until its exact
Source-backed Capability and singular paired Skill validate.

## Relationships

- `implements` [Task activation](/Agents/Executive/Architecture/task-activation--b30a4642.md) — Research outcomes are ordinary peer Tasks with exact assignees and Runbooks.
- `implements` [LLM-wiki knowledge pattern](/Agents/Executive/Architecture/llm-wiki-knowledge-pattern--dab5ff0a.md) — Research supplies the evidence side of the Source-to-wiki loop.
- `depends_on` [Alexandria](/Agents/Alexandria/Alexandria.md) — Only Alexandria's Ingest outcome may reconcile the finding into maintained Knowledge.
- `related_to` [Heimdall](/Agents/Heimdall/Heimdall.md) — Consequential evidence or contradictions may require independent checking.
