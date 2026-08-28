---
approved_at: '2026-08-28T06:58:13'
kind: knowledge
provenance: proposed by Codex (task codex:knowledge-handoff)
sources:
- AGENTS.md
- DESIGN.md
title: Local-first architecture
---

Obsidience is a standalone local harness with one authority for each concern.
The accepted Markdown under `obsidience/vault/` is the durable knowledge graph,
`obsidience/evidence/` is the immutable raw-source area, and the Source explorer
is the read-only view over real files and system records.

The physical System inventory lives under `obsidience/state/system/`. Its real
branches are `hardware/`, `applications/`, and `network/`. Hardware contains
Compute, Drives, and Devices. Drives exposes the actual files beneath each
recorded volume: Obsidience's project files remain at their exact paths and AI
model weights remain in their external model store with bounded Source
manifests. Applications records installed or deliberately not-yet-integrated
software. The current entries identify Obsidience and the external web-browser
boundary. Every Source leaf retains its exact path and bytes; private `@view/`
keys only stabilize UI identity and never manufacture a Source object or become
an ontology kind.

Checking out exact `obsidience/state/system` supplies the accepted ADMECH
Workstation branch through ordinary retrieval. A Hardware subtree narrows that
priority to ADMECH Hardware, and an Applications subtree narrows it to ADMECH
Software. Source checkout never attaches raw bytes, grants Tool authority, or
creates a second knowledge graph.

The Obsidience directory is backed by `/home`, while `/var/lib/ai` is Models
storage. `/home` and `/var/lib/ai` are separate Btrfs subvolume mounts on the
same filesystem and share one free-space pool; Obsidience has no dedicated
partition or quota.

Obsidience is the harness and developing desktop shell/application environment.
Its first replacement target is `plasmashell`; KWin remains the compositor
boundary. It is not the computer, kernel, or a System32 analogue. Linux,
systemd, KWin protocols, drivers, filesystems, PipeWire/WirePlumber, udev, and
NetworkManager remain the underlying plumbing unless a real bounded replacement
is later implemented and accepted.

The primary target is a low-parameter model on consumer hardware. Contracts
therefore favor small bounded contexts, closed Tool sets, stable names, exact
edges, explicit acceptance conditions, and deterministic validators. A larger
or remote model may be configured, but the architecture must never depend on
its broad latent knowledge.

Presentation, Library checkout, Tasks, agent identities, and voice do not create
duplicate model loops, memory stores, schedulers, or mutation paths. A capability
becomes active only when a real Tool binding and its paired Skill validate.

## Relationships

- `related_to` [[Agents/Executive/Executive|Executive]] - Executive is the user-facing role of the local runtime.
- `implements` [[Agents/Executive/Architecture/activation-briefing-protocol--21d7f1ad|Activation packet protocol]] - Bounded activation makes local small-model execution practical.
- `implements` [[Agents/Executive/Architecture/task-activation--b30a4642|Task activation]] - Task activation is where the architecture's exact-edge contract is realized: a capability is active only when its Tool binding and paired Skill resolve and validate.
- `implements` [[Agents/Executive/Architecture/llm-wiki-knowledge-pattern--dab5ff0a|LLM-wiki knowledge pattern]] - The accepted Markdown vault, immutable Source, exact-edge capability activation, and low-parameter local target realize the wiki's maintenance and retrieval pattern.
