---
type: skill
title: Using lights.visualize
description: Enable or stop the owner-requested room music light visualizer with explicit
  audio delay and honest timing status.
obsidience:
  tool: '[[Tools/lights.visualize]]'
---

## Runtime

Use only for a current owner request to visualize music on the registered lights.
For start, choose the owner-authorized audio delay and call `lights.visualize`
once with `action:start` and `audio_delay_ms`. If no exact saved measurement profile
exists, explicitly use `uncalibrated:true`; describe this as an uncalibrated mode,
not a measurement. Default selection requires one unique playing Discord stream.
If source selection is ambiguous, report it and let the owner choose an observed
stream rather than guessing another output. The selected Discord output is a mix,
so other members' audio can affect the animation and share its delay.

Use `action:status` to report current resource/timing state. Use `action:stop` to
end the mode, restore original stream routing and prior light power/appearance.
Report failed or uncertain restoration exactly. Never retry an uncertain start or
restore, claim perfect synchronization, change system defaults or microphones,
load a model, or treat ambient room activity as permission to start.

## Reference

This optional Skill is Executive-only and requires an explicit local grant.
Calibration uses real flash/audio observations through their existing owners;
this Tool does not perform calibration or acquire a camera. A supplied historical
profile does not independently prove current physical timing. `lights.set` owns
ordinary power commands and stops the visualizer before acting.
