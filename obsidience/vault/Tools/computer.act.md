---
type: tool
title: computer.act
obsidience:
  binding: capability:computer.act
  source: obsidience/harness/capabilities/computer/act.py
  approved_at: '2026-09-05T22:33:07'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

Apply one click at the point selected by the Task's vision model in its immediately preceding computer.observe image. Arguments:
`{"application": str, "action": "click", "target": str, "point": {"x": int, "y": int}, "postcondition": str optional}`.

Use the canonical application name or exact current app_id from the Shell Scene. `target` describes the intended control, up to 128 characters. `point` is its center on a 1000 by 1000 normalized image grid: x grows right, y grows down, and both must be integers from 0 to 999. Coordinates refer only to the complete image just attached by computer.observe, never to the desktop or another image. Labels and unlabeled icons use the same vision path. `postcondition` names the result to inspect; it cannot assert that it happened.

The Capability requires the executor's private, one-use observation lease for exactly the immediately preceding model input. An intervening Tool, invalid response, cancellation or completion discards it. The exact native image, process instance, window identity, geometry and at-most-ten-second image age are validated. The existing Shell command owner activates the exact window if necessary, maps the selected image point into that window, checks its actual pointer position and unobstructed input, and delivers one framed Wayland click. No OCR, second vision model, text-matching gate, point relocation, daemon or alternative input owner is involved.

One invocation consumes the Task's action attempt. Lost or uncertain delivery must never be replayed. A completed result verifies the delivered click and supplies a fresh exact post-image. The target label is the model's description, not independent semantic recognition. `semantic_postcondition_verified: false` means that input acknowledgement does not establish a larger outcome such as starting a match. Evaluate the post-image before reporting the visible result. Images, image points, capture leases and native identities stay private and ephemeral; they never enter durable trace, Source or Vault.
