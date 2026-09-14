---
type: tool
title: vault.propose
description: Stage an accepted-scope Article revision with target, action:create|update|archive,
  and applicable title/body/reason/metadata.
obsidience:
  binding: capability:vault.propose
  source: obsidience/harness/capabilities/vault/propose.py
---

## Runtime

Stage an accepted-scope Article revision with target, action:create|update|archive, and applicable title/body/reason/metadata. Preserve exact Sources and current revision evidence. Feed publication uses only the bound source and target. Checkout does not allow writing another Agent's Observations. Authority and lifecycle changes retain Review. Read the Reference before generating definitions or grouped relation changes.

## Reference

An active controller-bound Feed Distill Inbox uses only `source` (its exact Inbox citation) and `target` (the exact activation target); optional `action` and `reason` remain documentary inputs. Omit `body`, title and authored metadata. The owner requires the complete Inbox read, preserves Darwin's entire summary, derives native resource/sources/generated fields, and stages one ordinary Article Review under the Feed's selected existing Knowledge node. The node's current Auto-curate selection controls automatic approval. A changed/deleted destination fails clearly; repeated published item versions preserve accepted content and timestamps. The Feed's active-Article limit retires exact oldest excess publications by attested Feed lineage, including earlier destinations. Incoming publication and required archival form one bounded decision through the existing Review owner; do not submit separate Feed archives.

Submit a complete Article change through the existing validator and Review owner.

Arguments: `{"action":"create|update|archive","target":"Folder/name.md","title":str,"body":str,"reason":str,"metadata":object optional}`. Target must be a safe vault-relative Markdown path outside system folders. Creates and body-form updates require the full nonempty body, at most 131,072 characters. Updates preserve omitted accepted metadata. Legacy wikilinks normalize to Markdown links; an exact redundant leading `# Title` is normalized away.

Native OKF metadata: root `type` (`knowledge|task|runbook|tool|skill|agent`), `description`, `resource`, documentary `sources`, `generated`, document `status` (`draft|stable|deprecated`) and timezone-aware `stale_after`. Under `metadata.obsidience`: `acceptance`, `assignee`, `binding`, `model`, `owner_maintained`, `reasoning_effort`, `runbook`, `skills`, singular executable `source`, `subrunbooks`, `subskills`, `subtasks`, `subtools`, `taxonomy_path`, singular `tool`, and `triggers`. Legacy flat application fields and `kind` remain accepted; persisted Articles use native names. Unknown/conflicting fields, trust, verification, publication policy, runtime and review state are rejected. Plural `sources` is provenance, never executable binding; document status is not Task state.

Ordinary Knowledge creates/updates may publish under effective owner Auto-curate and the active writer's scope. Other changes remain for Review; ordinary Auto-curate excludes capability/Agent authority changes, general archives and conflicts. Archive approval requires ordinary Knowledge with no accepted inbound links and moves it under `_archived/`, preserving body/documentary metadata and adding deprecated status, archive time and reason.

Only one unresolved proposal may target an Article. Exact repeats return the existing item; different pending proposals and stale accepted-base revisions fail closed. Updates/archives pin that base. A new leaf Tool requires `binding: capability:<exact Tool title>` and its matching `obsidience/harness/capabilities/<dotted segments>/<leaf>.py` entrypoint; it and exactly one pending paired Skill are approved together. Isolated/ambiguous pairs cannot be approved. Generated Runbooks explicitly select minimal accepted `metadata.obsidience.skills` (flat `metadata.skills` also accepted). The controller binds Task/Agent applicability; approval supplies dependencies without changing Agent grants, and the Task waits for it.

For `Tasks/link`, the controller derives Link review; `review_class` is not an argument. Link updates only existing non-runtime Knowledge or Agent bodies and records changed links, excerpts and endpoint revisions. Missing, self, runtime or executable endpoints cannot become new Knowledge links. Edited endpoints produce review warnings; changed source/proposal bytes require a fresh proposal. A recorded connection does not prove its assertion.

Copied vault.read end markers and generated `Accepted inbound references` sections are rejected before staging. For Link, the complete current Article and every changed endpoint must have a full vault.read receipt. Missing reads are returned together in batches of at most ten; complete the requested reads before retrying. The same proposal may be retried after those exact evidence requirements are met.

Results distinguish `Proposal staged for owner review`, actual `Article published`, attested no-change and `Proposal rejected`. Publication attests acceptance, not factual truth. Rejections identify draft/handoff errors, not Source loss. Unsafe targets, invalid action/body/metadata or Capability contracts, stale bases, conflicting pending work and failed evidence/relationship gates block the request.
