---
type: skill
title: Using discord.control
description: Connect the configured Discord bot and control its own channel audio.
obsidience:
  tool: '[[Tools/discord.control]]'
  owner_maintained: true
---

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
