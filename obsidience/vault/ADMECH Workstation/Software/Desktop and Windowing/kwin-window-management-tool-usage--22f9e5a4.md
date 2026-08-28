---
kind: knowledge
tags:
- kwin
- tools
- windowmanagement
title: KWin Window Management Tool Usage
---

When interacting with KWin for window management, specific tools like `mcp__kwin__configure_window` are not deferrable. They must be invoked directly in the model's tool call list rather than being passed through a generic `tool_call` mechanism. Attempting to use the generic wrapper results in an error stating the tool is not deferrable.

## Relationships

- `related_to` [[ADMECH Workstation/Software/Desktop and Windowing/agent-launch-and-gui-application-management--339f2788|Agent Launch and GUI Application Management]] — KWin window management tool usage constraints apply to the GUI application management and launch processes.
- `related_to` [[ADMECH Workstation/Hardware/Displays/display-topology-and-isolation-strategy--a8755cfa|Display Topology and Isolation Strategy]] — Direct KWin window configuration operates within the display-isolation topology where KWin owns only the primary Samsung display.
