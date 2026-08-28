---
assignee: '[[Agents/Alexandria/Alexandria]]'
enabled: true
kind: task
last_run: d016c45a158d
model: obsidience-qwen38-27b-q8
triggers:
- task.create
params:
  activation_key: 20930d9f5fce319766e9
  candidate_key: 20930d9f5fce319766e9
  candidate_refs:
  - ADMECH Workstation/Software/Games/World of Warcraft/world-of-warcraft-launch-policy--3e5e73cc
  - ADMECH Workstation/Software/Games/World of Warcraft/world-of-warcraft-movement-and-mouselook-suite--f7a51a37
  created_by_run_id: 6a29b1b409e8
  created_by_task_ref: Tasks/curate
  event: task.create
  target_task: Tasks/merge
reasoning_effort: xhigh
runbook: '[[Runbooks/merge]]'
status: completed
status_updated: '2026-08-26T20:19:30'
summary: 'Review requested for merging [[ADMECH Workstation/Software/Games/World of
  Warcraft/world-of-warcraft-movement-and-mouselook-suite--f7a51a37]] into the retained
  [[ADMECH Workstation/Software/Games/World of Warcraft/world-of-warcraft-launch-policy--3e5e73cc]],
  after validation reported all 269 load-bearing edges resolving. Staged updates are:
  the canonical launch-policy union, [[ADMECH Workstation/Hardware/Displays/Samsung
  Odyssey OLED G9/samsung-display-vrr-and-edid-configuration--96ccfd7b]] redirected
  to the retained article, and [[Games/WoW/primary-world-of-warcraft-profile--f2cc8948]]
  redirected to the retained article while preserving its primary-character context;
  the redundant movement article is staged for archival after its accepted inbound
  references are covered.'
taxonomy_path: wiki/merge
title: Merge
triggered_at: '2026-08-26T18:00:42'
---

Consolidate one exact duplicate candidate set into one complete canonical
Article. Success preserves every unique accepted fact and useful relationship,
redirects accepted references, validates the graph, and stages only genuinely
redundant ordinary Knowledge for archival. A false lead completes with no
change.
