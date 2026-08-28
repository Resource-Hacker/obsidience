---
binding: capability:vault.maintenance
kind: tool
source: obsidience/harness/capabilities/vault/maintenance.py
title: vault.maintenance
---

Inspect one current vault snapshot and return a bounded, ranked list of
high-signal maintenance candidates with exact Article references, stable
candidate keys, structural signals, and the appropriate accepted Task. Current
checks cover strong duplicate leads and strong missing-link leads that are not
already directly connected. The result is read-only and deterministic. A
candidate is a lead for Curate, not a semantic verdict or permission to edit.
