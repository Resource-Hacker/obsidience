---
type: skill
title: Using discord.control
description: Connect the configured Discord bot and control its own channel audio.
obsidience:
  tool: '[[Tools/discord.control]]'
  owner_maintained: true
---

To pause, resume or stop current Discord audio, call `discord.control` with
only `action:pause`, `action:resume` or `action:stop`. Resume continues the
paused player and needs no track id, catalogue lookup, memory recall or search.
`media.library resume` reads saved Jellyfin progress; it does not resume this
player. Never replace a failed or uncertain resume with search, select or play,
and never restart the track to implement resume. Report the current failure;
use status only if fresh state is needed.

Music requests use `media.library search(query,type:music)`. It returns a bound
playback id directly; call `play` with that id and `media_kind:audio`. Artist-only
requests may choose a matching official/top track. Movie/TV search does not search
music. Local music and the configured public online route share this same player.
An explicit music play request permits preparation of that exact public track
through the configured provider; it grants no account changes or torrent acquisition.
If preparation is pending, state that it has not started playing. Never repeat an
uncertain or pending effect in this activation. Pause/resume/stop keep their usual
meaning once audio starts.

Read status to establish the current connection. List channels before joining an exact
channel. Discord member requests use their observed member identity and current voice
permissions. A member cannot move the bot into somebody else's channel by supplying an ID.

Use the normal final answer for a Discord conversation: its transport owns spoken/text
delivery. Standalone say is for the Executive to address the joined channel. A speech_requested
receipt establishes a queued synthesis request, not audible completion.

For media, clarify the exact title, edition, season and episode, then browse and select
through media.library. A current-turn selection may be passed to play with media_kind: audio.
This transport does not send video: ask before substituting audio for a television episode
or film. Audio playback started means the Discord player entered Playing, not that every
listener heard it. Never disclose local source paths or authenticated content URLs.

Pause, resume and stop affect this bot's Discord output. A bot-origin stop preserves the
request which asked it to stop so its ordinary answer can complete. Leave disconnects.
An uncertain or failed effect must not be repeated; use fresh status to describe the outcome.
Additional Discord operations require their own accepted implementation and explicit grants.

For a voice-origin play, `audio_playback_ready` means the exact source has decoded
but is waiting behind your spoken announcement. Name what will play and finish
with your normal concise reply; the transport starts the track after that reply.
Do not poll, call say, or repeat play to release it. `audio_playback_started`
means the player actually started. A ready receipt is not audible playback.

A voice resume with `resume_pending:true` keeps the current stream at its paused
position until your normal concise reply and completion cue finish. Do not repeat
resume or issue play. `resumed:true` means the player is already Playing.
