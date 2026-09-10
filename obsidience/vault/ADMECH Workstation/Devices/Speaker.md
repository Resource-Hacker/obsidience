---
type: knowledge
title: Speakers
tags:
- system-inventory
generated:
  by: Obsidience System inventory
  at: '2026-09-10T05:07:09.246Z'
sources:
- resource: source://bc457a79-17c9-4c8e-8b73-93dbbf373c0d
- resource: obsidience/state/system/hardware/devices/speaker.json
---

System schema and observed inventory, populated automatically by the Harness.

Captured: 2026-09-10T05:07:09.246Z. [Immutable evidence](source://bc457a79-17c9-4c8e-8b73-93dbbf373c0d) (sha256:0dc2c08faaeef5ed9d0816c7b2c8e44bc725cebbe9367edba0c35af44563310f).

| Field | Recorded value |
| --- | --- |
| System path | obsidience/state/system/hardware/devices/speaker.json |

## Children

No entries recorded in this capture.

## Descriptor

| Field | Recorded value |
| --- | --- |
| Category | device |
| Collector | obsidience.harness.realtime.media.interface\_catalog |
| Configuration | obsidience/state/media-settings.json |
| Id | speaker |
| Label | Speakers |
| Live data endpoint | /api/hardware |
| Read only | Yes |
| Schema | obsidience.system-node.v1 |
| Selector | speaker |

## Observed

| Field | Recorded value |
| --- | --- |
| Configured selection | alsa\_output.pci-0000\_7a\_00.6.analog-stereo |

### Endpoints

| Device.bus path | Device.profile.name | Id | Label | Object.path |
| --- | --- | --- | --- | --- |
| pci-0000:01:00.1 | hdmi-stereo | alsa\_output.pci-0000\_01\_00.1.hdmi-stereo | Samsung Odyssey G9 (RTX 4080 HDMI) | alsa:acp:NVidia\_1:4:playback |
| pci-0000:7a:00.1 | hdmi-stereo-extra2 | alsa\_output.pci-0000\_7a\_00.1.hdmi-stereo-extra2 | USB-C Monitor (AMD DisplayPort) | alsa:acp:Generic:9:playback |
| pci-0000:7a:00.6 | analog-stereo | alsa\_output.pci-0000\_7a\_00.6.analog-stereo | Motherboard Line Out (Realtek ALC1220) | alsa:acp:Generic\_1:4:playback |
| pci-0000:0e:00.0-usb-0:5:1.0 | pro-output-0 | alsa\_output.usb-Logitech\_A50\_X-00.pro-output-0 | A50 X Voice | alsa:acp:X:0:playback |
| pci-0000:0e:00.0-usb-0:5:1.0 | pro-output-1 | alsa\_output.usb-Logitech\_A50\_X-00.pro-output-1 | A50 X Game | alsa:acp:X:1:playback |

[Parent](/ADMECH%20Workstation/Devices/Devices.md).
