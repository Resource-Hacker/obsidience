---
type: task
title: Tool
obsidience:
  approved_at: '2026-08-21T04:02:33'
  assignee: '[[Agents/Darwin/Darwin]]'
  provenance: proposed by Codex (task research generation kit)
  reasoning_effort: high
  runbook: '[[Runbooks/create-a-tool]]'
---

The Tool child of the top-level Generate Task. Darwin synthesizes one executable
Tool contract for one existing `capability:<exact Tool title>` entrypoint and its
mandatory paired Skill from supplied capability context. If that singular
Source-linked entrypoint does not exist, he reports the exact implementation gap
and fails closed instead of creating a fake Tool. This Task documents existing
executable machinery; it does not author code or create an implementation Task.
Supporting Modules remain internal.
