---
binding: capability:computer.act
kind: tool
source: obsidience/harness/capabilities/computer/act.py
title: computer.act
---

Apply one exact, semantically grounded computer action through the sole CUA
driver. The current bounded action is one click. Arguments:
`{"application": str, "action": "click", "target": str, "postcondition": str optional}`.

Obsidience keeps observation identity, target tokens, pixels, and coordinates
inside the Tool. It freshly observes and validates before delivery, consumes
the single action attempt whether delivery succeeds or becomes uncertain, and
returns a fresh post-observation. Delivery acknowledgement is not Task success.
