---
type: knowledge
sources:
- resource: obsidience/harness/knowledge/retrieval.py
- resource: obsidience/harness/knowledge/source.py
- resource: obsidience/harness/knowledge/system.py
- resource: obsidience/harness/knowledge/review.py
- resource: obsidience/harness/execution/scheduler.py
title: LLM-wiki knowledge pattern
obsidience:
  approved_at: '2026-09-10T23:49:22.333585+00:00'
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
---

The maintained Markdown wiki is the Agent fleet's durable knowledge. Source
captures preserve what was observed; accepted Articles supply the concise
synthesis used in later work. A parent Article is a readable index and
condensation of its actual descendants, not a separate Article type.

## Evidence, Knowledge and runtime

`obsidience/evidence/` retains immutable captures, including research handoffs and
System evidence. `obsidience/vault/` holds accepted Articles. The Source browser
also exposes real project files and System descriptors; not every Source file
is an immutable capture. `DESIGN.md` and `AGENTS.md` define project contracts,
while the implemented codec and validators enforce supported document behavior.

The current activation retrieval path is lexical plus dense-vector search with
weighted reciprocal-rank fusion and a small allowance of direct graph
neighbors. It does not generate recursive RAPTOR summaries, expand queries with
a model or run a cross-encoder on the activation path. Limits and excerpting
are documented in [Activation packet protocol](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md).
Similarity supplies Knowledge; exact accepted edges select executable authority.

## Publication paths

[Question or Learn](/Agents/Executive/Architecture/Harness/research-requests--7bf0113c.md) can acquire evidence for a
knowledge gap. An ordinary new Source may activate Darwin's Learn Task; an
attested Feed item selects Distill with its fixed destination. Darwin's cited
handoff goes into `obsidience/evidence/inbox/`; `source.inbox` activates
Alexandria's [Ingest](/Tasks/ingest.md). Ingest reconciles the handoff through the
existing proposal and Review owner. Auto-curate permits eligible publication
only under the destination's current policy.

System inventory is a distinct deterministic publisher backed by immutable
System evidence, not an Agent research Task. Observation archives do not loop
back into ordinary Learn. Capturing Source, compacting dialogue or receiving a
handoff does not by itself accept durable claims.

[Golden ontology](/Agents/Executive/Architecture/Harness/action-ontology.md) defines the Article boundaries, and
[Observation lifecycle](/Agents/Executive/Architecture/Harness/observations.md) distinguishes temporary conversation
context from accepted Knowledge.
