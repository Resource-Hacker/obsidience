---
binding: capability:harness.status
kind: tool
source: obsidience/harness/capabilities/harness/status.py
title: harness.status
---

Return one deterministic, read-only Obsidience health snapshot without shell
access.

args: `{}`.

The result reports accepted graph size, Task states, pending reviews, Source
integrity, and bounded recent execution failures. It observes state only; it
does not diagnose a root cause, retry work, or repair anything.
