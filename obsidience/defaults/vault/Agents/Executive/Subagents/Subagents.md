---
type: knowledge
title: Subagents
---

The Executive coordinates three specialists, each with one canonical Brain
Article and assigned Tasks. Each Task's applicable accepted Runbook supplies
its required shared Skill and Tool dependencies automatically.

- [Darwin](/Agents/Darwin/Darwin.md) researches evidence and generates missing
  reusable assets. He sends cited findings to the Source Inbox.
- [Alexandria](/Agents/Alexandria/Alexandria.md) ingests that Inbox and curates
  the wiki through Ingest, Curate, Merge, Link, Improve, Archive, and Promote.
- [Heimdall](/Agents/Heimdall/Heimdall.md) provides independent Audit and Check.

Use [task.create](/Tools/task.create.md) only for an exact accepted peer Task.
Delegation records causation, not a new subtask hierarchy. Follow
[Research delegation](/Agents/Executive/Architecture/Harness/research-requests--7bf0113c.md)
for a knowledge gap; do not create duplicate role-charter Articles here.
