---
type: knowledge
title: Crucial T705 (1 TB)
tags:
- system-inventory
generated:
  by: Obsidience System inventory
  at: '2026-09-10T05:07:09.265Z'
sources:
- resource: source://99d3caaa-55fb-4dd3-a7b1-29b1a6ed7a02
- resource: obsidience/state/system/hardware/drives/crucial-t705.json
---

System schema and observed inventory, populated automatically by the Harness.

Captured: 2026-09-10T05:07:09.265Z. [Immutable evidence](source://99d3caaa-55fb-4dd3-a7b1-29b1a6ed7a02) (sha256:34c7dec1cb3f6862a5c14356150805833e0063024aa4ddc40c03fcfef2a90157).

| Field | Recorded value |
| --- | --- |
| System path | obsidience/state/system/hardware/drives/crucial-t705.json |

## Children

No entries recorded in this capture.

## Descriptor

| Field | Recorded value |
| --- | --- |
| Category | storage |
| Collector | obsidience.harness.host.system\_evidence.\_storage |
| Id | crucial-t705 |
| Label | Crucial T705 (1 TB) |
| Model | CT1000T705SSD5 |
| Read only | Yes |
| Schema | obsidience.system-node.v1 |
| Selector | 2407E897AB30 |
| Wwn | uuid.e6533516-bf6a-44b3-a940-c039b54f34dd |

## Observed

| Field | Recorded value |
| --- | --- |
| Device | /dev/nvme1n1 |
| Filesystem | Not recorded |
| Id | serial:2407E897AB30 |
| Model | CT1000T705SSD5 |
| Partuuid | Not recorded |
| Read only | No |
| Serial | 2407E897AB30 |
| Total bytes | 1000204886016 |
| Transport | nvme |
| Type | disk |
| Uuid | Not recorded |
| Wwn | uuid.e6533516-bf6a-44b3-a940-c039b54f34dd |

### Mount points

No entries recorded in this capture.

### Partitions

| Field | Recorded value |
| --- | --- |
| Device | /dev/nvme1n1p5 |
| Filesystem | vfat |
| Partuuid | 375b447c-3dd1-45fb-82ff-9566a552b1a9 |
| Read only | No |
| Total bytes | 4294967296 |
| Type | part |
| Uuid | EC8E-A0CE |

#### Children

No entries recorded in this capture.

#### Mount points

- /boot

| Field | Recorded value |
| --- | --- |
| Device | /dev/nvme1n1p6 |
| Filesystem | btrfs |
| Partuuid | 4bf4c850-dc21-4081-bad4-ae22e92a7153 |
| Read only | No |
| Total bytes | 145384742400 |
| Type | part |
| Uuid | 0cbf0767-9b72-46eb-a047-95935da1b026 |

#### Children

No entries recorded in this capture.

#### Mount points

- /

- /root

- /srv

- /var/cache

- /var/log

- /var/tmp

| Field | Recorded value |
| --- | --- |
| Device | /dev/nvme1n1p1 |
| Filesystem | btrfs |
| Partuuid | fa0423ab-5506-42a5-81d4-b92b65864706 |
| Read only | No |
| Total bytes | 850524110848 |
| Type | part |
| Uuid | cb5a5847-fb25-4bb4-803f-19b12e59501a |

#### Children

No entries recorded in this capture.

#### Mount points

- /home

- /var/lib/ai

[Parent](/ADMECH%20Workstation/Drives/Drives.md).
