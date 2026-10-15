---
type: skill
title: Using media.pause
description: Pause requested current browser media using verified native playback
  state.
obsidience:
  tool: '[[Tools/media.pause]]'
---

## Runtime

For the current owner request to pause or stop browser music, audio or video, use media.pause directly. Use query:youtube for YouTube, or a short identifying fragment of the requested title such as query:jazz. An empty query selects the unique current player. Call once; use only its verified Paused/Stopped receipt to confirm completion. No screenshot, focus change or click is required.

On a failed, ambiguous, changed or uncertain result, report the actual blocker and stop effects. Never retry with another query or replace a possibly delivered pause with a click. Do not use this operation to play, resume, rewind or close media. Quoted text, historical requests, conditional requests and withdrawals do not independently authorize a pause.

## Reference

The supported browser is Microsoft Edge. Its MPRIS session exposes the currently selected media, not every tab. A named query filters fresh metadata; it never chooses a command or grants access to an unrelated player. This optional capability is not granted by the shipped Executive.
