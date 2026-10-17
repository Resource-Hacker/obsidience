---
type: tool
title: lights.visualize
description: "Opt-in room music light visualizer for the Executive only. action:start requires explicit audio_delay_ms (250-3000) and uncalibrated:true unless an exact saved optical timing profile is available. Delays only one uniquely observed Discord playback stream, never system defaults or microphones. Optional stream_id must come from observed local visualizer sources. action:stop restores original routing and light appearance; action:status observes current mode. This controls colour and brightness while active. Timing profiles compensate measurements but do not establish perfect physical synchronization; do not claim calibrated or audible alignment from running state. Never replay failed/uncertain effects."
obsidience:
  binding: capability:lights.visualize
  source: obsidience/harness/capabilities/lights/visualize.py
---

## Runtime

Only the Executive conversation may use this optional Tool through its explicitly
granted paired Skill. It is not granted by the starter Executive and never grants
Discord members access to workstation lighting.

Use `{"action":"status"}`, `{"action":"stop"}`, or an explicit opt-in start such as
`{"action":"start","audio_delay_ms":500,"uncalibrated":true}`. The delay is an
intentional audio buffering choice, not a measured hardware latency. Without an
exact saved timing profile, `uncalibrated:true` is required. The default source is
one unique currently playing native Discord stream; ambiguity fails. Optional
`stream_id` must be an observed current output stream. It must have one observed
physical ALSA output. The selected stream is a mix: other Discord members can
be present in that audio. This Tool does not identify music by speaker or content.

The owner-local API exposes GET `/api/lights/visualizer`, GET
`/api/lights/visualizer/sources`, and POST `/api/lights/visualizer` with the same
start/stop/status actions. Only this local API accepts an explicit `calibration`
object; model arguments never carry private bulb identities or camera bindings.

The session snapshots all six verified bulb identities and exact power/appearance,
then owns their existing control lock. Native PipeWire supplies one temporary
sink, a delayed `pw-loopback` to the original physical output, and an in-memory
`pw-record` analysis tap. Defaults and microphone routes never change. The exact
stream node/serial, client PID/start identity and output serial must remain current.
A changed stream/output/route or dependency loss ends the session. Stop drains
in-flight colour frames, restores prior target metadata including absence, removes
owned audio resources, and restores each touched bulb once with fresh readback.
Restoration failures are reported and never silently retried. Ordinary `lights.set`
preempts and drains the visualizer before a power operation.

Envelope and three spectral bands drive RGB and brightness at up to 10 updates
per second per fixture. A bounded feature history supplies audio lookahead; each
fixture has at most one in-flight UDP update, with no queued obsolete writes.
Source PCM never reaches disk, conversations, Knowledge or Memory.

Running state proves local resource acquisition and PCM arrival, not that a person
heard audio or saw aligned lights. `calibrated` stays false; a supplied profile is
labelled `owner_profile_supplied`, not independently verified. Camera exposure,
firmware ramps, Wi-Fi jitter, 100 ms analysis/control granularity and physical
headphone delay limit timing precision. Do not promise perfect synchronization.

## Timing profile seam

The fixed ignored private file is `obsidience/state/lights-visualizer-calibration.json`
(`CONFIG.runtime_dir / "lights-visualizer-calibration.json"`), at most 32 KiB. Start
loads it unless explicit uncalibrated mode is selected. The visualizer never
creates measured defaults or writes a profile. The local calibration owner writes
it atomically after real optical/audio measurement.

Version 1 requires exactly:

- `version:1`, bounded `profile_id`, and Unix-seconds `measured_at`;
- exact current `stream_serial`, `output_serial`, and `sink_name`;
- nonempty bounded `camera_binding` provenance object;
- `requested_audio_delay_ms` matching the start request;
- `native_audio_delay_ms`, the measured digital input-monitor to output-monitor lag;
- `capture_latency_ms` for the analysis tap and `output_latency_ms` for any measured
  monitor-to-physical-output offset;
- `fixtures`, with exactly all six registered aliases, each carrying the exact
  `mac`, measured optical `latency_ms`, and measured `uncertainty_ms`.

The measured digital delay must cover every fixture's optical delay, uncertainty,
capture delay and a 150 ms analysis/control margin. Profiles bind current runtime
serials and fail when those identities change. A zero physical output offset is
not proof that wireless/headphone latency is zero; the status explicitly retains
`physical_output_delay_verified:false`. Calibration measurement and recording are
separate explicitly authorized operations, not started by this Tool.
