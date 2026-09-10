---
type: knowledge
title: Obsidience
tags:
- system-inventory
generated:
  by: Obsidience System inventory
  at: '2026-09-10T05:07:09.101Z'
sources:
- resource: source://17f5f472-8fc5-441a-9877-ba2eaf9a0c74
- resource: obsidience/state/system/applications/obsidience/application.json
---

System schema and observed inventory, populated automatically by the Harness.

Captured: 2026-09-10T05:07:09.101Z. [Immutable evidence](source://17f5f472-8fc5-441a-9877-ba2eaf9a0c74) (sha256:cabddf4819300d5192f0e682150fd99b42d14d4b4c03d7e4780ae7df61c43c15).

| Field | Recorded value |
| --- | --- |
| System path | obsidience/state/system/applications/obsidience/application.json |

## Children

| Ref | Title |
| --- | --- |
| ADMECH Workstation/Applications/Obsidience/Model Assignments | Hardware assignments |
| ADMECH Workstation/Applications/Obsidience/Speech Runtime | Realtime speech runtime |

## Descriptor

| Field | Recorded value |
| --- | --- |
| Category | application |
| Collector | obsidience.harness.host.inventory.application\_snapshot |
| Compositor boundary | Hyprland |
| Description | Graph-native local-agent harness and modular Hyprland desktop shell |
| Id | obsidience |
| Label | Obsidience |
| Live data endpoint | /api/system |
| Project path | obsidience |
| Read only | Yes |
| Role | desktop-shell |
| Schema | obsidience.system-node.v1 |
| Selector | obsidience |
| Service | obsidience-shell-host.service |
| State | development |
| Surface contract | obsidience.surface.v1 |

### Components

| Field | Recorded value |
| --- | --- |
| Harness | obsidience-harness-dev.service |
| Knowledge | obsidience-shell-knowledge.service |
| Notifications | obsidience-shell-notifications.service |
| Session | obsidience-shell-session.target |
| Shell | obsidience-shell-host.service |
| Software management | PackageKit (alpm) |

### Storage locations

| Allocation | Id | Label | Models path | Path | Quota bytes |
| --- | --- | --- | --- | --- | --- |
| shared\_filesystem | models | AI Models | /var/lib/ai/models | /var/lib/ai | Not recorded |
| shared\_filesystem | obsidience | Obsidience | Not recorded | /home/wissenschafter/Projects/obsidience/obsidience | Not recorded |

## Observed

### Storage locations

| Allocation | Available | Filesystem | Id | Label | Mount point | Path | Quota bytes | Subvolume | Total bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| shared\_filesystem | Yes | btrfs | models | AI Models | /var/lib/ai | /var/lib/ai | Not recorded | /@ai | 850524110848 |
| shared\_filesystem | Yes | btrfs | obsidience | Obsidience | /home | /home/wissenschafter/Projects/obsidience/obsidience | Not recorded | /@home | 850524110848 |

[Parent](/ADMECH%20Workstation/Applications/Applications.md).
