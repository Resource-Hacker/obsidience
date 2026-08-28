---
approved_at: '2026-08-21T04:02:35'
binding: capability:vault.propose
kind: tool
provenance: proposed by Codex (task research generation kit)
source: obsidience/harness/capabilities/vault/propose.py
title: vault.propose
---

Stage an Article change for owner review; never write the accepted vault directly.

args: `{"action": "create|update|archive", "target": "Folder/name.md", "title": str, "body": str, "reason": str, "metadata": object}`.

`metadata` is optional and accepts only safe authored fields: `kind`, `binding`,
singular `source`, `tool`, `skills`, `runbook`, `assignee`, `reasoning_effort`,
`owner_maintained`, and the four recursive child fields. A Tool proposal supplies
both `binding: capability:<exact Tool title>` and its one matching entrypoint at
`obsidience/harness/capabilities/<dotted Tool segments>/<leaf>.py`; plural
`sources` are invalid. Use metadata only when a typed graph Article needs
frontmatter. `update` must carry the FULL corrected body; accepted metadata not
named by the proposal is preserved. `archive` applies only to an ordinary
Knowledge Article with no accepted inbound links; approval moves it below
`_archived/`. Unknown metadata fields fail closed.

The body begins below the Article title. An exact redundant leading `# Title`
copied from `vault.read` is normalized away at staging and approval.

Only one unresolved proposal may target an accepted Article. `update` and
`archive` pin the exact accepted base revision, so a competing or stale full
replacement fails closed instead of silently overwriting a reviewed change.
One new leaf Tool and its one pending Skill form an inseparable Capability
review pair: approving the Tool admits both Articles, while an isolated Tool or
more than one paired Skill fails closed.

The harness derives the proposal's review class from the exact accepted Task.
A proposal issued by `Tasks/link` becomes a Link review with its added and
removed Article links projected explicitly. `review_class` is not a Tool
argument or safe metadata field, and approval remains an atomic Article change.
