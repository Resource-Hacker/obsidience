---
type: knowledge
title: Desktop scene and computer use
sources:
- resource: obsidience/harness/host/scene.py
- resource: obsidience/harness/capabilities/computer/observe.py
- resource: obsidience/harness/computer/runtime.py
- resource: obsidience/harness/computer/capture.py
- resource: obsidience/harness/capabilities/window/command.py
- resource: obsidience/shell/qml/api/ShellCommandServer.qml
---

The Shell publishes one bounded, revisioned scene for the logical Surfaces and
addressable native windows. It describes semantic target identity, focus,
visibility, Surface placement and power state. The Harness may attach the
current semantic scene to [Thinking Packet Bindings](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md);
exact compositor identifiers, geometry witnesses and capture leases remain
private controller state. Window lists and coordinates are not durable Knowledge.

## Identity and effects

An application target uses its registered canonical ID or exact current
`app_id`; a pane target uses its exact `pane_id`. Display titles and focus are
not stable identity. The resolver rejects ambiguous targets rather than choosing
a similarly titled or currently focused window. A Surface may disambiguate an
otherwise identical application identity.

[computer.observe](/Tools/computer.observe.md) captures the focused window or an
exact application/pane through the pinned Wayshot implementation, without
implicitly changing focus. The returned concrete target is reusable; `focused`
is only an input selector. [window.activate](/Tools/window.activate.md) and
[window.place](/Tools/window.place.md) are distinct effects with fresh scene
readback. Their verified scene results do not require an extra screenshot to
prove focus or placement.

The current [computer.act](/Tools/computer.act.md) implementation accepts an
image-grounded **click on an application**, not arbitrary typing, dragging or
pane automation. It consumes the immediately preceding observation's one-use
lease, checks freshness and process/window identity, and sends input through
the Shell command owner. A state-scoped sequence is bounded and requires a new
observation between actions. An acknowledged click plus a post-image establishes
input delivery; the requested application state still requires interpretation
of fresh evidence. An uncertain receipt must not be replayed as if no click
occurred.

Locked, hidden, sleeping, stale or ambiguous targets fail closed. A sleeping
Surface is not woken implicitly. Selection, observation, focus, placement and
input do not establish new Agents, Tasks or capability authority.

See [Native shell and surfaces](/Agents/Executive/Architecture/Shell/native-shell-and-surfaces.md) for window
ownership and [Task activation](/Agents/Executive/Architecture/Harness/task-activation--b30a4642.md) for
execution authority. Physical display details are discovered locally and are not installation defaults.
