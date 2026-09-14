---
type: knowledge
sources:
- resource: DESIGN.md
- resource: obsidience/harness/interfaces/api/app.py
- resource: obsidience/harness/knowledge/source.py
- resource: obsidience/harness/knowledge/system.py
- resource: obsidience/shell/surfaces/knowledge/host.py
title: Local-first architecture
---

# Local-first architecture

Obsidience is a local-first application with one authority for each concern.
Accepted Markdown in `obsidience/vault/` defines Knowledge and reusable work,
and those vault Articles are the knowledge-graph nodes classified by the
[Golden ontology](/Agents/Executive/Architecture/Harness/action-ontology.md).
Immutable captures live in `obsidience/evidence/`; physical descriptors remain
in `obsidience/state/system/`; SQLite records execution, conversation, publication
and indexing state. Rebuildable search indexes are not a second authored wiki.
The [LLM-wiki knowledge pattern](/Agents/Executive/Architecture/Harness/llm-wiki-knowledge-pattern--dab5ff0a.md)
documents how that vault Knowledge is captured, retrieved, and published.

The Harness owns the API, Task admission and execution, model leases, retrieval,
conversation and speech subsystems. The [Shell](/Agents/Executive/Architecture/Shell/Shell.md) owns desktop
presentation and explicit commands. Hyprland owns composition and native window
behavior; Quickshell owns shell panes; the knowledge desktop has its own
GTK/WebKit presenter. Linux services and drivers remain upstream plumbing.
Real component changes across these owned surfaces follow the [Cordis composition](/Agents/Executive/Architecture/Harness/cordis-composition.md) project-wide dependency and lifecycle rules.

Source is broader than immutable captures: It also exposes actual project
files, wiki Markdown and registered System descriptors at exact paths. A Source
checkout is a retrieval preference, not a Tool grant or an unconditional prompt
attachment. The the local System inventory Knowledge
projection is shallow: Applications, Compute, Devices, Drives and Network sit
beneath System. Hardware remains a physical descriptor grouping only, and each
application is one leaf Article with its details inside it.

The low-parameter model target motivates a small, labeled
[Thinking Packet](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md), exact accepted
[Task dependencies](/Agents/Executive/Architecture/Harness/task-activation--b30a4642.md), closed Tool schemas and explicit
completion evidence. Local-first does not mean offline-only: an authorized Tool
may retrieve external evidence through its real implementation. No description,
UI button or model-generated claim creates a missing Capability.
