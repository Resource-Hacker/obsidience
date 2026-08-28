---
kind: knowledge
tags:
- software
- agent
- invariant
title: Agent Launch and GUI Application Management
---

Launch GUI: kwin-mcp launch_app or agent-launch-gui.desktop. No nohup/setsid. TFT: tft-mobile-waydroid.desktop launches RTX 4080 AVD. CPUWeight=25 for side displays. Mouse scaling calibrated across displays. Clipboard sync: bidirectional, no stale images.

## Relationships

- `implements` [[Agents/Executive/Architecture/local-first-architecture--7d8e77cc|Local-first Executive architecture preference]] — Managed kwin-mcp/agent-launch-gui launching is the single authoritative desktop-control path the architecture preference calls for.
