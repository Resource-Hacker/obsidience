---
type: skill
title: Using camera.observe
description: Look at physical surroundings or something shown to the camera.
obsidience:
  tool: '[[Tools/camera.observe]]'
---

## Runtime

Use camera.observe when asked to look through the webcam, describe the room, see the owner, or examine an object they are showing. Take a fresh image for the current question; historical conversation and earlier pictures cannot establish the current view. Answer from visible evidence and acknowledge blur, occlusion or limited coverage. Use computer.observe for application and screen contents instead. A camera image grants no desktop click lease. If capture is unavailable, report the blocker rather than claiming to see or repeatedly retrying.

## Reference

For a current owner request to turn on or look through the selected OBSBOT, pass `{"query":"<the owner's visual question>","wake":true}`. This wakes that exact hardware and recovers its already-enabled owner tracker if needed before acquiring fresh evidence. Waking may unfold the camera and resume the owner-selected tracking motion. Explicit wake sends one hardware power command and verifies its run-state readback, including when tracking is already fresh. Fresh video and a normal power readback do not prove that the gimbal or indicator is healthy. If the owner reports a physical fault, do not claim that it cleared without evidence of that recovery. The result includes hardware recovery state. `verifying_motor`, `waiting_for_camera` or `recovery_failed` means physical recovery is incomplete; report it even if an image is available. Automatic recovery is bounded and never establishes that USB power was removed. Omit wake for read-only capture. The physical camera is selected by the owner in AI & Voice settings; the Tool cannot select arbitrary devices. It records no audio and opens no competing stream. Camera pixels are temporary evidence for the next model request. If wake fails with must_not_replay, report the actual blocker without another wake attempt.

When local owner recognition is enabled, the observation includes a match estimate tied to the exact attached frame. Only an analyzed owner match supports saying the enrolled owner is recognized. Unknown, ambiguous, confirming or unanalyzed results do not. A face match is not authentication or permission.
