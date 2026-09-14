---
type: knowledge
title: Observation lifecycle
sources:
- resource: obsidience/harness/knowledge/scope.py
- resource: obsidience/harness/knowledge/index.py
- resource: obsidience/harness/conversation/observations.py
- resource: obsidience/harness/conversation/store.py
- resource: obsidience/harness/conversation/runtime.py
- resource: obsidience/harness/knowledge/auto_curate.py
---

Observations use the same Article hierarchy as the rest of the graph. The three
memory levels have distinct retention, not competing stores or Agent roles.

## Auto-curate permission

The owner enables Auto-curate on the real branch Article. Children inherit it
unless explicitly switched off; the Reader checkbox and dotted rings show the
same effective permission. This setting permits an existing writer, not a new
schedule or a Task per node. It does not make an unverified observation true.
The effective setting comes from the current Article and inherited policy, not
from this Architecture summary. Shared Tools, Skills, Tasks, Runbooks and Agent
identity remain review-controlled.

Turning Immediate off freezes its disk Article but retains the exact SQLite
conversation and in-memory model context. Turning Temporary off prevents new
appends and compaction summaries; existing entries are not erased. Compact and
Promote keep their own Task triggers. A disabled cache cannot silently accept
writes merely because its Task was already enabled.

## Agent ownership

Each Agent writes only its own Temporary Observations. Appends are bound to the
executing Agent and run; related Article refs must be in that Agent's graph.
Observation notes are optional, short and nonredundant, never a narration quota.
The owner can inspect all Observations in Library, but another Agent cannot check
out or search them. Shared Knowledge is checked out by identity, not copied into
separate memories. A curated cross-Agent result travels as explicit evidence.

## Immediate

Each Agent also has a Current activation Article under its own Immediate branch.
It displays the exact objective, resolved entities, supplied/read Article refs,
current status and bounded controller receipts. It is a view of the execution,
not a second authority. The model gets the objective once in its Objective
section. Late progress from an older activation cannot replace the new view.

[Immediate Observations](/Agents/Executive/Observations/Immediate%20Observations/Immediate%20Observations.md)
is a child of Immediate Observations. It projects the active Chat's latest
cumulative summary plus exact completed pairs after that boundary. Typed Chat
and [Realtime](/Agents/Executive/Architecture/Harness/real-time-executive.md) share an 80-turn hot deque backed by complete SQLite dialogue.
Enabling or reconnecting Realtime preserves the selected conversation; stopping
Realtime retains it for Chat. Only the explicit Conversation control creates a
new conversation.
The current request rides once as the Objective, not as a duplicate historical turn.

The exact context Article rides separately in the
[Thinking Packet](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md)
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
Source, reads that exact archive through its returned attested citation, searches
only her checked-out Knowledge, and proposes justified additions,
corrections, or links through the normal proposal validator. Owner-enabled
destinations may publish scoped Knowledge creates/updates automatically;
disabled destinations and unsupported changes remain in Review. No-change is a
valid result. Source archival and compaction alone never accept durable claims
or trigger redundant research.

Durable findings belong under their subject in the accepted wiki. Established
interaction requirements belong in
the Executive's own [Preferences](/Agents/Executive/Observations/Preferences/Preferences.md)
when written by its authorized owner. A Curator handoff cannot grant direct
access to those private notes; proposed shared findings stay in the Curator's
checked-out semantic homes. Game mechanics go under Games, authored workstation findings under System / Workstation
Observations. The generated System inventory remains read-only and is refreshed
by its deterministic publisher. Do not create a second Durable Context,
Log, or memory database. Hidden reasoning is never an Observation Article.

## Relationships
- `depends_on` [Executive model selection](/Agents/Executive/Architecture/Harness/current-executive-model--3745813a.md) — Context capacity comes from the selected model, while compaction executes with the Compact Task’s own authored model and Runbook; retained conversation context does not create another model selector.
