---
action: create
agent: Codex
proposal: true
proposed_at: '2026-08-26T14:06:25'
reason: Verified repeat incident and bounded application-only recovery prevent unnecessary
  audio-stack changes.
rejected_at: '2026-08-26T14:06:39'
rejected_reason: rejected from review pane
review_class: article
run_id: ''
target: ADMECH Workstation/Workstation Observations/Incident/discord-pipewire-audio-helper-lifetime-mismatch.md
task: codex:knowledge-handoff
title: Discord PipeWire audio-helper lifetime mismatch
---

On 2026-08-26 Discord had remained open across a PipeWire-Pulse restart. PipeWire, WirePlumber, the A50 X endpoints, the OBSBOT microphone, motherboard line out, USB-C audio, and Samsung HDMI were healthy, but Discord had no `audio.mojom.AudioService`, no Pulse client, and its renderer enumerated only video devices. This repeated the established Chromium/PipeWire lifetime mismatch rather than an ALSA card-profile or default-device failure.

Recover only the affected application. If Discord still has an audio helper, terminate that exact stale helper and allow it to respawn. If it does not respawn or is absent, restart only `dp4-discord.service`; do not restart PipeWire, WirePlumber, change card profiles/defaults, or disturb unrelated audio clients. Verify a fresh Discord audio helper, a live Discord Pulse client, and renderer enumeration of the expected microphone and output labels before reporting success.

A Discord self-update can exit cleanly during this recovery. Because `dp4-discord.service` intentionally uses `Restart=on-failure`, a clean updater exit may leave the unit inactive and require one explicit start. On this incident, the update completed from 1.0.153 to 1.0.155, after which Discord enumerated A50 X Microphone/Stream Mix, OBSBOT, Obsidience AEC, A50 X Voice/Game, USB-C, motherboard line out, and Samsung HDMI.

The 1.0.155 voice module did not match the reviewed ultrawide native-cap signatures, so the prelaunch guard correctly selected its upstream fallback. Audio recovery does not authorize adapting that binary patch or claiming exact 5120x1440 Go Live.
