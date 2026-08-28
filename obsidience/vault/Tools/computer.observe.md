---
binding: capability:computer.observe
kind: tool
source: obsidience/harness/capabilities/computer/observe.py
title: computer.observe
---

Observe one exact on-screen application through Obsidience's structured
observation service. Arguments:
`{"application": str, "query": str}`.

The result contains bounded visible labels and grounding state. It exposes no
window token, image descriptor, or privileged coordinate and always reports
`action_authorized: false`. This Tool observes; it never injects input.
