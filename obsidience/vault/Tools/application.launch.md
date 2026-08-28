---
binding: capability:application.launch
kind: tool
source: obsidience/harness/capabilities/application/launch.py
title: application.launch
---

Dispatch one registered desktop application exactly once through the
workstation-managed graphical launcher. Argument:
`{"application": "battle_net|world_of_warcraft|teamfight_tactics|microsoft_edge"}`.

The result distinguishes `ready`, `starting`, and `failed`. `ready` requires a
current compositor window witness. A successful dispatch without that witness
is only `starting` and must never be described as fully open.
