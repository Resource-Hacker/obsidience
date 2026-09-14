---
type: tool
title: computer.act
description: Deliver one click to the immediately observed application.
obsidience:
  binding: capability:computer.act
  source: obsidience/harness/capabilities/computer/act.py
---

## Runtime

Deliver one click to the immediately observed application. Pass scope:input|state, application, target description, point:{x,y} with integer coordinates 0..999, and optional postcondition. A fresh computer.observe must immediately precede this call. The result can attest click delivery and return a fresh post-image, not mechanically prove the semantic goal. Never repeat uncertain delivery. State outcomes allow at most three verified distinct steps.

Only geometry_changed_before_input with correction_allowed:true permits one new computer.observe and a newly chosen point before any input. The old point is consumed; a second geometry change fails. All other input failures end the sequence. For input scope, an acknowledged intended click with its fresh post-image satisfies the requested input; report application state separately.

## Reference

Apply one click at the point selected by the Task's vision model in its immediately preceding computer.observe image. Arguments:
`{"scope": "input|state", "application": str, "action": "click", "target": str, "point": {"x": int, "y": int}, "postcondition": str optional}`.

Use the canonical application name or exact current app_id from the Shell Scene. `target` describes the intended control, up to 128 characters. `point` is its center on a 1000 by 1000 normalized image grid: x grows right, y grows down, and both must be integers from 0 to 999. Coordinates refer only to the complete image just attached by computer.observe, never to the desktop or another image. Labels and unlabeled icons use the same vision path. `postcondition` names the result to inspect; it cannot assert that it happened.

The Capability requires the executor's private, one-use observation lease for exactly the immediately preceding model input. An intervening Tool, invalid response, cancellation or completion discards it. The exact native image, process instance, window identity, geometry and at-most-ten-second image age are validated. The existing Shell command owner activates the exact window if necessary, maps the selected image point into that window, checks its actual pointer position and unobstructed input, and delivers one framed Wayland click. No OCR, second vision model, text-matching gate, point relocation, daemon or alternative input owner is involved.

Each invocation consumes its image lease. The sole attempt-count exception is the explicit one-time geometry_changed_before_input correction, which dispatches nothing and requires a new image and point. Otherwise each invocation consumes one action attempt. Input scope permits one attempt. State scope permits at most three distinct steps, each requiring a new computer.observe after the preceding acknowledged click and fresh post-image. Except for that explicit pre-input geometry correction, any failed, rejected, uncertain or post-image-missing attempt ends that action sequence. The post-image never mints another action lease. Lost or uncertain delivery must never be replayed. A completed result verifies the delivered click and supplies a fresh exact post-image. The target label is the model's description, not independent semantic recognition. `semantic_postcondition_verified: false` means that input acknowledgement does not establish a larger outcome such as starting a match. Evaluate the post-image before reporting the visible result. Images, image points, capture leases and native identities stay private and ephemeral; they never enter durable trace, Source or Vault.
