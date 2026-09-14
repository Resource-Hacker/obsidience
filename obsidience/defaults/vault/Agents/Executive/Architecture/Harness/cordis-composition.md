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

DeepSeek Harness now owns the Executive conversation model/Tool loop through
its supported CLI profile and public Cordis interfaces. The existing Python
capability owner retains argument validation, committed receipts, fresh target
verification, cancellation and completion acceptance. Ordinary answers are native
text; the shared completion authority accepts them locally without another model
request. SQLite remains the only durable conversation and receipt store. Native
sessions and observation images are ephemeral. Scheduled Tasks retain their
Python decision loop and share the same CapabilityDispatch operation boundary.

The accepted Agent catalog defines available native schemas. Articles remain explanatory knowledge. Native schema availability does not claim that every Tool or Skill Article body was loaded.

## Development rules

1. Declare each component's provided service interfaces, required dependencies and optional integrations. Consumers depend on the contract; configuration composes compatible providers. Keep existing explicit seams and introduce a new abstraction only where a real component needs it.
2. Give subscriptions, listeners, registrations, timers, workers, clients and leases one lifecycle owner. Register their cleanup at acquisition, using context managers, ExitStack, try/finally or the host's equivalent. Release only resources that component actually owns.
3. Activate work only while its required dependencies are available. Cancellation, dependency loss or teardown must stop/drain owned work and release resources. Reconnection uses the same owner and generation checks, not a second scheduler or agent loop.
4. Preserve one authority for each durable store, conversation, scheduler, model reservation and desktop input path. A component delegates through that interface rather than reaching into another owner's private state or constructing an alternate control path.
5. Keep registrations and internal lifecycle effects reversible where the host supports it. Removing a plugin cannot undo a delivered click, sent communication, committed Source or accepted Knowledge change. Preserve receipts, uncertain-outcome handling and explicit compensation; hot reload is not rollback of the external world.
6. Keep the foreground path short: a stable compact instruction prefix, existing reusable clients and model leases, avoid an extra large-model classification call that displaces the Executive conversation cache, and no full registry rebuild merely for presentation. Measure actual end-to-end boundaries before claiming a latency gain.
7. Prefer a maintained upstream component through its supported adapter. Record adopted code and licenses in the existing reuse manifest. Reference material alone is not an installed dependency, and plugin composition must not become a second generic framework.

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

The production Executive uses CLI 0.1.5-rc.1 and agent-loop/agent/tools/llm 0.1.5-rc.2 on Cordis 4.0.2, pinned by the project dependency lock. Obsidience supplies the model, prompt, capability and application ports. New work should extend these existing contracts with explicit lifecycle ownership. The rest of the project adopts Cordis composition at real change seams; not every file or Article needs a plugin. Small isolated probe timings are not whole-project or microphone-to-speaker latency claims.

## Relationships

- `extends` [Golden ontology](/Agents/Executive/Architecture/Harness/action-ontology.md) — Adds implementation composition and lifecycle rules without changing Article meanings.
- `governs` [Harness](/Agents/Executive/Architecture/Harness/Harness.md) — Existing subsystem services retain explicit ownership and cleanup.
- `governs` [Real-time Executive](/Agents/Executive/Architecture/Harness/real-time-executive.md) — Chat and speech share one execution owner and standing procedure.
- `governs` [Task activation](/Agents/Executive/Architecture/Harness/task-activation--b30a4642.md) — Task procedure selects Tools while infrastructure composition stays behind their contracts.
- `governs` [Activation packet protocol](/Agents/Executive/Architecture/Harness/activation-briefing-protocol--21d7f1ad.md) — The packet's DeepSeek model/Tool loop is composed under Cordis's explicit service contracts and lifecycle ownership.
