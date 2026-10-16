---
type: tool
title: discord.control
description: 'Control the Obsidience Discord Bot in its configured server. status
  reads connection and playback; channels lists current voice channel IDs. join(channel_id)
  connects to one exact channel; leave disconnects. Discord-origin actions use the
  admitted member identity and fresh channel permissions. say(text) requests speech,
  not verified audible delivery; ordinary Discord replies are spoken by their transport
  automatically, so do not call say for your own answer. play(id,media_kind:audio)
  starts the exact media.library selection from this activation as audio only. Video/Go
  Live is not supported: never substitute a show''s soundtrack for requested video
  without agreement. Ask which series, season and episode when unclear. pause/resume
  control current Discord media; stop cancels Discord output and pending replies while
  leaving wake listening armed. Do not claim a listener heard playback from a player-start
  receipt. Failed or uncertain effects must not be replayed. This Tool grants no desktop
  control, provider configuration or acquisition authority.'
obsidience:
  binding: capability:discord.control
  source: obsidience/harness/capabilities/discord/control.py
  owner_maintained: true
---

Music selections from `media.library search(type:music)` use the same `play`
operation. The configured route may prepare the exact public YouTube source on
TorBox before delivery; receipts distinguish pending preparation from audio
entering the Discord player. Public receipts contain neither signed CDN URLs nor
account credentials. The destination owns all decoder/provider children and
cancels only its exact playback request.

The optional Discord transport owns the connection and audio players. The executing Agent
uses its granted Skill; the configured server and observed member identity remain controller
bindings, never model-selected authority. Media catalogue selection and source admission
stay with Obsidience Media. Audio playback and speech delivery report their actual receipt
level; neither claims that a listener heard the result. This interface does not send video.

For a voice-origin play, `audio_playback_ready` means the exact source has decoded
but is waiting behind your spoken announcement. Name what will play and finish
with your normal concise reply; the transport starts the track after that reply.
Do not poll, call say, or repeat play to release it. `audio_playback_started`
means the player actually started. A ready receipt is not audible playback.
