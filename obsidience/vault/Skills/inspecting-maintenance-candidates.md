---
kind: skill
title: Inspecting maintenance candidates
tool: '[[Tools/vault.maintenance]]'
---

Call `vault.maintenance` once per Curate execution with an empty argument
object. Treat its ranked results as leads, never conclusions. Use only the
exact `recommended_task`, `candidate_key`, and `refs` returned together in one
candidate. Select at most the first candidate when its destination Task is not
already carrying that exact candidate key; the Tool filters active and queued
keys. The scheduler may queue a distinct candidate behind work already in that
Task. A clean result is successful curation; do not invent work to avoid
reporting no change.
