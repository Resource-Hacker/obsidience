---
approved_at: '2026-08-21T03:38:44'
jarvis_source_citation: jarvis://claim/f26441df-73c3-4431-9050-10742e3c33db
jarvis_source_claim: f26441df-73c3-4431-9050-10742e3c33db
provenance: proposed by Codex (task owner knowledge request)
tasks:
- '[[@library/Tasks/executive]]'
title: JARVIS
---

# JARVIS

JARVIS is the user-facing executive identity. In this greenfield build,
Obsidience is its graph-native runtime: a plain Obsidian vault plus a small
interpreter. The knowledge graph drives activation and retrieval while JARVIS
coordinates the literal Alexandria, Darwin, and Heimdall agents.

Four authoring primitives — recursive Tasks, procedural Runbooks, one Skill
per Tool, and executable Tools — continue to resolve through exact wikilinks:
edges dispatch and vectors inform. Their Obsidience-native catalogs remain in
place; the legacy JARVIS Tools, Skills, Runbooks, and Tasks have deliberately
not been imported yet.

The whole system follows node → subnode → child node → article at any
meaningful depth. Tasks retain task → subtask structure where it fits; Tools,
Skills, Runbooks, and ordinary knowledge use the same recursive pattern with
their own child types. New material belongs at the narrowest fitting place in
an existing semantic hierarchy. Names stay short and human-readable instead
of flattening paths into hyphenated compound labels.

Sessions may invoke only the Tools paired with their Skills. Agents stage
proposals in `_staging/` for owner review, while approvals and immutable
receipts remain git-audited.
