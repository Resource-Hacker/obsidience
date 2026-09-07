---
type: knowledge
sources:
- resource: file:///home/wissenschafter/Projects/obsidience/AGENTS.md
- resource: file:///home/wissenschafter/Projects/obsidience/DESIGN.md
title: Local-first architecture
obsidience:
  approved_at: '2026-09-07T13:00:15'
  provenance: proposed by Alexandria (task Tasks/link)
---

Obsidience is one standalone local harness with one authority for each concern.
Accepted Markdown under `obsidience/vault/` is the durable knowledge graph;
immutable external evidence lives under `obsidience/evidence/`; real code and
system records remain at their literal Source paths; SQLite records runtime
state. None is a second agent or competing knowledge authority.

The physical System inventory lives under `obsidience/state/system/` with real
Hardware, Applications, and Network branches. Checking out that exact Source
scope biases ordinary retrieval toward ADMECH Workstation Knowledge; narrower
Hardware and Applications scopes bias ADMECH Hardware and Software. Source
checkout never copies raw bytes into a Thinking Packet or grants Tool authority.

Obsidience is both the harness and the live desktop shell. One Hyprland
compositor owns every display, while one Quickshell host presents the shared
pane registry and graph across its logical Surfaces. It is not the computer,
kernel, or a System32 analogue. Linux, systemd, Wayland protocols, drivers,
filesystems, PipeWire/WirePlumber, udev, and NetworkManager remain the
underlying plumbing unless a real bounded replacement is later implemented and
accepted. The current scene contract is described by
[Hyprland shell scene](/Agents/Executive/Architecture/hyprland-shell-scene.md).

The primary target is a low-parameter model on consumer hardware. Contracts
therefore favor bounded context, closed Tool sets, stable names, exact edges,
explicit acceptance conditions, and deterministic validators. Presentation,
Task assignment, voice, and model residency do not create duplicate
loops, stores, schedulers, or mutation paths. A capability becomes active only
when its Tool binding and paired Skill validate.

## Relationships

- `implements` [Golden ontology](/Agents/Executive/Architecture/action-ontology.md) — One explicit authority owns each semantic concern.
- `implements` [LLM-wiki knowledge pattern](/Agents/Executive/Architecture/llm-wiki-knowledge-pattern--dab5ff0a.md) — Local Source, accepted Markdown, and bounded retrieval form the durable brain.
- `related_to` [Research requests](/Agents/Executive/Architecture/research-requests--7bf0113c.md) — Bounded findings use the local immutable evidence layer before Ingest can update the accepted Markdown graph.
- `related_to` [Hyprland shell scene](/Agents/Executive/Architecture/hyprland-shell-scene.md) — The scene is the local desktop observation and effect boundary.
- `related_to` [Executive model selection](/Agents/Executive/Architecture/current-executive-model--3745813a.md) — Per-Task local models remain replaceable components inside the same contracts.
