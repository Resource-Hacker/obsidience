---
for_agent: '[[Agents/Executive/Executive]]'
kind: runbook
owner_maintained: true
skills:
- '[[Skills/appending-temporary-observations]]'
- '[[Skills/completing-a-task]]'
task: '[[Tasks/observations/immediate/compact]]'
title: Compact Immediate Observations procedure
---

Read the current [[Agents/Executive/Observations/immediate-observations|Immediate Observations]]
Article. It contains the latest cumulative Temporary Observation summary, if
one exists, followed by exact completed conversation pairs that have not yet
been compacted.

1. Preserve current owner intent, accepted decisions, named entities, durable
   constraints, outstanding work, and unresolved questions.
2. Remove repetition, greetings, verbal filler, superseded intermediate
   wording, and completed details that no longer affect continuation.
3. Preserve uncertainty as uncertainty. Do not add facts, authority, Tools,
   Tasks, or decisions absent from Immediate Observations.
4. Call `observations.temporary.append` once with one self-contained cumulative
   summary no longer than 2,000 characters.
5. Call `task.complete` with only the operational result.

The new Article is transient and unverified. It is not durable Knowledge or a
review decision. At a conversation boundary, Alexandria's Promote Temporary
Observations Task archives the exact bundle in Source and stages only justified
durable candidates without changing this live context.
