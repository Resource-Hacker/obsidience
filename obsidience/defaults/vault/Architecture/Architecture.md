---
type: knowledge
title: Architecture
sources:
- resource: DESIGN.md
- resource: obsidience/harness/interfaces/api/app.py
- resource: obsidience/shell/qml/shell.qml
- resource: obsidience/media/README.md
- resource: obsidience/tv/host/README.md
- resource: obsidience/lights/README.md
- resource: docs/modules/home.md
---

Architecture explains the design of this Obsidience environment. It is shared
implementation knowledge, separate from Agent identities, the owner's project
records, generated System inventory and accepted workstation operating policies.

Obsidience has four Modules, its top-level product components. This is the one
place they are listed. A Module is neither an Agent, a Task assignment, nor an
additional runtime authority.

- [Harness](/Architecture/Harness/Harness.md) (`obsidience/harness/`): ontology,
  activation, retrieval, model selection, conversation memory, speech ingress,
  research, publication and the capabilities behind every Tool.
- [Shell](/Architecture/Shell/Shell.md) (`obsidience/shell/`): compositor and native
  surface ownership, desktop scene targeting and panes. Its renderer is the shared
  React/Three.js graph bundle in `obsidience/ui/`, and its Edge Cast client (the
  browser extension, native messaging host and theme policy) is in
  `obsidience/browser/edge/`.
- [Media](/Architecture/Media/Media.md): the independent catalogue, discovery,
  exact-source acquisition, content playback/delivery and progress product. Units
  and providers live in `obsidience/media/`; Harness adapters own no second media
  database. The existing `obsidience/tv/host/` is its workstation delivery route.
- [Home](/Architecture/Home/Home.md): lights and physical-device identity,
  commissioning, state, power, volume and remote control. Existing implementations
  live in `obsidience/lights/`, Harness device adapters and the TV agent in
  `obsidience/tv/firetv-agent/`. Media consumes the TV as an optional device;
  `tv.control` currently composes content and device operations.

These Articles describe the implementation, not live state. Current application
and device inventory belongs in the local System inventory;
window state, model residency and execution outcomes come from their current
runtime interfaces. The source files cited by each Article are the basis for
architecture claims. Read the narrowest relevant child before acting.

[Cordis composition](/Architecture/Harness/cordis-composition.md) is the standing design for new work across these product boundaries. Service contracts, declared dependencies and owned cleanup compose implementations without introducing another Agent, Article type or authority.
