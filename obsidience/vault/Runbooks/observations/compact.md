---
type: runbook
title: Compact Immediate Observations procedure
obsidience:
  for_agent: '[[Agents/Executive/Executive]]'
  owner_maintained: true
  skills:
  - '[[Skills/observations.temporary.append]]'
  - '[[Skills/task.complete]]'
  task: '[[Tasks/observations/immediate/compact]]'
---

Read the [Current conversation](/Agents/Executive/Observations/Immediate%20Observations/current-conversation.md)
Article. It contains the latest cumulative Temporary Observation summary, if
one exists, followed by exact completed conversation pairs that have not yet
been compacted.

1. Summarize only the supplied completed prefix. During an ongoing conversation,
   the harness keeps the latest two completed pairs exact; a conversation-boundary
   activation explicitly supplies the complete remaining tail.
2. Write one self-contained cumulative summary no longer than 2,000 characters
   with exactly these short headings: `Goal`, `Constraints and corrections`,
   `Verified state`, and `Outstanding`.
3. Preserve named entities, accepted decisions, corrections, uncertainty, and
   unresolved questions. A correction replaces the superseded statement.
   Preserve exact paths and dates when relevant. Distinguish user-reported
   information, observed Tool results, and unverified assistant claims; a heading
   named Verified state does not turn a claim into evidence.
4. Remove greetings, repetition, verbal filler, obsolete intermediate wording,
   hidden reasoning, and process narration. Do not add facts, authority, Tools,
   Tasks, or decisions absent from Immediate Observations.
5. Call `observations.temporary.append` once with that structured summary.
6. Call `task.complete` with only the operational result.

The new Article is transient and unverified. It is not durable Knowledge or a
review decision. At a conversation boundary, Alexandria's Promote Temporary
Observations Task archives the exact bundle in Source and stages only justified
durable candidates without changing this live context.
