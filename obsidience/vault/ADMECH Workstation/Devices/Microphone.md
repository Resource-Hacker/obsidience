---
type: knowledge
title: Microphones
tags:
- system-inventory
generated:
  by: Obsidience System inventory
  at: '2026-09-10T05:07:09.227Z'
sources:
- resource: source://556ef9f6-f4e8-4c31-802c-a2caaee96c87
- resource: obsidience/state/system/hardware/devices/microphone.json
---

System schema and observed inventory, populated automatically by the Harness.

Captured: 2026-09-10T05:07:09.227Z. [Immutable evidence](source://556ef9f6-f4e8-4c31-802c-a2caaee96c87) (sha256:7eceebcbe020285deac6e62a20d2cf238b143e8163bf6ecd593a79f99a487f19).

| Field | Recorded value |
| --- | --- |
| System path | obsidience/state/system/hardware/devices/microphone.json |

## Children

No entries recorded in this capture.

## Descriptor

| Field | Recorded value |
| --- | --- |
| Category | device |
| Collector | obsidience.harness.realtime.media.interface\_catalog |
| Configuration | obsidience/state/media-settings.json |
| Id | microphone |
| Label | Microphones |
| Live data endpoint | /api/hardware |
| Read only | Yes |
| Schema | obsidience.system-node.v1 |
| Selector | microphone |

## Observed

| Field | Recorded value |
| --- | --- |
| Configured selection | alsa\_input.usb-Remo\_Tech\_Co.\_\_Ltd.\_OBSBOT\_Tiny\_2\_Lite-02.analog-stereo |

### Endpoints

| Device.bus path | Device.profile.name | Id | Label | Object.path |
| --- | --- | --- | --- | --- |
| pci-0000:0e:00.0-usb-0:5:1.0 | pro-input-0 | alsa\_input.usb-Logitech\_A50\_X-00.pro-input-0 | A50 X Microphone | alsa:acp:X:2:capture |
| pci-0000:0e:00.0-usb-0:5:1.0 | pro-input-1 | alsa\_input.usb-Logitech\_A50\_X-00.pro-input-1 | A50 X Stream Mix | alsa:acp:X:3:capture |
| pci-0000:0e:00.0-usb-0:2:1.2 | analog-stereo | alsa\_input.usb-Remo\_Tech\_Co.\_\_Ltd.\_OBSBOT\_Tiny\_2\_Lite-02.analog-stereo | OBSBOT Tiny 2 Lite Microphone | alsa:acp:Lite:0:capture |

[Parent](/ADMECH%20Workstation/Devices/Devices.md).
