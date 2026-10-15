---
type: tool
title: media.pause
description: Pause one current browser media session directly, without screenshots
  or clicks. Use query:youtube for YouTube, a short title fragment such as jazz for
  named media, or an empty query for the unique current player. Only a verified Paused/Stopped
  receipt establishes success. This never resumes, toggles or rewinds playback; ambiguous
  or changed players fail without replay.
obsidience:
  binding: capability:media.pause
  source: obsidience/harness/capabilities/media/pause.py
---

## Runtime

Pause one current Microsoft Edge media session with `{"query":"youtube"}`, a short title fragment such as `{"query":"jazz"}`, or `{"query":""}` for the unique current player. The query is an optional metadata filter of at most 128 characters. This capability is available only through the Executive identity and an explicitly granted paired Skill; the shipped Executive does not grant it.

The adapter selects one current MPRIS player, verifies the fixed browser executable and process start time, and binds its unique bus owner and track identity. Already paused or stopped playback needs no mutation. Otherwise it sends exactly one Pause and requires fresh same-identity Paused/Stopped readback. This never toggles, resumes, rewinds or launches playback. An ambiguous, changed or unavailable player fails; uncertain delivery is not replayed or replaced by a click. Any failure ends effects for this activation.

## Reference

Only status:completed with delivery:verified and state:Paused|Stopped establishes pause completion. The result includes its current track identity and verification time; it needs no screenshot. A method acknowledgement alone does not establish playback state. MPRIS describes the browser-selected media session, not an arbitrary tab, and does not accept a track ID with Pause. Fresh pre/post identity checks detect changes without claiming an atomic tab-specific operation.

This is one registered capability within the existing receipt, cancellation and completion owner. It adds no browser automation session, input path, media daemon or model loop. Subsequent explicit owner requests create fresh activations.
