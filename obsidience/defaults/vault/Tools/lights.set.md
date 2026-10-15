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

The capability reads this installation's exact bulb identities from the ignored local `obsidience/state/lights.json` configuration. Source and starter Articles contain fixture aliases only. Each selected bulb must freshly return its expected MAC and current power state before any group change. A bulb already in the requested state needs no mutation. Otherwise the capability sends one local WiZ power command and verifies MAC and state through a fresh readback.

Before turning a lit bulb off, the capability atomically records its verified brightness and scene or static colour in ignored local `obsidience/state/lights-appearance.json`, keyed by exact MAC. The firmware reports its static/default preset while off, losing the active scene. On restores the saved appearance for that verified MAC, or uses the fresh off-state appearance when no saved record exists. Completed ON requires both requested power and appearance readback. The saved record remains available after success or uncertainty; a later OFF of a lit bulb refreshes it from the current measured appearance. It does not invent or select a new appearance. Calls serialize through one process-owned lock.

`status:completed` establishes the requested power state for every selected light. A failed result contains per-fixture outcomes and may represent a partial change. Report those exact outcomes. `effect_applied:null` means the effect is uncertain. `must_not_replay:true` forbids automatic replay; no rollback, opposite command or retry is issued. Each fixture admits one dispatched mutation in a run; other fixtures may receive their distinct requested state in that run. A repeated selection containing an already-dispatched fixture blocks the whole selection and returns its exact prior receipt. A subsequent explicit owner request creates a fresh run.

Light control requires LAN access to the registered bulbs. It starts no service, camera, presence automation or training capture. Historical detections and camera absence never request a power change.
