# Local Hindsight memory

`hindsight.py` is the Obsidience port to the supported Hindsight API. The ADK
Executive loop (`../execution/adk/runner.py`) takes one bounded automatic recall
for each owner turn, without a second agent loop or a reflection call.
The official Hindsight coding-agent bundle is a design reference; its Git
history importer and separate coding wiki are deliberately not mounted.

## Ownership and flow

1. Accepted public conversation turns and completed specialist reports enter
   a durable delivery outbox in the existing Harness ledger. Stable operation
   and document IDs make upstream acceptance idempotent; acknowledged payloads
   are removed from the outbox. Interrupted work is not presented as success.
2. Hindsight owns extraction, facts, entities, relationships and consolidated
   observations in PostgreSQL/pgvector. Each accepted Agent identity has its own
   bank. These are historical, attributed, unverified memories.
3. Memory is a separate movable graph pane. It reads native per-Agent memory
   records and relationships through the provider graph API. Exact
   `@memory/<bank>/<id>` references remain readable in the existing Reader for
   evidence inspection. No raw memory nodes or native provider edges enter the
   accepted Article graph. Inspection never grants another Agent bank access.
4. The Executive bank carries three native mental models: "Owner preferences
   and standing permissions", "Workstation state changes" and "Recent decisions
   and commitments". The adapter creates any missing one from the existing
   delivery task; an existing model, including owner refinements, is never
   overwritten. Hindsight fully regenerates them after consolidation, at most
   once per six hours per model, using its configured provider. The default trigger
   permits observations plus raw world/experience facts, so reflection can check
   source evidence; it excludes other mental models to avoid recycling their
   summaries. In Hindsight 0.10.3, this enables an initial observation search and
   raw-fact recall on each refresh. The 1,536-token page target is not a hard
   provider-output or cost cap. Existing models need a separate native trigger
   update; provisioning preserves their current settings. Mental-model refreshes have no webhook,
   so the existing 30-second health tick lists model metadata. A changed page
   (content hash) becomes one immutable, attested Source and one
   `observations.memory.ready` occurrence for Alexandria's Curate Task, bound to
   the exact mental-model id and version. A refresh that kept the page, or a
   page that returns to an already curated version, starts no run. Only one
   page handoff is outstanding at a time: its Curate occurrence is queued,
   running or awaiting Review. Curate reads the complete page, compares accepted
   Knowledge and stages at most three create/update recommendations that cite
   the page Source, always through owner Review, including in Auto-curate
   branches. It delegates no Task. Curation reports do not feed memory
   recursively. Observations are no longer copied into Sources; earlier
   observation Sources, batch manifests and their Article citations remain
   readable history, and already queued observation Link occurrences keep
   their existing execution path.
5. The ADK conversation log owns the continuous conversation; its provider
   window bounds the active context without summary compaction. At an idle edge,
   a window beyond six exchanges or 4,000 estimated tokens normally rebases to
   the newest three exchanges within 2,000 tokens, always keeping at least two.
   Eligible exchanges await confirmed extraction before eviction. Delayed
   extraction allows overlap through 12 exchanges or 8,000 tokens; beyond either
   threshold the window rebases and tells the model that some earlier exchanges
   are not yet confirmed recallable. These are overlap thresholds, not absolute
   caps on two unusually large exchanges. A content-free sequence range records
   the gap; its warning clears only after all eligible exchanges in that range
   have confirmed extraction receipts. Withheld diagnostics do not delay rebasing.
   Automatic recall has a 750 ms deadline; the
   explicit scoped `observations.recall` Tool permits six seconds. Neither
   path calls generative Reflect or treats memory as current screen evidence.
   Automatic recall queries the owner request alone and, concurrently under the
   same deadline, the request joined with the owner request it follows; the
   second result fills one of the three slots. Each query can succeed independently:
   a failed query leaves the successful results available with a compact `partial`
   notice. If neither succeeds, the model receives an `unavailable` notice even
   with no memories. Healthy recall gains no status text. Timeout or owner
   cancellation cancels and joins unfinished requests; owner cancellation propagates.
   Every recall sends the local
   time as `query_timestamp`, so "today" and "yesterday" resolve on the owner's
   calendar. The port, not Hindsight's `prefer_observations`, drops an
   observation/source pair, keeping the better-ranked one. The model sees each
   memory's local recording minute with its age ("4 days ago").

The mental models ask about owner preferences, workstation changes and
decisions. Their background refresh does not require a standing prompt summary:
`memory_summary = false` keeps those pages out of the conversation prompt while
preserving bounded per-turn recall, explicit inspection and Curate handoffs.

Hindsight's native configuration selects the extraction/consolidation provider;
inspect the installation's selected environment rather than assuming a model.
The accepted provider is Hindsight's native `openai-codex` provider with the
installation's selected Codex model at the standard service tier, strict
structured output and no fallback; the retain, consolidation, Reflect and
mental-model-refresh role overrides use high reasoning. It authenticates through
the existing Codex login home, used in place and never copied into Hindsight's
environment. Missing provider configuration or credentials fails startup rather
than selecting the local model.
The optional local-model configuration uses the private port in
`interfaces/api/routes/memory.py`, borrowing only preemptible idle capacity from
the existing resident model owner. Foreground work cancels that pure inference;
Hindsight owns its bounded retry. That model port has no capabilities and
restores the selected Executive context afterward.
CPU ONNX embeddings and FlashRank consume no CUDA model allocation.

Conversation requests and Harness Task objectives have distinct provenance
labels. A scheduled or triggered Task objective does not establish a direct
owner request; its accepted public report remains an unverified agent report.
New external Codex and Claude Code deliveries identify their reporting assistant
in retain context, separately from the bank owner. Content/metadata hashes and
existing delivery payloads stay unchanged, so an acknowledged retry is not
re-extracted and queued deliveries keep their original context.
Completed-turn intake admits up to 262,144 characters per role and a combined
524,544-character envelope, including controller labels. Both roles are retained
in full after secret redaction; oversized input or redaction expansion is rejected
rather than silently truncating the conversation. Exact retries keep their source
identity and original date. Compatibility with former 16K envelopes only completes
still-pending payloads in place; already acknowledged deliveries are not replayed.

`POST /api/turns/complete` synchronously reports durable `inserted`, `duplicate`
or `withheld` state, or `disabled` intake. Disabled intake returns `accepted: false`;
identity conflicts return HTTP 409, oversized input 413, and failed durable recording
503. An outbox insert does not prove native extraction. Its `pending` row becomes
`accepted` only after Hindsight acknowledges the exact operation ID and its payload
is cleared. For eligible conversation exchanges, `extracted` additionally requires
the exact native `batch_retain` parent and every child to be completed, with each
child bound to that parent and reporting zero extraction errors and a valid
nonnegative outcome count. A valid zero-fact extraction is allowed. The existing
delivery/health path collects these content-free receipts; webhooks only wake it.
Diagnostic `memory_writeback: false` turns reserve their `withheld` identity before
execution, so an interrupted turn, continuation or startup recovery cannot retain
them later.

An owner maintenance marker at `state/hindsight-maintenance.json` pauses outbox
delivery, mental-model handoffs, admission of memory-event Curate occurrences,
and automatic native-operation repair. New completed turns still enter the
durable outbox; read-only recall and graph inspection remain available. Remove
the marker after native validation and wake the port with a registered bank's
completion event to refresh observations and, unless delivery remains paused,
drain the outbox. Native
`enable_auto_consolidation` is independently controlled through Hindsight's
bank configuration; reconnecting the port never resets an owner's pause or
replaces their reviewed extraction/consolidation missions with defaults.
An explicit OpenRouter daily free-quota reset in native failure evidence also
defers new outbox delivery and automatic recovery until that provider deadline.
Only the reset timestamp is projected, never raw provider error/account data.
The existing health tick resumes pending delivery after reset; recall is
unchanged. Failed operation receipts remain
visible and retain their once-per-operation recovery limits.
An independent `state/hindsight-delivery-paused.json` marker keeps new turns in
the durable outbox after maintenance without blocking read-only memory use or
mental-model Curate handoffs. Native extraction and consolidation model
selection belongs to Hindsight; a one-off provider override must not silently
become the ongoing provider.
The private local model endpoint rejects inference while either pause is set,
including native jobs restored after reboot. One-off cloud rebuild credentials
and provider configuration must survive reboot for the duration of that work;
keep credentials encrypted and remove the override when maintenance completes.
The maintenance marker also pauses mental-model provisioning and page handoffs;
there is no separate curation marker.
After a one-off rebuild, an installation may keep the native API available with
`HINDSIGHT_API_WORKER_ENABLED=false` until the owner selects the ongoing model.
Retire the completed controller and provider override before removing the rebuild
marker; preserve any independent delivery hold.

## Health and curation controls

`/api/memory/status` reports provider/storage and operation failures separately
from its content-free `recall` telemetry. A retained failed operation can make the
aggregate degraded while recent recall remains healthy. `not_observed` means no
recent completed recall evidence, not verified failure or verified success.

`processing_paused` and `delivery_paused` describe different owner controls;
`curation_paused` mirrors the maintenance hold. `mental_models` reports each
page's last refresh, failed refresh and staleness; `mental_model_error` reports
a failed listing, provisioning or handoff without blocking delivery or recall.
A failed native refresh is an ordinary failed operation for the existing
Heimdall repair path. Accepted Knowledge and unverified Memory remain distinct
owners. Backpressure from pending execution, FIFO or Review is not a provider
fault and never authorizes bypassing a hold, replaying uncertain effects or
approving wiki changes.

An independent queued Curate occurrence can pass a failed, blocked or interrupted
occurrence when its complete Tool receipts permit that transition. Two exact `task.create`
rejections prove no Task was enqueued: the forbidden delegation from a
memory-triggered Curate, and a scheduled Curate's maintenance candidate fields
not matching its controller result. The scheduler requires a returned receipt,
the current `Tools/task.create` content hash, and the exact rejection result hash
and length. Generic errors, missing receipts and uncertain effects do not qualify;
the failed run is preserved and its call is never replayed.

## Deployment contract

This optional service is separate from the Harness Python environment. Install
PostgreSQL with pgvector, then install the exact requirements in an isolated
Python 3.13 environment:

```sh
uv venv --python 3.13 <hindsight-venv>
uv pip install --python <hindsight-venv>/bin/python -r obsidience/harness/memory/requirements.txt
for patch in obsidience/scripts/patches/hindsight/00*.patch; do
  patch --forward -d <hindsight-venv>/lib/python3.13/site-packages -p1 < "$patch"
done
```

This applies the reviewed native patches 0001 through 0010 in numeric order;
[their README](../../scripts/patches/hindsight/README.md) explains each one, and
`artifacts.lock.json` records their preimage and result hashes.

Initialize a private PostgreSQL cluster with UTF-8, local peer authentication,
host SCRAM authentication, and mode 0700. Run it as the owner, with no TCP
listener, an owner-only Unix socket directory, and a dedicated database. The
accepted setup uses PostgreSQL 18 and pgvector 0.8.6. An explicit username in
the DSN is required by Hindsight's migration URL normalization:

```text
postgresql://<owner>@/obsidience_hindsight?host=<socket-directory>&port=55437
```

Create an owner-only random token at
`obsidience/state/hindsight-token`. The adapter sends it in the Authorization
header for registered callbacks, and the optional local-model configuration also
uses it as the Hindsight LLM API key. Never put it in public defaults, command
arguments, Git or logs. Keep the environment in mode-0600
`obsidience/state/hindsight.env`. The block below is the optional local-model
configuration; substitute the selected paths and token. With the accepted
provider, `HINDSIGHT_API_LLM_PROVIDER=openai-codex`, the selected model, the
role overrides above and that provider's own retain, consolidation and worker
budgets replace the `HINDSIGHT_API_LLM_*`, completion-token, batch and
worker-slot lines; the embedding, reranker, recall and webhook lines are shared:

```text
HINDSIGHT_API_DATABASE_URL=<private PostgreSQL DSN>
HINDSIGHT_API_LLM_PROVIDER=openai
HINDSIGHT_API_LLM_BASE_URL=http://127.0.0.1:8765/api/memory/model/v1
HINDSIGHT_API_LLM_MODEL=obsidience-gemma
HINDSIGHT_API_LLM_API_KEY=<shared token>
HINDSIGHT_API_LLM_MAX_CONCURRENT=1
HINDSIGHT_API_LLM_MAX_RETRIES=3
HINDSIGHT_API_LLM_TIMEOUT=600
HINDSIGHT_API_LLM_REASONING_EFFORT=none
HINDSIGHT_API_LLM_STRICT_SCHEMA_RETAIN=true
HINDSIGHT_API_LLM_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}
HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS=3584
HINDSIGHT_API_RETAIN_BATCH_TOKENS=1800
HINDSIGHT_API_CONSOLIDATION_MAX_COMPLETION_TOKENS=3584
HINDSIGHT_API_WORKER_ID=obsidience-hindsight
HINDSIGHT_API_WORKER_MAX_SLOTS=1
HINDSIGHT_API_WORKER_CONSOLIDATION_RESERVED_SLOTS=0
HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai
HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL=http://127.0.0.1:8791/v1
HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL=embeddinggemma-2-bf16-68bae29d
HINDSIGHT_API_EMBEDDINGS_OPENAI_BATCH_SIZE=8
HINDSIGHT_API_EMBEDDINGS_MAX_INPUT_TOKENS=6000
HINDSIGHT_API_EMBEDDINGS_QUERY_PREFIX='task: search result | query: '
HINDSIGHT_API_EMBEDDINGS_PASSAGE_PREFIX='title: none | text: '
HINDSIGHT_API_RERANKER_PROVIDER=flashrank
HINDSIGHT_API_RERANKER_FLASHRANK_MODEL=ms-marco-MiniLM-L-12-v2
HINDSIGHT_API_RERANKER_FLASHRANK_CACHE_DIR=<private model cache>
HINDSIGHT_API_RERANKER_MAX_CANDIDATES_LOW=16
HINDSIGHT_API_RERANKER_FLASHRANK_BATCH_SIZE=1
HINDSIGHT_API_RERANKER_FLASHRANK_INTRA_OP_THREADS=8
HINDSIGHT_API_RECALL_STRATEGY_BOOSTS=temporal:medium
HINDSIGHT_API_CONSOLIDATION_RECALL_BUDGET=mid
HINDSIGHT_API_WEBHOOK_ALLOWED_HOSTS=127.0.0.1
HINDSIGHT_API_AUDIT_LOG_ENABLED=false
HINDSIGHT_API_SKIP_LLM_VERIFICATION=true
CUDA_VISIBLE_DEVICES=
OMP_NUM_THREADS=2
TOKENIZERS_PARALLELISM=false
```

Embeddings come from the one resident EmbeddingGemma 2 service
(`obsidience-embeddings.service`, whose source is in `obsidience/harness/systemd/`,
running `obsidience/scripts/embed.sh`) that the
Knowledge index also uses; Hindsight loads no embedding model of its own. The
wrapper exports `HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY` from the
`obsidience-model-api-key` credential (otherwise the provider would send the LLM
key). Keep the query/passage prefixes paired with this model (quote them: the
trailing spaces matter); vectors are 768-d. Changing the embedder or dimension
means exporting every bank and importing it into a new empty database
(`hindsight-admin export-bank` / `import-bank`; no LLM work), which re-embeds and
re-derives semantic links but gives memories new ids; mental-model ids are kept.
Skipping the startup LLM probe breaks the startup dependency cycle with the
Harness; it does not skip validation of actual extraction requests.
Retain uses the upstream strict-schema option for its native extraction output.
Automatic recall uses the low budget with at most 16 fused candidates reranked
inside its 750 ms deadline. Explicit memory lookup has a six-second deadline;
it and background consolidation use the broader mid budget. These are ceilings,
not waits or retries. All retrieval methods and stored memories remain
available; the small budget bounds the costly cross-encoder stage, not storage.
The accepted Ryzen CPU profile uses one candidate per ONNX forward pass and
eight intra-op threads without spinning. This avoids padding every short memory
to a long batch neighbor and bounds abandoned work to the current forward pass.
The second native patch carries Hindsight's existing disconnect token into that
worker; no new cancellation owner or rerank model is added. `OMP_NUM_THREADS`
does not configure ONNX's own thread pool. The model and 512-token truncation
remain unchanged; dynamic quantization can cause small batch-dependent score
differences. Re-measure the profile after an ONNX, model or hardware change.

A question that names a time ("yesterday", "on Friday") gets a further retrieval
arm: memories dated in that window, then memories linked to them in time. The
window ranks, it does not filter. The `temporal:medium` boost promotes that arm.
Set it only on Hindsight 0.10.3 or later: in 0.10.2 the same setting lowered
recall for dated questions. The fourth native patch keeps the port's local
offset on a date parsed from the question, so its window is the owner's
calendar day rather than the same date in UTC.

Supervise the private PostgreSQL server and
`<hindsight-venv>/bin/hindsight-api --host 127.0.0.1 --port 8790` as separate user
services, with the latter requiring the database, mode-0077 umask and low
CPU/IO weight. The local units are `obsidience-hindsight-postgres.service` and
`obsidience-hindsight.service`. No global PostgreSQL service or public listener
is needed. The stable worker ID lets upstream recover its own interrupted work.

Enable the port in the local, ignored `obsidience/obsidience.toml`:

```toml
[memory]
hindsight_url = "http://127.0.0.1:8790"
```

Restart only the Harness when idle. Check `/api/memory/status`, an actual retained
transaction and its upstream operations, then Memory/Reader, the three Executive
mental models and the Curate page handoff. Service liveness alone is
insufficient. Fresh installs leave this optional provider disabled until its dependencies are configured.

## Recovery and rollback

Success webhooks wake the existing delivery/projection path. Hindsight 0.10.0
does not expose a failure webhook, so the existing Harness health tick audits
the small health/failed-operation endpoints at most once per 30 seconds. It
does not rebuild the graph or run a model. Failed operations enter Heimdall's
existing status/Repair path. A fresh inspection permits one retry of that exact
upstream operation, with durable intent before dispatch; uncertain retries are
not repeated. Exhausted or unsupported failures appear in the existing Review
notification queue. Neither notifications nor memory can approve wiki changes.
Recall health is reported separately from storage/worker health, with content-free
per-budget counts, timeout counts and durations for the current Harness lifetime.
Partial results and unavailable recalls both count as failures for this health
window. Three failures among the latest twenty completed calls in fifteen minutes mark
the provider degraded through the same status/Audit path. A new lifetime or an
expired window says `not_observed`, not recall-verified. STOP interruptions are
counted separately, never as failures or successes. Recall failures authorize no
automatic replay, and no queries or recalled memory text enter this telemetry.

Before maintenance, preserve the Harness ledger, PostgreSQL database, immutable
Source blobs and private token/config together. To disable the provider, remove
only the local `[memory]` URL and restart the idle Harness. Preserve its database
and outbox for re-enabling; do not delete memories to clear a health warning.
Disabling Hindsight preserves its database and queued handoffs; it does not enable
an alternate memory implementation.

Memory uses Hindsight's native `world`, `experience` and `observation` types.
`world` records facts about others and the environment; `experience` records the
bank agent's own actions and experiences. This is a perspective distinction,
not a confidence or truth rating: an external assistant's report about its own
work is not the Executive's experience merely because the Executive owns the bank.
The sixth native patch makes the extraction prompt and schema descriptions agree
on that perspective. Classification follows the substantive actor, so a Codex
report of the Executive's own action remains an Executive experience, with its
reporting attribution and uncertainty preserved. The native schema still emits
`assistant` for these facts and stores that value as `experience`.
`observation` is a consolidation derived from source facts; a mental model is a
longer synthesis answering a standing question. All remain attributed, unverified
history. Current working context and fresh Tool evidence retain their execution
owners, while accepted Knowledge and permissions retain their Article/Review
owners. A memory or mental-model page never supplies new authority.
The Memory pane offers All memories and filters for those types, alongside the
existing Agent bank selector, entities, original dates and source evidence. No
custom category schema is installed. Memory types do not create Article folders
or reclassify accepted Knowledge; retention and source identities keep their owners.

The provider view loads `/api/graphs/memory` and the existing `/ws/activity`
stream. Exact bank scopes distinguish recall, reads, confirmed retention and
consolidation. Its local force layout owns presentation only. Search does not
invoke the model, and a view refresh cannot trigger curation by itself.
Changing a filter sends its state and visible counts without resending the whole
record catalog. The shared viewer transport replaces obsolete queued snapshots;
independent bounded framing lets small state updates interrupt catalog delivery
while preserving complete messages and ordered controls. Empty memory filters
show an explicit empty view instead of retaining an earlier video frame.

Upstream: [installation](https://hindsight.vectorize.io/developer/installation),
[memory practices](https://hindsight.vectorize.io/best-practices).

Completed-turn dates use the original conversation timestamp or Task completion
time, including recovery. The Codex notifier sends only the latest owner input
and uses the native UUIDv7 turn creation time. The Claude Code `Stop` hook sends
the turn's human prompt (matched by `prompt_id`), its final reply and the
prompt's transcript timestamp with `source: claude-code`. Historical input lists must not be
re-retained as though they happened at every subsequent completion. The provider
retains explicit event dates extracted from the content. Correct misdated facts
through Hindsight’s native memory edit API; it rebuilds temporal links and derived
observations. Never spread records across fabricated dates for presentation.
