---
type: knowledge
status: deprecated
title: AI Models
tags:
- system-inventory
generated:
  by: Obsidience System inventory
  at: '2026-09-10T04:33:49.801Z'
sources:
- resource: source://de822997-a621-4ae7-91a9-d69d105e4e21
- resource: obsidience/state/system/hardware/drives/system-volume/ai-models.json
obsidience:
  archived_at: '2026-09-10T05:06:53.030384+00:00'
  archive_reason: 'Owner simplified System hierarchy: physical drives are direct Articles;
    storage paths belong to Obsidience; duplicate Network wrapper removed.'
---

System schema and observed inventory, populated automatically by the Harness.

Captured: 2026-09-10T04:33:49.801Z. [Immutable evidence](source://de822997-a621-4ae7-91a9-d69d105e4e21) (sha256:ac57ddf438d8b7765b691499fb4a8b7ee8644d7f6cd0755a107ee1564512f3e3).

| Field | Recorded value |
| --- | --- |
| System path | obsidience/state/system/hardware/drives/system-volume/ai-models.json |

## Children

No entries recorded in this capture.

## Descriptor

| Field | Recorded value |
| --- | --- |
| Allocation | shared\_filesystem |
| Category | storage |
| Collector | obsidience.harness.host.inventory.storage\_snapshot |
| Id | models |
| Label | AI Models |
| Live data endpoint | /api/hardware |
| Models path | /var/lib/ai/models |
| Path | /var/lib/ai |
| Quota bytes | Not recorded |
| Read only | Yes |
| Schema | obsidience.system-node.v1 |
| Selector | models |

## Observed

| Field | Recorded value |
| --- | --- |
| Allocation | shared\_filesystem |
| Available | Yes |
| Filesystem | btrfs |
| Id | models |
| Label | AI Models |
| Mount point | /var/lib/ai |
| Path | /var/lib/ai |
| Quota bytes | Not recorded |
| Subvolume | /@ai |
| Total bytes | 850524110848 |

[Parent](/ADMECH%20Workstation/Hardware/Drives/System%20Volume/System%20Volume.md).
