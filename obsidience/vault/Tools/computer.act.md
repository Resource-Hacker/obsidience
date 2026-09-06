---
type: tool
title: computer.act
obsidience:
  binding: capability:computer.act
  source: obsidience/harness/capabilities/computer/act.py
  approved_at: '2026-09-05T22:01:54'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

Apply one foreground click on one exact visible text label in an existing
application through the current Shell command owner. Arguments:
`{"application": str, "action": "click", "target": str, "postcondition": str optional}`.

Use a canonical registered application name or exact current app_id from the
Shell Scene. The application must resolve uniquely. `target` is the exact
visible text label, up to 128 characters; icons without a legible unique label
are not supported. `action` defaults to `click`; `postcondition` names the
requested result to inspect, but cannot assert that the result happened.

The Capability activates that exact application for foreground input, captures
its native toplevel, and grounds the requested label with installed CPU
Tesseract. It keeps process instances, Surface/window identities, pixels,
coordinates and single-use command tokens private. The existing Shell adapter
rechecks identity, geometry, awake/unlocked state, label, point and request
ownership around one Wayland motion and click transaction. It adds no daemon,
second input owner, game-specific Tool or GPU model lease.

One invocation consumes the Task's action attempt. A lost receipt or uncertain
delivery must never be replayed. A completed result verifies only the scoped
click and includes a fresh exact post-action image for the Task-selected vision
model. `semantic_postcondition_verified: false` means a larger outcome such as
starting a match is not established by input acknowledgement. Interpret the
returned image before reporting an application result. Pixels are ephemeral and
never enter the durable trace, Source or Vault.
