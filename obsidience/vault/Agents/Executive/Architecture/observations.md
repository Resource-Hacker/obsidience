---
type: knowledge
title: Observation lifecycle
sources:
- resource: file:///home/wissenschafter/Projects/obsidience/obsidience/harness/conversation/observations.py
- resource: file:///home/wissenschafter/Projects/obsidience/obsidience/harness/conversation/store.py
- resource: file:///home/wissenschafter/Projects/obsidience/obsidience/harness/realtime/runtime.py
obsidience:
  approved_at: '2026-09-07T14:59:29'
  provenance: proposed by Alexandria (task Tasks/link)
---

Observations use the same Article hierarchy as the rest of the graph. The three
memory levels have distinct retention, not competing stores or Agent roles.

## Auto-curate permission

The owner enables Auto-curate on the real branch Article. Children inherit it
unless explicitly switched off; the Reader checkbox and dotted rings show the
same effective permission. This setting permits an existing writer, not a new
schedule or a Task per node. It does not make an unverified observation true.
The specialist Brains and Executive Observations are enabled, while shared
Tools, Skills, Tasks, Runbooks and Agent identity remain review-controlled.

Turning Immediate off freezes its disk Article but retains the exact SQLite
conversation and in-memory model context. Turning Temporary off prevents new
appends and compaction summaries; existing entries are not erased. Compact and
Promote keep their own Task triggers. A disabled cache cannot silently accept
writes merely because its Task was already enabled.

## Immediate

[Current conversation](/Agents/Executive/Observations/Immediate%20Observations/current-conversation.md)
is a child of Immediate Observations. It projects the active Chat's latest
cumulative summary plus exact completed pairs after that boundary. Typed Chat
and [Realtime](/Agents/Executive/Architecture/real-time-executive.md) share an 80-turn hot deque backed by complete SQLite dialogue.
Realtime enable creates a new conversation; stopping Realtime retains it for Chat.
The current request rides once as the Objective, not as a duplicate historical turn.

The exact context Article rides separately in the
[Thinking Packet](/Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad.md)
and drives graph activity. It is transient, unverified, and excluded from similarity
retrieval; quoted historical requests or assistant claims do not grant authority.

## Temporary

[Compact](/Tasks/observations/immediate/compact.md) runs at 80% model-context occupancy
by default, configurable from 60–90%, or by the owner's Compact button. It uses
its authored model and [Compact procedure](/Runbooks/observations/compact.md). Ongoing
compaction keeps two newest completed pairs exact; a conversation boundary includes
the remaining tail. Each cumulative summary is a separate Article capped at 2,000
characters, preserving corrections and distinguishing reported from verified results.

Ordinary Temporary retention is ten entries, 20,000 characters, and 24 hours.
The active conversation's newest committed summary is protected from expiry within
that count; pending promotion inputs are retained separately until archived.
Failed compaction does not replace the committed context or delete SQLite history.

## Durable

At a conversation boundary, the ordinary `observations.temporary.ready` event
activates [Promote](/Tasks/observations/durable/promote.md) for
[Alexandria](/Agents/Alexandria/Alexandria.md). Her
[Promote procedure](/Runbooks/observations/promote.md) archives the exact bundle in
Source, searches existing Knowledge, and proposes only justified additions,
corrections, or links through the normal proposal validator. Owner-enabled
destinations may publish scoped Knowledge creates/updates automatically;
disabled destinations and unsupported changes remain in Review. No-change is a
valid result. Source archival and compaction alone never accept durable claims
or trigger redundant research.

Durable findings belong under their subject in the accepted wiki. Established
interaction requirements belong in
[Preferences](/Agents/Executive/Observations/Preferences/Preferences.md); game mechanics go
under Games, workstation facts under ADMECH. Do not create a second Durable Context,
Log, or memory database. Hidden reasoning is never an Observation Article.
