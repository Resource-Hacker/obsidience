---
title: Launch an application
kind: skill
tool: '[[Tools/application.launch]]'
---

How to use `application.launch` safely and accurately.

- Select exactly one registered application identifier from the Tool contract.
- Invoke it once for one explicit launch request; never retry merely because a
  newly dispatched application has not produced a window yet.
- Report `ready` as open, `starting` as starting, and `failed` with its bounded
  error. Never turn dispatch success into a readiness claim.
- Do not substitute a related launcher. An unqualified World of Warcraft
  request uses the registered Smooth Motion profile; Battle.net is separate.
