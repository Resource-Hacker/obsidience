---
type: skill
title: Using computer.replay
description: Answer what just happened on the screens from the rolling replay.
obsidience:
  tool: '[[Tools/computer.replay]]'
---

## Runtime

Use computer.replay when the owner asks about the recent past on screen: what just happened, what was that, what did I miss, where did something go, why did it close. Pass the owner's question as query. Set seconds only when they name a span ("the last minute" is 60) and surface only when they name a screen. Follow the returned stage instruction. The endpoint alone cannot establish earlier events; use the overview and chronological frames for those. Add or correct useful findings without repeating prior narration; SKIP is silent in progressive voice turns. Say when sampling detected no change, without claiming nothing happened between frames. For what is on screen now, use computer.observe instead.

## Reference

The replay covers at most the last 60 seconds and has no audio, so a sound or something spoken cannot be answered from it. Frames are evidence of what was shown, not of why; say what is visible and avoid inventing causes. If the replay is unavailable, report the blocker rather than retrying or substituting a current screenshot as the past.
