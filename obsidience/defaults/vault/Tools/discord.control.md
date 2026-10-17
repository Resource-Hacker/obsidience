---
type: tool
title: discord.control
description: 'Control the Obsidience Discord Bot in its configured server. For current Discord
  audio pause/resume/stop, call this Tool with only action:pause|resume|stop. Resume continues
  the paused player; it needs no track id, media.library call, memory recall or search. Never
  replace a failed resume with search/play or restart a track. status reads connection and
  playback; channels lists current voice channel IDs. join(channel_id) connects to one exact
  channel; leave disconnects. Discord-origin actions use the admitted member identity and
  fresh channel permissions. say(text) requests speech, not verified audible delivery; ordinary
  Discord replies are spoken by their transport automatically, so do not call say for your
  own answer. play(id,media_kind:audio) starts the exact media.library selection from this
  activation as audio only. Video/Go Live is not supported: never substitute a show''s soundtrack
  for requested video without agreement. Ask which series, season and episode when unclear.
  pause/resume control current Discord media; stop cancels Discord output and pending replies
  while leaving wake listening armed. Do not claim a listener heard playback from a player-start
  receipt. Failed or uncertain effects must not be replayed. This Tool grants no desktop control,
  provider configuration or acquisition authority.'
obsidience:
  binding: capability:discord.control
  source: obsidience/harness/capabilities/discord/control.py
  owner_maintained: true
---

To pause, resume or stop current Discord audio, call `discord.control` with
only `action:pause`, `action:resume` or `action:stop`. Resume continues the
paused player and needs no track id, catalogue lookup, memory recall or search.
`media.library resume` reads saved Jellyfin progress; it does not resume this
player. Never replace a failed or uncertain resume with search, select or play,
and never restart the track to implement resume. Report the current failure;
use status only if fresh state is needed.

Music selections from `media.library search(type:music)` use the same `play`
operation. The configured route may prepare the exact public YouTube source on
TorBox before delivery; receipts distinguish pending preparation from audio
entering the Discord player. Public receipts contain neither signed CDN URLs nor
account credentials. The destination owns all decoder/provider children and
cancels only its exact playback request.

Direct YouTube playback may require a provider-reported availability wait before
the selected audio can be downloaded. `provider_wait_ms` reports that preparation
duration, not ready or playing audio. The owner allows one such wait up to 60
seconds in addition to the normal startup budget. Cancellation stops the exact
request immediately; it does not wait for the provider's delay to elapse.

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

A voice resume with `resume_pending:true` keeps the current stream at its paused
position until your normal concise reply and completion cue finish. Do not repeat
resume or issue play. `resumed:true` means the player is already Playing.
