# Local Hindsight memory

`hindsight.py` is the Obsidience port to the supported Hindsight API. The native
Cordis service is `../execution/deepseek/hindsight.mjs`. It adds bounded recall
to the existing DeepSeek turn, without a second agent loop or a reflection call.
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
4. New or materially changed observations create immutable, hash-attested Sources
   and the existing `observations.memory.ready` event. Alexandria's existing Curate Task
   receives this event alongside its ordinary maintenance schedule. It compares accepted Knowledge and
   stages durable recommendations or delegates an exact Article/observation Source
   pair to the existing Link Task. Individual observation Sources disambiguate a
   batch. Accepted Markdown Source citations are the wiki evidence links; ordinary Link Review owns proposal previews and acceptance.
   All wiki recommendations and observation links require owner Review, including
   in Auto-curate branches. Native consolidation remains automatic. Timestamp or
   proof-count changes alone do not requeue work. Each bank refresh offers one
   batch of at most eight material changes, newest updates first with stable ID
   tie-breaking. Compact manifests retain complete observation records and their
   individual Source citations without repeating the supporting facts. The batch
   targets 32 KiB by selecting whole records; an oversized first record remains
   an intact singleton instead of being truncated or starved. Full supporting
   evidence stays in the original individual Sources. Curate may read an exact
   member only after fully reading its attested activating manifest.
   The existing Curate/Link runtime, FIFO and unresolved Review
   occurrences permit only one outstanding memory batch across all banks.
   Unselected or blocked records keep their original dedup state; the existing
   health tick revisits dirty banks after work settles. Startup reconstructs the
   backlog from native records and admitted hashes, without a separate queue.
   Curate compares accepted Knowledge first and offers at most three useful
   recommendations, preferring corrections or updates to existing subject Articles.
   The proposal writer enforces that limit per activation across retry runs and
   pending or decided Reviews. Every supplied Source citation must resolve;
   new memory citations must belong to the bound batch or one of its members,
   and a cited member needs a complete attested read receipt. Existing valid
   Article citations remain available when revising an Article.
   Routine confirmations need no wiki copy, and curation reports do not feed
   memory recursively. Task reasoning/model, FIFO and Review use existing owners.
5. DeepSeek retains ownership of the continuous conversation and active context.
   Its native `dsh-compaction-basic` backend manages that context. Automatic recall has a 750 ms deadline; the
   explicit scoped `observations.recall` Tool permits six seconds. Neither
   path calls generative Reflect or treats memory as current screen evidence.

The former Connections/Feeds collector and Darwin Distill workflow are retired.
Historical reports remain in Hindsight for recall and inspection. An observation
whose complete supporting provenance resolves to original Feed Distill runs or
their exact Feed-bound Ingest continuations is excluded from automatic wiki
handoffs. Already captured batches and individual members use the same lineage
check at admission/proposal time. Unknown or mixed provenance remains eligible;
this is neither a bank-wide filter nor a text-keyword filter. The retired Feed
stack must not be reconstructed from historical news memories.

Hindsight's native configuration selects the extraction/consolidation provider;
inspect the installation's selected environment rather than assuming a model.
The optional local-model configuration uses the private port in `api.py`, borrowing
only preemptible idle capacity from the existing resident model owner. Foreground
work cancels that pure inference; Hindsight owns its bounded retry. That model
port has no capabilities and restores the selected Executive context afterward.
CPU ONNX embeddings and FlashRank consume no CUDA model allocation.

Conversation requests and Harness Task objectives have distinct provenance
labels. A scheduled or triggered Task objective does not establish a direct
owner request; its accepted public report remains an unverified agent report.

An owner maintenance marker at `state/hindsight-maintenance.json` pauses outbox
delivery, observation handoffs, admission of memory-event Curate occurrences,
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
The existing health tick resumes pending delivery after reset; recall and the
independent owner curation hold are unchanged. Failed operation receipts remain
visible and retain their once-per-operation recovery limits.
An independent `state/hindsight-delivery-paused.json` marker keeps new turns in
the durable outbox after maintenance without blocking read-only memory use or
independently enabled Curate handoffs. Native extraction and
consolidation model selection belongs to Hindsight; a one-off provider override
must not silently become the ongoing provider.
The private local model endpoint rejects inference while either pause is set,
including native jobs restored after reboot. One-off cloud rebuild credentials
and provider configuration must survive reboot for the duration of that work;
keep credentials encrypted and remove the override when maintenance completes.
An independent `state/hindsight-curation-paused.json` marker stops new observation
Sources/handoffs and admission of queued `observations.memory.ready` occurrences.
It survives maintenance completion and restarts without stopping recall, native
memory inspection, or ordinary scheduled/manual Curate. The owner controls when
this ingestion route resumes; delivery and curation holds are separate choices.
After a one-off rebuild, an installation may keep the native API available with
`HINDSIGHT_API_WORKER_ENABLED=false` until the owner selects the ongoing model.
Retire the completed controller and provider override before removing the rebuild
marker; preserve any independent delivery and curation holds.

## Health and curation controls

`/api/memory/status` reports provider/storage and operation failures separately
from its content-free `recall` telemetry. A retained failed operation can make the
aggregate degraded while recent recall remains healthy. `not_observed` means no
recent completed recall evidence, not verified failure or verified success.

`processing_paused`, `delivery_paused` and `curation_paused` describe different
owner controls. A curation hold prevents memory-to-wiki recommendations and their
observation Link admission; it does not disable capture, recall, or ordinary wiki
maintenance. Accepted Knowledge and unverified Memory remain distinct owners.
Backpressure from pending execution, FIFO or Review is not a provider fault and
never authorizes bypassing a hold, replaying uncertain effects or approving wiki
changes. Resumption retains original Source, activation and memory identities.

## Deployment contract

This optional service is separate from the Harness Python environment. Install
PostgreSQL with pgvector, then install the exact requirements in an isolated
Python 3.13 environment:

```sh
uv venv --python 3.13 <hindsight-venv>
uv pip install --python <hindsight-venv>/bin/python -r obsidience/harness/memory/requirements.txt
patch --forward -d <hindsight-venv>/lib/python3.13/site-packages -p1 < obsidience/scripts/patches/hindsight/0001-render-graphs-outside-event-loop.patch
patch --forward -d <hindsight-venv>/lib/python3.13/site-packages -p1 < obsidience/scripts/patches/hindsight/0002-bound-cpu-reranking-and-cancellation.patch
patch --forward -d <hindsight-venv>/lib/python3.13/site-packages -p1 < obsidience/scripts/patches/hindsight/0003-openrouter-daily-quota-reset.patch
```

Initialize a private PostgreSQL cluster with UTF-8, local peer authentication,
host SCRAM authentication, and mode 0700. Run it as the owner, with no TCP
listener, an owner-only Unix socket directory, and a dedicated database. The
accepted setup uses PostgreSQL 18 and pgvector 0.8.6. An explicit username in
the DSN is required by Hindsight's migration URL normalization:

```text
postgresql://<owner>@/obsidience_hindsight?host=<socket-directory>&port=55437
```

Create an owner-only random token at
`obsidience/state/hindsight-token`. The same token is the Hindsight LLM API key;
the adapter also sends it in the Authorization header for registered callbacks.
Never put it in public defaults, command arguments, Git or logs. Keep the
following environment in mode-0600 `obsidience/state/hindsight.env`, substituting
the selected paths and token:

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
HINDSIGHT_API_EMBEDDINGS_PROVIDER=onnx
HINDSIGHT_API_EMBEDDINGS_ONNX_MODEL_PATH=<existing BGE model_optimized.onnx>
HINDSIGHT_API_EMBEDDINGS_ONNX_TOKENIZER_NAME_OR_PATH=<existing BGE tokenizer directory>
HINDSIGHT_API_EMBEDDINGS_ONNX_MODEL_ID=qdrant/bge-small-en-v1.5-onnx-q
HINDSIGHT_API_EMBEDDINGS_ONNX_DIMENSIONS=384
HINDSIGHT_API_EMBEDDINGS_ONNX_POOLING=cls
HINDSIGHT_API_EMBEDDINGS_ONNX_NORMALIZE=true
HINDSIGHT_API_EMBEDDINGS_ONNX_QUERY_PREFIX=
HINDSIGHT_API_EMBEDDINGS_ONNX_PASSAGE_PREFIX=
HINDSIGHT_API_RERANKER_PROVIDER=flashrank
HINDSIGHT_API_RERANKER_FLASHRANK_MODEL=ms-marco-MiniLM-L-12-v2
HINDSIGHT_API_RERANKER_FLASHRANK_CACHE_DIR=<private model cache>
HINDSIGHT_API_RERANKER_MAX_CANDIDATES_LOW=16
HINDSIGHT_API_RERANKER_FLASHRANK_BATCH_SIZE=1
HINDSIGHT_API_RERANKER_FLASHRANK_INTRA_OP_THREADS=8
HINDSIGHT_API_CONSOLIDATION_RECALL_BUDGET=mid
HINDSIGHT_API_WEBHOOK_ALLOWED_HOSTS=127.0.0.1
HINDSIGHT_API_AUDIT_LOG_ENABLED=false
HINDSIGHT_API_SKIP_LLM_VERIFICATION=true
CUDA_VISIBLE_DEVICES=
OMP_NUM_THREADS=2
TOKENIZERS_PARALLELISM=false
```

Use the existing pinned BGE artifact rather than downloading a second copy:
revision `52398278842ec682c6f32300af41344b1c0b0bb2`, ONNX SHA256
`51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431`.
Keep the CLS pooling, normalization and empty prefixes paired with this model.
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
transaction and its upstream operations, then Memory/Reader and the existing
Curate handoff. Service liveness alone is insufficient. Fresh installs leave
this optional provider disabled until its dependencies are configured.

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
Three failures among the latest twenty completed calls in fifteen minutes mark
the provider degraded through the same status/Audit path. A new lifetime or an
expired window says `not_observed`, not recall-verified. STOP interruptions are
counted separately, never as failures or successes. Recall failures authorize no
automatic replay, and no queries or recalled memory text enter this telemetry.

Before maintenance, preserve the Harness ledger, PostgreSQL database, immutable
Source blobs and private token/config together. To disable the provider, remove
only the local `[memory]` URL and restart the idle Harness. Preserve its database
and outbox for re-enabling; do not delete memories to clear a health warning.
There is no legacy Temporary/Immediate observation store or Compact/Promote Task.
Disabling Hindsight preserves its database and queued handoffs; it does not enable
an alternate memory implementation.

Memory uses Hindsight's native `world`, `experience` and `observation` types.
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
[memory practices](https://hindsight.vectorize.io/best-practices),
[native DeepSeek integration](https://hindsight.vectorize.io/blog/2026/08/14/deepseek-harness-persistent-memory).

Completed-turn dates use the original conversation timestamp or Task completion
time, including recovery. The Codex notifier sends only the latest owner input
and uses the native UUIDv7 turn creation time. The Claude Code `Stop` hook sends
the turn's human prompt (matched by `prompt_id`), its final reply and the
prompt's transcript timestamp with `source: claude-code`. Historical input lists must not be
re-retained as though they happened at every subsequent completion. The provider
retains explicit event dates extracted from the content. Correct misdated facts
through Hindsight’s native memory edit API; it rebuilds temporal links and derived
observations. Never spread records across fabricated dates for presentation.
