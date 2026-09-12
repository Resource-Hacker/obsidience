---
type: runbook
title: Curate procedure
obsidience:
  for_agent: '[[Agents/Alexandria/Alexandria]]'
  owner_maintained: true
  skills:
  - '[[Skills/vault.maintenance]]'
  - '[[Skills/task.create]]'
  - '[[Skills/observations.temporary.append]]'
  task: '[[Tasks/curate]]'
---

1. Call `vault.maintenance` exactly once. Do not perform an unbounded manual
   scan or treat a similarity or connectivity signal as a conclusion. For a
   missing-link lead, isolated endpoints, separate components, and shared
   semantic neighbors are inspection context only; none proves a useful
   relationship. Native hierarchy already connects every ancestor and descendant,
   including checked-out Knowledge beneath its Agent root. Never request a Link
   for those pairs. Shared ancestry alone does not justify a sibling cross-link.
2. If no unclaimed candidate exists, complete with the checked Article count
   and a clean no-change result. A disconnected-vault summary alone never
   activates Link.
3. Select only the first ranked candidate and map its exact recommendation:
   - `Merge` → `Tasks/merge`;
   - `Link` → `Tasks/link`;
   - `Improve` → `Tasks/improve` for a broken reference or missing folder Article;
   - `Audit` → `Tasks/audit` for elapsed native `stale_after` or an explicitly due evidence review;
   - `Archive` → `Tasks/archive` for explicit native `status: deprecated` or supersession.
   Call `task.create` exactly once with:
   `{"task":"<mapped exact Task ref>","params":{"candidate_key":"<exact key>","candidate_revision":"<exact revision>","candidate_refs":["<exact returned refs>"],"candidate_kind":"<kind>","candidate_signals":{<exact signals>}}}`.
   Do not add an objective, acceptance test, Runbook, Agent, model, or title;
   those belong to the accepted destination Task and its Runbook.
4. Complete Curate after `task.create` returns `started` or `queued`. If it
   returns `deferred` with reason `target_awaiting_review`, complete Curate with
   an honest deferred/no-change result: the destination remains responsible for
   its own review, and Curate owns no proposal. Never mark Curate `review` for a
   destination's state, activate more than one Task in a single execution, or
   perform the destination's work inside Curate. A queued activation is not a
   completed repair; report any failed destination as blocked work.

The Tool suppresses only an explicit completed no-change verdict for the same
candidate revision in the existing execution ledger. Changed inputs become
eligible again; failures, guesses and pending reviews never count as no-change.
A `missing_index` lead concerns an absent folder Article, not a missing
Markdown child list. An existing folder Article and native hierarchy provide
structural coverage. Parent condensation remains useful prose, and missing
facts are not permission to invent. Age alone is not
staleness; native `stale_after`, explicit `status: deprecated`, an authored review date,
or exact supersession supplies a lifecycle lead. Each destination Task verifies
that lead independently.

The activated Task retains its authored WIKI placement. Its activation packet
records Curate as causal provenance, not as a parent or subtask.

Maintenance inputs remain bound to their inspected revision. If queued inputs
change or become ineligible before execution, the Scheduler can settle that
exact unused lead without editing an Article or replaying a Tool. The original
receipt remains available; a new inspection of changed inputs has its own
revision-bound occurrence and must not be dropped as already processed.
Agent-owned Knowledge folder condensations are structural scope Articles,
not duplicate candidates merely because different agents share index prose.


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Do not record hidden reasoning or create a note merely to narrate routine work.
