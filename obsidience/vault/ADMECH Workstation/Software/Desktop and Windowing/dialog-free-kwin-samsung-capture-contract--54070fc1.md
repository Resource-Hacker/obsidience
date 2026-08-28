---
kind: knowledge
title: Dialog-free KWin Samsung capture contract
---

Executive Samsung screen capture uses KWin `zkde_screencast_unstable_v1` version 5 directly through the registered root-owned native helper. It is pinned to `HDMI-A-1`, hides the cursor, and captures logical bounds `0,0 5120x1440`.

The active path never calls the XDG ScreenCast portal, shows a chooser, depends on a restore token, or falls back to portal capture. The owner-only framed-CBOR socket, exact generation and epoch validation, and sealed-memfd publication bind every observation to its source frame.

Output loss, KWin restart, stream closure, PipeWire failure, or a missing first frame leaves the socket alive in fail-closed `capture_unavailable` state. The same service process retries with bounded backoff and installs a new 128-bit stream generation when capture returns. Live helper-termination acceptance retained the service PID and restored fresh full-resolution frames with a new helper and generation in about 1.5 seconds.

## Relationships

- `uses` [[ADMECH Workstation/Hardware/Displays/display-topology-and-isolation-strategy--a8755cfa|Display Topology and Isolation Strategy]] — Capture is pinned to the Samsung output in the established isolated-display topology.
