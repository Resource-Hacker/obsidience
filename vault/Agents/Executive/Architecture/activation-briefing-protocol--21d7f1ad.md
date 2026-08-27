---
approved_at: '2026-08-27T15:16:57'
kind: knowledge
provenance: proposed by Codex (task codex:knowledge-handoff)
title: Activation packet protocol
---

An activation packet gives a small local model the smallest complete set of
Articles needed for one outcome. The same executor compiles it for live text,
live voice, manual Tasks, scheduled Tasks, and event-triggered Tasks. The
visible packet is the Thinking Packet; graph activity publishes the exact
Article refs the model received.

Fast search may nominate a Task candidate, but the harness must select one exact
accepted Task. Its authored links then resolve assignee, Runbook, Skills, and
Tools; similarity cannot replace or broaden authority. The Knowledge lane
combines lexical and vector search with weighted reciprocal-rank fusion, keeps
three direct hits when available, and admits at most two directly linked
neighbors. It has no generative expansion, cross-encoder pass, or elapsed-time
deadline.

## Packing order

1. Agent Identity Article.
2. Exact Task Article, parameters, exclusions, and acceptance conditions.
3. Authorized Tool Articles.
4. Exact paired Skill Articles.
5. Applicable Runbook Articles.
6. Up to five relevant accepted Knowledge Articles, including bounded direct
   graph neighbors.
7. For the active Executive conversation only, the single
   [[Agents/Executive/Observations/immediate-observations|Immediate Observations]]
   Article.

Immediate Observations is transient and unverified, has retrieval disabled, and
grants no Task, Tool, Policy, or durable Knowledge authority. It contains the
newest cumulative Temporary Observation summary followed by exact completed
public conversation pairs after that summary's boundary. The current owner
request is carried by the Task parameters and always wins.

Every activation uses a 1,200-estimated-token Knowledge allowance. Every section
keeps its semantic label. Retrieval failure may remove optional background
Knowledge, but it can never invent authority, procedure, a Tool, or a success
claim. Immediate Observations is attached by exact identity rather than search.

The execution ledger records the exact Task, Runbook hash, reasoning effort,
calls, evidence, and terminal result. The activation stream publishes the exact
packet refs and measured search duration so the working graph can visualize
every run without creating another graph kind.
