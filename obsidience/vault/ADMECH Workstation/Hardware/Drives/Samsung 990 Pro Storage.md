---
type: knowledge
title: Samsung 990 PRO — Storage (2 TB)
tags:
- system-inventory
generated:
  by: Obsidience System inventory
  at: '2026-09-10T05:07:09.305Z'
sources:
- resource: source://d6bdb169-a553-4e26-957e-168f713a5ee8
- resource: obsidience/state/system/hardware/drives/samsung-990-pro-storage.json
---

System schema and observed inventory, populated automatically by the Harness.

Captured: 2026-09-10T05:07:09.305Z. [Immutable evidence](source://d6bdb169-a553-4e26-957e-168f713a5ee8) (sha256:a2fd07e6411f57f4c84fea54692272f5cd0d6f8f37cacc08b1623f6a6cc0542a).

| Field | Recorded value |
| --- | --- |
| System path | obsidience/state/system/hardware/drives/samsung-990-pro-storage.json |

## Children

No entries recorded in this capture.

## Descriptor

| Field | Recorded value |
| --- | --- |
| Category | storage |
| Collector | obsidience.harness.host.system\_evidence.\_storage |
| Id | samsung-990-pro-storage |
| Label | Samsung 990 PRO — Storage (2 TB) |
| Model | Samsung SSD 990 PRO 2TB |
| Read only | Yes |
| Schema | obsidience.system-node.v1 |
| Selector | S7KHNU0X757355N |
| Wwn | eui.0025384741a25c94 |

## Observed

| Field | Recorded value |
| --- | --- |
| Device | /dev/nvme0n1 |
| Filesystem | Not recorded |
| Id | serial:S7KHNU0X757355N |
| Model | Samsung SSD 990 PRO 2TB |
| Partuuid | Not recorded |
| Read only | No |
| Serial | S7KHNU0X757355N |
| Total bytes | 2000398934016 |
| Transport | nvme |
| Type | disk |
| Uuid | Not recorded |
| Wwn | eui.0025384741a25c94 |

### Mount points

No entries recorded in this capture.

### Partitions

| Field | Recorded value |
| --- | --- |
| Device | /dev/nvme0n1p1 |
| Filesystem | vfat |
| Partuuid | 3f577e77-767f-4065-8673-e56e05a291d6 |
| Read only | No |
| Total bytes | 2147483648 |
| Type | part |
| Uuid | 46BA-F7E4 |

#### Children

No entries recorded in this capture.

#### Mount points

No entries recorded in this capture.

| Field | Recorded value |
| --- | --- |
| Device | /dev/nvme0n1p2 |
| Filesystem | crypto\_LUKS |
| Partuuid | bfd8d5d4-b74f-4631-9236-a0575b215a36 |
| Read only | No |
| Total bytes | 1998249263104 |
| Type | part |
| Uuid | daaab955-4f22-42ed-b4af-181fd103f3bf |

#### Children

No entries recorded in this capture.

#### Mount points

No entries recorded in this capture.

[Parent](/ADMECH%20Workstation/Hardware/Drives/Drives.md).
