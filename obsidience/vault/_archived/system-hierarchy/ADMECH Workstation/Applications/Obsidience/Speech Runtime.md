---
type: knowledge
status: deprecated
title: Realtime speech runtime
tags:
- system-inventory
generated:
  by: Obsidience System inventory
  at: '2026-09-10T04:33:49.654Z'
sources:
- resource: source://b2d80e18-3e80-4c19-a1e4-d664fb853e7f
- resource: obsidience/state/system/applications/obsidience/speech-runtime.json
obsidience:
  superseded_by: '[[ADMECH Workstation/Applications/Obsidience]]'
  archived_at: '2026-09-10T23:35:15.819811+00:00'
  archive_reason: System hierarchy simplified; details retained in the successor Article
    and immutable Source.
---

System schema and observed inventory, populated automatically by the Harness.

Captured: 2026-09-10T04:33:49.654Z. [Immutable evidence](source://b2d80e18-3e80-4c19-a1e4-d664fb853e7f) (sha256:824608390d1ec512b0eddf87cea48f906d33486b8ca230986d607c187cc3d2bd).

| Field | Recorded value |
| --- | --- |
| System path | obsidience/state/system/applications/obsidience/speech-runtime.json |

## Children

No entries recorded in this capture.

## Descriptor

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

## Observed

### Media selections

| Field | Recorded value |
| --- | --- |
| Camera | v4l2:/dev/video0 |
| Microphone | alsa\_input.usb-Remo\_Tech\_Co.\_\_Ltd.\_OBSBOT\_Tiny\_2\_Lite-02.analog-stereo |
| Speaker | alsa\_output.pci-0000\_7a\_00.6.analog-stereo |
| Tts voice | hal |

### Speech

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

[Parent](/ADMECH%20Workstation/Applications/Obsidience/Obsidience.md).
