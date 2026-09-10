---
type: knowledge
title: Obsidience
tags:
- system-inventory
generated:
  by: Obsidience System inventory
  at: '2026-09-10T23:35:19.792Z'
sources:
- resource: source://edad6a6f-e65f-4ea8-9043-f8afad3647a4
- resource: obsidience/state/system/applications/obsidience/application.json
- resource: obsidience/state/system/applications/obsidience/model-assignments.json
- resource: obsidience/state/system/applications/obsidience/speech-runtime.json
---

System schema and observed inventory, populated automatically by the Harness.

Captured: 2026-09-10T23:35:19.792Z. [Immutable evidence](source://edad6a6f-e65f-4ea8-9043-f8afad3647a4) (sha256:404868944cb6f50e9ffb78ed4db46aaadf5e03051a72698b556ae497057d3117).

| Field | Recorded value |
| --- | --- |
| System path | obsidience/state/system/applications/obsidience/application.json |

## Children

No entries recorded in this capture.

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

## Details

### Model-assignments

| Field | Recorded value |
| --- | --- |
| System path | obsidience/state/system/applications/obsidience/model-assignments.json |

#### Descriptor

| Field | Recorded value |
| --- | --- |
| Category | application-runtime |
| Collector | obsidience.harness.models.runtime.settings |
| Configuration | obsidience/state/model-settings.json |
| Id | hardware-assignments |
| Label | Hardware assignments |
| Live data endpoint | /api/hardware |
| Read only | Yes |
| Schema | obsidience.system-node.v1 |
| Selector | hardware |

#### Observed

##### Hardware assignments

| Field | Recorded value |
| --- | --- |
| Amd-igpu | display-media |
| Cpu | none |
| Rtx4000 | obsidience-gemma |
| Rtx4080 | omniparser |

### Speech-runtime

| Field | Recorded value |
| --- | --- |
| System path | obsidience/state/system/applications/obsidience/speech-runtime.json |

#### Descriptor

| Field | Recorded value |
| --- | --- |
| Category | application-runtime |
| Collector | obsidience.harness.realtime.media.speech\_runtime |
| Configuration | obsidience/state/media-settings.json |
| Id | speech-runtime |
| Label | Realtime speech runtime |
| Live data endpoint | /api/realtime |
| Read only | Yes |
| Schema | obsidience.system-node.v1 |

#### Observed

##### Media selections

| Field | Recorded value |
| --- | --- |
| Camera | v4l2:/dev/video0 |
| Microphone | alsa\_input.usb-Remo\_Tech\_Co.\_\_Ltd.\_OBSBOT\_Tiny\_2\_Lite-02.analog-stereo |
| Speaker | alsa\_output.pci-0000\_7a\_00.6.analog-stereo |
| Tts voice | hal |

##### Speech

| Field | Recorded value |
| --- | --- |
| Asr | Nemotron Speech Streaming EN 0.6B |
| Asr chunk ms | 160 |
| Asr device | RTX 4080 SUPER |
| Transport | Pipecat LocalAudioTransport 0.0.98 |
| Tts | Pocket TTS 3.0.2 |
| Tts device | CPU |
| Turn taking | NVIDIA NeMo Voice Agent |
| Voice | hal |

## Observed

### Storage locations

| Allocation | Available | Filesystem | Id | Label | Mount point | Path | Quota bytes | Subvolume | Total bytes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| shared\_filesystem | Yes | btrfs | models | AI Models | /var/lib/ai | /var/lib/ai | Not recorded | /@ai | 850524110848 |
| shared\_filesystem | Yes | btrfs | obsidience | Obsidience | /home | /home/wissenschafter/Projects/obsidience/obsidience | Not recorded | /@home | 850524110848 |

[Parent](/ADMECH%20Workstation/Applications/Applications.md).
