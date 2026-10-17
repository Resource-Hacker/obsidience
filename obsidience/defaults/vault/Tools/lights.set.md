---
type: tool
title: lights.set
description: Turn the registered room lights on or off. Use target:all for the lights
  collectively, or window_lamp, woven_pendant, north_lamp, tv_floor_lamp, desk_lantern,
  room_lantern for a named fixture; state:on|off. Execute for the current owner request
  and confirm only verified readback. Never replay failed or uncertain changes.
obsidience:
  binding: capability:lights.set
  source: obsidience/harness/capabilities/lights/set.py
---

## Runtime

Set light power with exactly `{"target":"all","state":"on"}` or `{"target":"all","state":"off"}`. Targets are `all`, `window_lamp`, `woven_pendant`, `north_lamp`, `tv_floor_lamp`, `desk_lantern`, and `room_lantern`. Only the Executive conversation can use this capability, through an explicitly granted paired Skill. The shipped Executive does not grant it; enable it only after the local owner registers the bulbs and chooses this behavior.

## Reference

The capability reaches the installation's sole native Matter controller through a private Unix socket. Commissioned peers are bound to the registered fixture aliases. Each selected light must return a fresh Matter state, including node ID and endpoint, before any group change. Every write carries that exact binding. An uncommissioned or unavailable fixture blocks the selected group before writes; there is no WiZ fallback.

A bulb already in the requested state needs no mutation. Otherwise the capability sends a native On/Off command and verifies fresh power and unchanged native level/color attributes. Native Matter state remains in the controller; the capability adds no appearance cache or second device owner. Operations serialize with the existing visualizer lock and controller per-fixture lanes. Command acknowledgment is distinct from readback and physical illumination.

`status:completed` establishes the requested power state for every selected light. A failed result contains per-fixture outcomes and may represent a partial change. Report those exact outcomes. `effect_applied:null` means the effect is uncertain. `must_not_replay:true` forbids automatic replay; no rollback, opposite command or retry is issued. Each fixture admits one dispatched mutation in a run; other fixtures may receive their distinct requested state in that run. A repeated selection containing an already-dispatched fixture blocks the whole selection and returns its exact prior receipt. A subsequent explicit owner request creates a fresh run.

Light control requires the running local Matter controller and commissioned bulbs reachable on the LAN. It starts no service, camera, presence automation or training capture. Historical detections and camera absence never request a power change.
