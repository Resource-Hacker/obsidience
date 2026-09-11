---
type: knowledge
title: Architecture
sources:
- resource: DESIGN.md
- resource: obsidience/harness/interfaces/api/app.py
- resource: obsidience/shell/qml/shell.qml
obsidience:
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
  approved_at: '2026-09-10T23:49:22.333585+00:00'
---

Obsidience has two cooperating product boundaries. The Harness turns accepted
knowledge and work definitions into bounded, evidenced execution. The Shell
presents the desktop and exposes observed state and explicit computer effects.
Neither branch is an Agent, Task assignment, or additional runtime authority.

- [Harness](/Agents/Executive/Architecture/Harness/Harness.md): ontology, activation, retrieval, model selection,
  conversation memory, speech ingress, research and publication.
- [Shell](/Agents/Executive/Architecture/Shell/Shell.md): compositor and native surface ownership, desktop scene
  targeting, panes, and the shared knowledge-graph renderer.

These Articles describe the implementation, not live state. Current application
and device inventory belongs in [System](/ADMECH%20Workstation/ADMECH%20Workstation.md);
window state, model residency and execution outcomes come from their current
runtime interfaces. The source files cited by each Article are the basis for
architecture claims. Read the narrowest relevant child before acting.
