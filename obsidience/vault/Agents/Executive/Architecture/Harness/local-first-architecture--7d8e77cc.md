---
type: knowledge
sources:
- resource: DESIGN.md
- resource: obsidience/harness/interfaces/api/app.py
- resource: obsidience/harness/knowledge/source.py
- resource: obsidience/harness/knowledge/system.py
- resource: obsidience/shell/surfaces/knowledge/host.py
title: Local-first architecture
obsidience:
  approved_at: '2026-09-10T23:49:22.333585+00:00'
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
---

Obsidience is a local-first application with one authority for each concern.
Accepted Markdown in `obsidience/vault/` defines Knowledge and reusable work.
Immutable captures live in `obsidience/evidence/`; physical descriptors remain
in `obsidience/state/system/`; SQLite records execution, conversation, publication
and indexing state. Rebuildable search indexes are not a second authored wiki.

The Harness owns the API, Task admission and execution, model leases, retrieval,
conversation and speech subsystems. The [Shell](/Agents/Executive/Architecture/Shell/Shell.md) owns desktop
presentation and explicit commands. Hyprland owns composition and native window
behavior; Quickshell owns shell panes; the knowledge desktop has its own
GTK/WebKit presenter. Linux services and drivers remain upstream plumbing.

Source is broader than immutable captures: it also exposes actual project
files, wiki Markdown and registered System descriptors at exact paths. A Source
checkout is a retrieval preference, not a Tool grant or an unconditional prompt
attachment. The [System](/ADMECH%20Workstation/ADMECH%20Workstation.md) Knowledge
projection is shallow: Applications, Compute, Devices, Drives and Network sit
beneath System. Hardware remains a physical descriptor grouping only, and each
application is one leaf Article with its details inside it.

The low-parameter model target motivates a small, labeled
[Thinking Packet](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md), exact accepted
[Task dependencies](/Agents/Executive/Architecture/Harness/task-activation--b30a4642.md), closed Tool schemas and explicit
completion evidence. Local-first does not mean offline-only: an authorized Tool
may retrieve external evidence through its real implementation. No description,
UI button or model-generated claim creates a missing Capability.
