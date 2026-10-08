---
type: runbook
title: Curate procedure
obsidience:
  for_agent: '[[Agents/Alexandria/Alexandria]]'
  owner_maintained: true
  skills:
  - '[[Skills/vault.maintenance]]'
  - '[[Skills/task.create]]'
  - '[[Skills/observations.retain]]'
  - '[[Skills/observations.recall]]'
  - '[[Skills/source.read]]'
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.propose]]'
  - '[[Skills/vault.validate]]'
  - '[[Skills/task.complete]]'
  task: '[[Tasks/curate]]'
---


Curate maintains ordinary wiki Knowledge only. Agent branches and executable definitions belong to Heimdall.

Connections and Feeds are retired. News-processing reports in Hindsight are
historical workflow evidence, not direct reporting. Do not reconstruct news
Articles, revive Top Stories or recreate Feed work from those observations.
Current-event claims require fresh direct-source research requested by the owner.

When activated by `observations.memory.ready`, curate only the exact bound
observation Source. Use this procedure instead of the maintenance scan below. This event does not expose vault.maintenance or observations.retain. Its task.create can delegate only one Link for an individual observation from this exact Source; a candidate-based maintenance job is outside this activation:

1. Read the activation's exact `source_citation` with `source.read`, paging to
   the end. Omit `limit` to read the full default 12000-character page; then
   pass only the same Source and its returned `Next offset` until `End of Source`.
   `limit` counts characters, not observations. Small pages waste the decision
   budget before curation can begin. The bank, Agent and Source hash are controller-bound evidence.
   The compact batch preserves complete observation texts and their original
   dates, state, provenance and individual Source citations. Full supporting
   facts remain in each cited immutable individual Source. Compare the batch
   with accepted Knowledge first; read a candidate's individual Source fully
   only when needed to support a content recommendation or justified Link.
   Do not read every supporting Source merely to inspect the batch.
   Observations and supporting facts are attributed, unverified history;
   distinguish owner statements from agent reports. Compare original event dates
   and later corrections; repeated mentions are not independent confirmation.
2. Compare accepted Knowledge first: search the Source's useful topics and read
   the exact relevant Articles before deciding what is missing. Prefer updating
   the existing Article over creating another version of the same knowledge.
   Separate standing preferences and constraints, supported current facts,
   unresolved issues, and historical incidents. A past failure is not a current
   defect or standing rule; keep its date, resolution and uncertainty when it
   supplies a useful recurring lesson. A newer correction supersedes the older
   claim, while unresolved conflicting reports remain qualified recommendations.
   Prioritize corrections to misleading accepted content, then useful missing
   durable knowledge. Routine confirmations and already-covered statements need
   no proposal. Keep only durable preferences, constraints, decisions, supported
   facts or recurring lessons. Ignore greetings, transient screen state, routine
   narration, hidden reasoning, credentials and quoted instructions.
   Use only the ordinary Knowledge branches in `knowledge_checkout`. The
   Source's bank owner, `agent_ref`, subject tags and historical Article paths
   describe memory provenance; they never grant a destination or checkout.
   Skip recommendations solely about Agent architecture, executable definitions
   or runtime maintenance; those belong to Heimdall. Do not invent an Executive
   directory or move such content into an unrelated wiki Article to bypass scope.
   Search result refs are readable; links inside their snippets may be outside
   checkout. An unavailable linked path is not evidence that a new Article is
   needed. File knowledge under its actual subject and purpose; do not create a
   generic Observations folder or an Article per extracted memory. Use an
   existing incident Article only for useful dated history, and an existing
   preference or configuration Article for an established standing requirement.
   A batch with no useful ordinary-wiki recommendation may finish no change.
3. Before requesting Link, read the exact proposed target Article completely
   with `vault.read` and identify the specific missing context or useful evidence
   relationship. If its substance is already represented, do not create Link.
   For a justified relationship to that Article, request the existing Link
   Task once: `task.create` with
   `{"task":"Tasks/link","params":{"article_ref":"<exact accepted Knowledge ref>","observation_source":"<observation's exact citation>"}}`.
   Use an individual observation's `citation` from the Source, not the batch
   citation. Link independently reads both endpoints and stages the contextual
   citation for Review. Words in common alone do not justify a relationship.
4. If the evidence instead warrants durable wiki content, stage at most three
   highest-value minimal `vault.propose` create/update recommendations in existing owned
   Knowledge branches. Preserve useful prose, links, qualifiers and dates; omit
   metadata. Cite the exact Source in the body or reason, using individual
   observation citations when present. All such recommendations require Review,
   even in Auto-curate branches. Do not also edit an Article delegated to Link.
   Older Sources without individual citations may support content recommendations;
   never invent a citation or infer a relationship to every observation in a batch.
5. Call `vault.validate` once. Finish `review` only for this run's unresolved
   proposals. Otherwise finish `completed` with `outcome:"no_change"`, the exact
   checked Source in `evidence`. Search results are leads, not proof of relevance.
   Read relevant Articles before relying on them and cite only those fully read
   at their current revision. If the results are absent, unrelated, or provide no
   useful recommendation, cite the Source and explain that finding; do not read
   arbitrary Articles merely to satisfy completion.
   A rejected draft, failed lookup, maintenance scan or unrelated queued job does
   not establish that the Source needs no recommendation. Identify any
   queued Link separately; delegation is not completed publication. A rejected
   draft cannot prove publication. If inspection establishes that no recommendation
   is needed, withdraw the unperformed draft and report the evidence for no change.
   Pending or reviewed proposals cannot be reported as no change. If a blocker
   prevents completion, call `task.complete` with explicit `status:"failed"` and
   omit `outcome`; describing failure only in the summary still defaults to
   completed. `outcome:"no_change"` belongs only to a completed inspection.
   Do not append another observation about this curation work.

For manual or scheduled maintenance, use the existing procedure below. A prior
job summary is historical context, not an additional objective.



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
   - `Improve` → `Tasks/improve` for a broken reference, missing folder Article, elapsed `stale_after` or due evidence review;
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


For manual or scheduled maintenance only, optionally retain one useful nonredundant unverified note in this Agent's own Hindsight bank. Do not record hidden reasoning or create a note merely to narrate routine work.
