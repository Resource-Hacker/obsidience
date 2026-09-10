---
kind: knowledge
title: Historical recovery-plane doctor activation repair
---

On 2026-08-03 the recovery-plane doctor was unreachable even though the immutable runtime and managed unit files remained intact, because every recovery activator had been disabled.

Recovery uses the transactional installer so unit files, encrypted credentials, immutable generation pointers, broker, real-time fabric, watchdogs, and rollback state move together. The installer treats only systemd’s exact per-unit `Unit … not loaded` reset-failed race as benign; every other reset failure remains fatal. The guardian timer includes a late-activation schedule as well as boot and inactive schedules, so enabling it after boot yields an upcoming trigger rather than permanent `active (elapsed)` state.

Acceptance requires repeated online doctor results; matching broker and fabric generations; ready watchdog, MCP, timer, and boot-activator states; correct owner-only root broker material and runtime sockets; and explicit `root_mode=literal` plus `containment=enforcement:none`. These checks attest cooperative root operation, not security containment.

## Relationships

- `mitigates` [[Agents/Executive/Architecture/local-first-architecture--7d8e77cc|Local-first Executive architecture preference]] — The literal-root recovery plane provides a bounded maintenance path for the local-first Executive stack.
