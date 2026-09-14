---
type: skill
title: Using computer.act
description: Choose the intended control from the immediately preceding image.
obsidience:
  tool: '[[Tools/computer.act]]'
  requires:
  - '[[Skills/computer.observe]]'
---

## Runtime

Choose the intended control from the immediately preceding image. Coordinates are normalized image coordinates, not desktop pixels. Declare scope:input for one requested click or scope:state for a requested application result. The first action fixes scope for this run. Interpret each fresh post-image before claiming a state or taking another distinct step. Never repeat an uncertain click.

Only geometry_changed_before_input with correction_allowed:true permits one new computer.observe and a newly chosen point before any input. The old point is consumed; a second geometry change fails. All other input failures end the sequence. For input scope, an acknowledged intended click with its fresh post-image satisfies the requested input; report application state separately.

## Reference

Use computer.act for one bounded click inside the application bound by the current Task.

- Pass `{"scope": "input|state", "application": str, "action": "click", "target": str, "point": {"x": int, "y": int}, "postcondition": str optional}`. Use the canonical application name or exact app_id from the Shell Scene. Describe the intended control in target.
- Select the center of that control from the immediately attached image. Express its position on a 1000 by 1000 grid covering the whole image: x is left-to-right and y is top-to-bottom. Both are integers 0-999. For example, the image center is {"x": 500, "y": 500}. Read text and icons directly with vision; never invent desktop coordinates, element indices or capture tokens.
- The image must come from the immediately preceding successful computer.observe of this application. Any intervening Tool or invalid response discards the private action lease. Do not act from memory or an older image. If the intended control is unclear, finish with that limitation without clicking.
- The Capability validates the same image/window, handles foreground activation if needed, maps the point, delivers one click and captures the result. Input scope permits one attempt. State scope permits at most three distinct steps only when fresh images establish each preceding result. Every later step requires a separate newer computer.observe immediately before action. Except for the explicit one-time pre-input geometry correction above, any failed precondition, rejected or uncertain delivery, or unavailable post-image ends the sequence; never retry it.
- A completed result with verified_scope: click establishes delivery at your selected point plus a fresh post-image. Inspect that image before describing the result. A mode-selection screen is not a started match; a target label or requested postcondition is not evidence by itself.
- Stop on missing or ambiguous application, expired image, changed identity or geometry, sleeping Surface, lock, cancellation, rejected or uncertain delivery, or unavailable post-image. Report the specific blocker without changing input paths or repeating the click.
