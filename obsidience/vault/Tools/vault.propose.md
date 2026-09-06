---
type: tool
title: vault.propose
obsidience:
  approved_at: '2026-08-21T04:02:35'
  binding: capability:vault.propose
  provenance: proposed by Codex (task research generation kit)
  source: obsidience/harness/capabilities/vault/propose.py
---

Submit an Article change through the normal proposal validator and review ledger.
Ordinary Knowledge creates/updates may publish automatically when the destination
has effective owner Auto-curate permission and the active writer is in scope.
News additionally requires its exact source-backed Research/Inbox/Ingest chain.
One complete Top 10 proposal to `News & Research/Top 10/Top 10.md` compiles the
parent, ten summarized story Articles, and any eligible prior-edition archives
into one bounded Review group. Its exact owner policy permits that rotation;
an affected disabled scope retains the complete group for review.
Other proposals remain for review; capability and Agent authority, general
archives, and conflicting changes are outside ordinary branch Auto-curate.

args: `{"action": "create|update|archive", "target": "Folder/name.md", "title": str, "body": str, "reason": str, "metadata": object}`.

`metadata` is optional for ordinary body changes. Use native OKF `type` and
`description`, `resource`, documentary `sources`, `generated`, native
`status` (`draft`, `stable`, or `deprecated`), and timezone-aware `stale_after`
at its root; application fields such as `assignee`,
`binding`, `owner_maintained`, `reasoning_effort`, `runbook`, `skills`, singular
`source`, `subrunbooks`, `subskills`, `subtasks`, `subtools`, and `tool` belong
under `metadata.obsidience`. The existing flat argument shape remains accepted;
persisted Articles use the native namespaced format. A Tool proposal
supplies both `binding: capability:<exact Tool title>` and its one matching entrypoint at
`obsidience/harness/capabilities/<dotted Tool segments>/<leaf>.py`; plural
`sources` are provenance, never the executable binding. Use metadata only when an Article needs
frontmatter. `update` must carry the FULL corrected body; accepted metadata not
named by the proposal is preserved. `archive` applies only to an ordinary
Knowledge Article with no accepted inbound links; approval moves it below
`_archived/` with native `status: deprecated`, an archive timestamp and reason,
preserving body and documentary metadata. Unknown metadata fields fail closed.
Document status is distinct from Task runtime state. `verified`, trust and
publication-policy fields cannot be supplied through proposal metadata.

A generated Runbook must explicitly supply the minimal required accepted Skill
refs in `metadata.skills` or native `metadata.obsidience.skills`. The supplied
shared catalog is a candidate set, not an automatic grant. The controller binds
exact `task` and `for_agent`; approval derives the dependencies without writing
Agent Tool, Skill, or Runbook lists. The assigned Task waits for that approval.

The body begins below the Article title. An exact redundant leading `# Title`
copied from `vault.read` is normalized away at staging and approval.

Only one unresolved proposal may target an Article. An exact repeated proposal
returns the existing staged item. `update` and
`archive` pin the exact accepted base revision, so a competing or stale full
replacement fails closed instead of silently overwriting a reviewed change.
One new leaf Tool and its one pending Skill form an inseparable Capability
review pair: approving the Tool admits both Articles, while an isolated Tool or
more than one paired Skill fails closed.

The harness derives the proposal's review class from the exact accepted Task.
A proposal issued by `Tasks/link` becomes a Link review with its added and
removed Article links projected explicitly. `review_class` is not a Tool
argument or safe metadata field, and approval remains an atomic Article change.
Link updates only an existing non-runtime Knowledge or Agent Article body.
The harness captures each changed wikilink's body line, excerpt, and endpoint
revision in the proposal. A proposed connection remains a suggestion, not a
verified fact. Missing, self, runtime, or executable endpoints cannot be
approved as new Knowledge links. An edited endpoint produces a visible revision
warning; a changed source Article or proposal body requires a fresh proposal.
