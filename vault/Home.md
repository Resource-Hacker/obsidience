---
title: Home
kind: note
---
# Obsidience

This vault **is** the system: four authoring primitives, one interpreter.

- **Tasks** (`Tasks/`) — *what* to accomplish; recursive via ordered `subtasks:`. Example: [[Tasks/maintain-vault]]
- **Runbooks** (`Runbooks/`) — *how* a task completes; they name their `skills:`. Example: [[Runbooks/lint-notes]]
- **Agent** (`Agent/`) — the agent's own layer: self-knowledge, the index, and (on the graph) the home of the four collections below.
- **Skills** (`Skills/`) — how to use tools correctly. Example: [[Skills/proposing-changes]]
- **Tools** (`Tools/`) — the executable capabilities. Example: [[Tools/vault.propose]]

The runtime is the interpreter, not a primitive: task → runbook/subtasks →
skills → authorized tools → evidence ([[Receipts|receipts]]) → task state.
Assign and watch tasks in the **Jobs** pane. Agent proposals wait in
`_staging/` for your review.

Laws: edges dispatch, vectors inform · owner writes freely, agents propose ·
mechanism in code, policy in vault · runbooks mandatory for leaf tasks ·
closed tool authorization · receipts immutable.
