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
  - '[[Skills/observations.retain]]'
  - '[[Skills/observations.recall]]'
  task: '[[Tasks/merge]]'
---


1. Read every exact `candidate_refs` Article supplied by Curate. Merge only
   ordinary Knowledge within Alexandria's current checkout. Confirm that the
   Articles describe the same subject and are redundant; similarity is only a
   lead. Agent identities, shadow role charters, architecture and executable
   definitions belong to Heimdall. If a candidate or required referring Article
   is outside this scope, report the exact blocker for owner or Heimdall routing;
   do not broaden checkout, infer an unread body or activate another Task.
2. Choose one canonical retained Knowledge Article: prefer the best-placed,
   most complete, most strongly referenced Article. Never archive the retained
   ref. Archive only a distinct redundant ordinary Knowledge Article after its
   unique content and useful relationships are preserved.
3. Compose the retained Article as the smallest complete union of unique
   accepted knowledge, provenance, qualifiers, and meaningful relationships.
   Do not add facts that exist in none of the candidates. If preserving unique
   content requires a union, stage a complete update to the retained Article;
   a summary claiming a merge is not evidence that this update exists.
4. Use the redundant Article's `vault.read` result as the authoritative accepted
   backlink list. Semantic search may add context but can never prove that no
   inbound reference exists. Read every exact Article listed under **Accepted
   inbound references**, then stage its complete update so it points to the
   retained ref. Preserve meaningful edges by rewriting their exact targets
   to the retained Knowledge Article. If a required referring Article is outside
   checkout, report that blocker without proposing archival.
5. Use native `vault.propose` Tool calls, one exact Article per call, in this
   order: required retained-Article union update, each required referring-Article
   update, then the distinct redundant Article's archive request. If the archive proposal
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
   refs and every staged update. Describe unresolved proposals as staged, not
   published consolidation. Complete with an evidenced no-change result only
   after confirming no merge is warranted; unread required Articles or missing
   union/redirect updates are failures, not a clean verdict.

Do not merge different agents' Knowledge folder condensations based on shared
index titles or boilerplate. Their accepted Agent ownership and folder roles
distinguish their scopes. Agent role-charter consolidation belongs to Heimdall. Stale unused
maintenance leads are settled against exact creator and revision evidence
before model admission; changing a queued lead never authorizes executing
its old proposal or discarding an uncertain prior Tool effect.


When a useful nonredundant observation should survive this activation, optionally retain one bounded unverified note in this Agent's own Hindsight bank. Do not record hidden reasoning or create a note merely to narrate routine work.
