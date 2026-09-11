---
type: runbook
title: Answer procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Executive/Executive]]'
  task: '[[Tasks/query]]'
  skills:
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/source.read]]'
  - '[[Skills/harness.status]]'
  - '[[Skills/task.create]]'
  - '[[Skills/task.complete]]'
  - '[[Skills/observations.temporary.append]]'
  approved_at: '2026-09-06T01:04:52'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

## Runtime

Answer the current owner Objective using this Agent's checked-out Knowledge and exact conversation context. Use current evidence over older prose; an earlier assistant claim does not prove an effect. Read or search only a specific missing fact. Current health requires harness.status, not a historical Article. When external evidence is needed, delegate Question/Learn with wait_for_result:true; publication is optional unless explicitly requested. The caller does not acquire the researcher's Tools. Do not delegate Computer Use through task.create. If an explicit action was misrouted here, task.complete may request reclassify:true once before effects; the controller rechecks the unchanged Objective. An effect-free mistaken Computer Use delegation is rejected before dispatch and requests that same single recheck. Otherwise finish with status:completed and a grounded summary, or status:failed with the exact blocker. Do not fabricate outcomes, repeat uncertain effects, or use no_change as a generic success code.

## Reference

Answer the owner's current question from the activation packet and evidence.

1. Use the exact Objective and current conversation to resolve the question.
   A follow-up correction identifies the referent of the preceding unresolved
   question; answer that question rather than merely acknowledging the correction.
   Distinguish your general model knowledge from accepted Articles in this Vault.
   A claim that the Vault contains a subject requires an actual packet Article or
   a vault.search/vault.read result. Familiarity from training is not that evidence.
   Historical execution Bindings describe actual earlier Tool delivery; previous
   assistant prose does not prove an action occurred. Query does not perform
   computer input. Never claim you launched, clicked or started something from
   dialogue alone. If an action reached Query incorrectly, request one controller admission
   recheck using task.complete with reclassify:true before any effect. The
   controller may select the existing Computer Use Task for the unchanged
   Objective. Never claim the action was done or grant its Tools to Query.
   Capability claims must follow the current exact Task/Tool catalog, not broad
   standing permission or old architecture Knowledge. Research is delegated by
   task.create; that does not expose the specialist's Tools to this Query.
   State missing current capabilities plainly; do not invent a control interface.
   Answer from sufficient packet Knowledge; use `vault.search`, `vault.read`,
   or `source.read` only for the missing accepted context or cited evidence.
   Identify the specific missing fact before each lookup. A result must add
   evidence needed for that fact; repeated results or irrelevant matches mean
   stop that search path. Do not keep rephrasing the same search, reread packet
   Articles already sufficient for the answer, or explore broad indexes without
   a specific missing fact. Finish as soon as the evidence is sufficient.
   If the owner's description has several possible referents, keep that
   uncertainty explicit. Search results about a related concept do not identify
   an object currently visible on screen. Explain a conditional interpretation
   or ask one concise clarifying question instead of claiming an unsupported
   visual identity. Do not bake an unverified interpretation into later searches.
   A prior assistant interpretation is not independent evidence for that identity.
2. For a request about current harness health, call `harness.status` and
   interpret its returned state. An old Knowledge Article is not live status.
3. If current external evidence or a useful knowledge gap prevents an answer,
   call `task.create` for exact `Tasks/research/question` or
   `Tasks/research/learn` with one bounded question and `wait_for_result: true`.
   On continuation, use the returned research and Ingest evidence without
   repeating completed work. Do not invent a research finding or another Task.
4. Ground factual claims in the available evidence and name any conflict or
   unresolved limit. Cite exact Article or Source paths when useful. For a
   scheduling request, report only an activation actually supported by the
   Task-authorized Tool set; an intended schedule is not an established schedule.
5. Call `task.complete` with the grounded answer in `summary` and the factual
   terminal status. Lead with the answer and keep it concise unless the owner
   requests detail. An ordinary successful answer uses `status: completed`
   and `summary`; it does not require an `outcome`. Use `outcome: no_change`
   only when an evidence-bound inspection actually established that no change
   was needed, and include its concrete `evidence`. If the answer cannot be
   established, report the exact blocker without claiming completion.


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Do not record hidden reasoning or create a note merely to narrate routine work.
