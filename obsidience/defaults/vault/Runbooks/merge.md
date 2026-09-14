---
type: runbook
title: Merge procedure
obsidience:
  for_agent: '[[Agents/Alexandria/Alexandria]]'
  owner_maintained: true
  skills:
  - '[[Skills/vault.search]]'
  - '[[Skills/vault.read]]'
  - '[[Skills/vault.validate]]'
  - '[[Skills/vault.propose]]'
  - '[[Skills/observations.temporary.append]]'
  task: '[[Tasks/merge]]'
---

1. Read every exact `candidate_refs` Article supplied by Curate. Confirm that
   they describe the same subject and are redundant. Similarity is only a lead;
   Article-kind differences alone neither prove nor disprove duplication. One
   named Agent is a decisive special case: its canonical `type: agent` Brain
   Article and any parallel Knowledge "role charter" describe one subject and
   are architectural duplicates, not complementary Articles.
2. Choose one canonical retained Article. Prefer the accountable Agent Article
   over a descriptive shadow; otherwise prefer the best-placed, most complete,
   most strongly referenced Article. Only an ordinary Knowledge Article may be
   archived. Unique responsibilities, Task families, boundaries, handoffs, and
   relationships in a shadow role charter are migration material to absorb or
   redirect; they are never a reason to retain a second Article for that Agent.
3. Compose the retained Article as the smallest complete union of unique
   accepted knowledge, provenance, qualifiers, and meaningful relationships.
   Do not add facts that exist in none of the candidates.
4. Use the redundant Article's `vault.read` result as the authoritative accepted
   backlink list. Semantic search may add context but can never prove that no
   inbound reference exists. Read every exact Article listed under **Accepted
   inbound references**, then stage its complete update so it points to the
   retained ref. Preserve meaningful edges by moving them to the canonical
   Agent Article or rewriting their exact targets; do not preserve an edge
   merely to keep the shadow Article alive.
5. Stage exactly one concise `vault.propose` action per turn, in this order:
   canonical retained Article, each referring Article, then the redundant
   Article's archive request. Never combine several proposals in one action or
   add prose outside the single fenced action block. If the archive proposal
   already exists and this run is repairing its missing redirects, reuse it and
   stage only the exact missing referring-Article updates. Never draft a
   competing replacement for the same target.
6. Call `vault.validate` once before staging. If a load-bearing edge would remain broken or
   any inbound reference is unresolved, stop without proposing archival.
7. Stage each redundant ordinary Knowledge Article for archival only after its
   retained content and every inbound reference are covered. If `task.complete`
   rejects review with exact missing redirect refs, read and update every one,
   then retry completion; never stop on an incomplete Merge warning. The Review
   Queue will keep a complete archive disabled until its canonical-union and
   redirect updates are accepted. Finish with `review`, naming the retained and redundant
   refs and every staged update, or `completed` with the exact reason the
   candidate was not safe to merge.

Do not merge different agents' Knowledge folder condensations based on shared
index titles or boilerplate. Their accepted Agent ownership and folder roles
distinguish their scopes. This does not exempt an ordinary shadow role charter
from consolidation into its actual canonical Agent Article. Stale unused
maintenance leads are settled against exact creator and revision evidence
before model admission; changing a queued lead never authorizes executing
its old proposal or discarding an uncertain prior Tool effect.


When a useful nonredundant observation should survive this activation, optionally append one bounded unverified note to this Agent's own Temporary Observations. Do not record hidden reasoning or create a note merely to narrate routine work.
