---
type: knowledge
title: Cordis composition
sources:
- resource: https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/docs/cordis-primer.md
- resource: https://arxiv.org/abs/2608.25512
- resource: DESIGN.md
obsidience:
  owner_maintained: true
---

# Cordis composition

Cordis composition is Obsidience's project-wide development design. Obsidience follows its explicit dependency and lifecycle principles across the Harness, Shell, UI and integrations. Apply them when building or changing a real component; avoid a speculative framework rewrite.

## Meaning in the ontology

A plugin is a composable implementation unit that provides or consumes named service contracts and owns its registrations and effects. It is an implementation role, not a seventh Article type or another Agent. A Module is still a top-level product component; a subsystem or plugin may implement its service contract. Not every file, function, Article, Skill or Task needs to become a plugin.

A model-facing Tool is the code-owned executable interface to a Capability. Its Tool Article describes that interface and its paired Skill explains its use. A plugin can provide the Capability's machinery or a non-model infrastructure service. Installing a plugin never grants Tools: the accepted Agent catalog or Task → Runbook → Skill → Tool bindings identify the permitted capabilities. Knowledge explains the design and cannot grant capabilities by itself.

DeepSeek owns the active conversation and native compaction; Hindsight owns historical observations and scoped recall.

Only New Conversation changes the selected conversation ID. The upstream native compaction backend owns summary generation and checkpoint replacement, retaining its balanced recent tail and the full audit log. Earlier context packets are superseded, interrupted partial
replies are excluded from model history, and old images are consumed rather than
reused as current pixels. Native recovery records an interrupted Tool's unknown
outcome without replaying it. Scheduled Tasks retain their Python decision loop
and share the same CapabilityDispatch operation boundary.

The accepted Agent catalog defines available native schemas. Articles remain explanatory knowledge. Native schema availability does not claim that every Tool or Skill Article body was loaded.

## Development rules

1. Declare each component's provided service interfaces, required dependencies and optional integrations. Consumers depend on the contract; configuration composes compatible providers. Keep existing explicit seams and introduce a new abstraction only where a real component needs it.
2. Give subscriptions, listeners, registrations, timers, workers, clients and leases one lifecycle owner. Register their cleanup at acquisition, using context managers, ExitStack, try/finally or the host's equivalent. Release only resources that component actually owns.
3. Activate work only while its required dependencies are available. Cancellation, dependency loss or teardown must stop/drain owned work and release resources. Reconnection uses the same owner and generation checks, not a second scheduler or agent loop.
4. Preserve one authority for each durable store, conversation, scheduler, model reservation and desktop input path. A component delegates through that interface rather than reaching into another owner's private state or constructing an alternate control path.
5. Keep registrations and internal lifecycle effects reversible where the host supports it. Removing a plugin cannot undo a delivered click, sent communication, committed Source or accepted Knowledge change. Preserve receipts, uncertain-outcome handling and explicit compensation; hot reload is not rollback of the external world.
6. Keep the foreground path short: a stable compact instruction prefix, existing reusable clients and model leases, avoid an extra large-model classification call that displaces the Executive conversation cache, and no full registry rebuild merely for presentation. Measure actual end-to-end boundaries before claiming a latency gain.
7. Adopt a maintained framework or upstream component when it makes the system better: one per concern, through its supported extension points, pinned and recorded with its license in the existing reuse manifest. Reference material alone is not an installed dependency. These principles are stated runtime-independently in the [Golden ontology](/Architecture/Harness/action-ontology.md).

## Knowledge provider boundary

Obsidience supplies application services to DeepSeek through its native Cordis
adapter. DeepSeek owns the Executive conversation and model/Tool loop;
Obsidience owns accepted Knowledge, scoped retrieval, Source capture, Review,
capability receipts, model reservations and specialist scheduling. The Shell
displays those owners' state. `vault.search`, `vault.read` and `vault.list` expose
the current knowledge owner as native Tools. Fast prefetch uses the same index.

[Tencent's dsh-weknora plugin](https://github.com/Tencent/WeKnora/tree/1ef38fdb8b19347b82d3a99f6f17d75ac09ad606/packages/dsh-weknora)
uses this knowledge-provider pattern: bounded source passages and document
reads through DeepSeek's Tool registry. Its optional `weknora_ask` runs a
separate server-side answer pipeline. Ordinary Executive retrieval keeps the
current model reasoning directly over evidence; independently queueable research
uses existing specialist work. The local BM25/dense RRF index and accepted
Markdown wiki remain their current owners.

Return the selected bounded search passage intact. Further current Article
reads supply complete evidence for edits and links. Integrate maintained
providers at demonstrated service gaps while preserving scope, lifecycle and
evidence identity. This comparison is a design reference; no WeKnora code or
runtime dependency was adopted.

## Native Tool protocol

The owner accepts DeepSeek's native Tool schema and invocation protocol for the
Executive-loop migration. The code-owned Tool definition is the executable
contract: name, parameters, output and implementation. Tool and Skill Articles
explain the registered capability and its use; they do not impose a second
machine-call schema or require Obsidience's existing `{tool, args}` response
format. Keep exact Article-to-Capability provenance and accepted Agent bindings,
while changing adapters and documentation together when the executable interface
changes. Ordinary conversational text can use the upstream response stream;
capability code retains argument validation, receipts, target verification and
cancellation. DeepSeek now owns the Executive model/Tool loop. The existing
completion authority validates ordinary final text locally; native task.complete
remains available for structured terminal status and computer-state verification.

## Adoption boundary

The Executive uses the DeepSeek CLI and native agent/session/Tool packages pinned in `obsidience/harness/execution/deepseek/package.json` and its lockfile. The current source pins DeepSeek 0.2.0-rc.2 and Cordis 4.0.4. Obsidience supplies the model, prompt, capability and application ports. New work should extend these existing contracts with explicit lifecycle ownership. The rest of the project adopts Cordis composition at real change seams; not every file or Article needs a plugin. Small isolated probe timings are not whole-project or microphone-to-speaker latency claims.

## Relationships

- `extends` [Golden ontology](/Architecture/Harness/action-ontology.md) — Adds implementation composition and lifecycle rules without changing Article meanings.
- `governs` [Harness](/Architecture/Harness/Harness.md) — Existing subsystem services retain explicit ownership and cleanup.
- `governs` [Real-time Executive](/Architecture/Harness/real-time-executive.md) — Chat and speech share one execution owner and standing procedure.
- `governs` [Task activation](/Architecture/Harness/task-activation--b30a4642.md) — Task procedure selects Tools while infrastructure composition stays behind their contracts.
- `governs` [Activation packet protocol](/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md) — The packet's DeepSeek model/Tool loop is composed under Cordis's explicit service contracts and lifecycle ownership.

## Maintenance ownership

Alexandria owns ordinary wiki curation, including content, links and freshness. Heimdall owns Harness and Agent health, definitions, capability wiring, execution recovery and operational model characterization. Darwin owns external research and generates proposed assets; Heimdall independently evaluates their execution. Recovery remains an ordinary Tool plugin behind the existing Task owner, with exact durable receipts, FIFO settlement and event-driven continuation. Guardian definition visibility is distinct from Knowledge checkout and executable Tool grants.

Heimdall owns AutoSaddler improvement through the existing Audit Task and
harness.optimize capability. One upstream V2 engine diagnoses and compares
Executive and specialist instruction candidates. Native DeepSeek and specialist
execution supply isolated evaluations; capability contracts grade captured
completion/proposal decisions independently of the optimizing model. Receipt
capture, event deduplication, model reservations and publication keep their
existing owners. AutoSaddler supplies its native session retry policy; candidate
and rollout budgets bound each job. Owner-authorized validated instruction bodies
may publish through the existing Review writer after the Audit receipt commits.
Metadata, Tool authority and runtime code cannot publish through that path.
Unsupported cases and code defects remain Review findings. There is no separate
model-driven inspection/proposal repair loop or additional scheduler.
