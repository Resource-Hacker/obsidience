---
type: knowledge
title: Development
---

Obsidience is a development build. Work in small, directly testable slices using
the least code that correctly solves the request. Prefer a maintained upstream
implementation when it fits; keep the Obsidience adapter narrow. Remove replaced
architecture instead of accumulating deprecated systems. Preserve a recoverable
copy before broad or destructive changes.

Folders should explain responsibility: one real component per meaningful
subsystem, shared behavior implemented once, and no speculative wrapper hierarchy.
Tools have exact Capability entrypoints in Source and one paired Skill in the
shared Library. Update the master rather than creating an Agent-local prose copy.

Restart affected development processes after changes and verify their live result
so the owner can test immediately. Do not restart unrelated applications or a
securely locked shell. Keep names, Article headings, links, and all UI projections
consistent with [Golden ontology](/Agents/Executive/Architecture/Harness/action-ontology.md)
and [Local-first architecture](/Agents/Executive/Architecture/Harness/local-first-architecture--7d8e77cc.md).
