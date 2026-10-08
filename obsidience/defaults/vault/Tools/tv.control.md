---
type: tool
title: tv.control
description: Control one identity-bound television through ADB with power readback
  and fresh screen evidence.
obsidience:
  binding: capability:tv.control
  source: obsidience/harness/capabilities/tv/control.py
  owner_maintained: true
---

## Runtime

Control the one registered television using `action:on`, `off`, `observe`, `launch`, `key` or `text`. Launch also requires a registered `app` alias; key requires one `key`; text requires `text` (1-120 simple printable characters). Power actions need no other arguments. Observe returns the installed app catalog, preferred app, current power, foreground, media-session metadata and one fresh screen image. Remote keys include up/down/left/right/select/back/home/menu, play/pause/rewind/fast_forward, volume_up/volume_down/mute, enter and delete.

## Reference

Upstream Android Platform Tools ADB owns the transport. Private installation state `obsidience/state/television.json` binds one LAN address to an exact device serial and OEM model and lists installed application packages. No caller can supply an address, shell command, arbitrary package or keycode. Every call verifies identity; every effect checks it again remotely. No ADB server restart, background polling or second agent is introduced.

Power uses discrete sleep/wake keys and verifies both wakefulness and display state. Already-correct power is a verified no-op. Wake requires network reachability in standby. Only a verified power receipt establishes the requested power outcome.

Observe before each key or text action. The preceding observation expires after 60 seconds and must still match the foreground window; an action consumes it. Each action sends one command and returns a fresh image. Read the updated screen before continuing. Delivered navigation does not establish content playback. Protected video can be black; use player UI and current media metadata as available. Report uncertainty when evidence cannot establish playback.

Calls serialize and honor cancellation. Power and each application launch may be dispatched at most once per run. Uncertain or failed post-dispatch verification blocks all further effects in the run; read-only observation remains available. Never replay uncertain delivery. A later explicit owner request is a new run.

Text requires an active Android input method. Custom keyboards use visible remote-key selection. Missing observation or inactive text input returns correction_allowed:true without sending input; the Executive may observe and correct that precondition. This does not authorize retry of transport failures or uncertain effects. Navigation completion requires explicit established outcome verification.
