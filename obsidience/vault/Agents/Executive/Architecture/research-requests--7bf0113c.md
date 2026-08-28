---
approved_at: '2026-08-26T06:56:58'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/link)
title: Research requests
---

When accepted Knowledge is insufficient, Executive activates one bounded Darwin
outcome: Question, Learn, News, or Model. An ad hoc request runs immediately; a
recurring request adds a schedule to the same Task and remains pending while
[[Agents/Executive/Architecture/real-time-executive|Real-time Executive]] runs,
because that surface leaves autonomous specialist schedules and triggers
unclaimed. Both use ordinary Task activation.

The Task states the gap, target, expected artifact, and acceptance conditions.
Its Runbook owns framing, discovery, collection, screening, assessment,
extraction, analysis, verification, and handoff. These stages remain procedure
unless one becomes an independently queueable outcome.

Darwin prefers current direct or primary sources and bounded corroboration. He
captures selected evidence in Source and drops one self-contained finding with
exact `source://` pointers into the physical `obsidience/evidence/inbox/`. Its
`source.inbox` event activates Alexandria's centralized Ingest Task, which
reconciles it into maintained Knowledge. Heimdall independently verifies
consequential evidence or contradictions.

If research reveals a reusable capability gap, Executive follows the evidence
with the appropriate Generate Task. A Tool is not accepted until its executable
binding and paired Skill both exist and validate.

## Relationships

- `uses` [[Agents/Darwin/Darwin|Darwin]] - Darwin owns research acquisition and synthesis.
- `depends_on` [[Agents/Alexandria/Alexandria|Alexandria]] - Alexandria turns findings into maintained Knowledge.
- `implements` [[Agents/Executive/Architecture/task-activation--b30a4642|Task activation]] - Research uses the same activation law as all work.
