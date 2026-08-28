---
title: Act on the computer
kind: skill
tool: '[[Tools/computer.act]]'
---

Use `computer.act` only after `computer.observe` identifies one exact semantic
target.

- Pass the application, the exact visible target label, and the intended
  postcondition. Never supply or infer raw desktop coordinates.
- Issue at most one action for the request. Never retry an uncertain delivery.
- Treat `delivery: acknowledged` only as input evidence. The fresh
  post-observation must establish the Task outcome before completion.
- Stop on identity, geometry, grounding, witness, or post-observation failure.
