# Harness

The Harness is Obsidience's Python runtime in `obsidience/harness/`. One API
lifetime owns the executor, scheduler, accepted-knowledge index, model runtime,
conversation lane and speech connection. These are subsystems of one Harness,
not independent Agents or Modules. The Harness owns conversation, knowledge,
model resources, capability validation, Review and execution receipts.

## Package map

Packages stay shallow: one level of subsystems, explicit imports and
`capabilities/` mirroring Tool ids.

| Package | Owns |
| --- | --- |
| `interfaces/api/`, `interfaces/cli/` | The FastAPI app (one router per resource in `routes/`) and the `obsidience` CLI |
| `conversation/` | The Executive conversation owner, context projection and selection |
| `execution/` | Executor, scheduler, capability core, completion authority, ledger, trace, activity, speech admission and the ADK loop (`execution/adk/`) |
| `capabilities/` | One Capability per Tool, plus the static registry |
| `knowledge/` | Vault parsing and writing, retrieval index, scope, Review, Source, intake, maintenance and System inventory |
| `memory/` | The Hindsight port |
| `models/` | Model catalog, leases, residency, benchmarks and the model client |
| `realtime/` | The speech connection, devices, camera and the speech worker (`realtime/speech/`) |
| `graphs/` | Activity and refresh for the Memory and Code views |
| `shell_port/` | The Harness side of the Shell Scene and command boundary |
| `web/`, `media/`, `tv/`, `discord/`, `host/` | Web lookup, media and TV clients, the Discord integration, host inventory |

## The Executive loop

Chat and final speech enter the Executive's one
[Google ADK](../../integrations/google-adk.md) conversation. The model route is
a thin ADK model that streams from the local
[llama.cpp](../../integrations/llama-cpp.md) server (`adk_model_client =
"local"`); ADK's official LiteLLM route is the rollback.

- **One session per conversation** in `state/adk-sessions.sqlite3`; only New
  Conversation rotates it. Speech lifetime is not conversation lifetime. The
  user turn is stored before execution; an assistant turn only for a current,
  completed, nonempty reply.
- **Window, not compaction.** The provider sees the conversation from one
  anchor that moves only at idle edges ([Memory](../../memory.md#flow)).
- **Finite lanes.** A HassIL grammar lane executes complete simple commands
  (lights and TV on/off, pause/stop, local time) as one exact dispatch with no
  model call. A one-token scorer can choose among schema-valid proposals for a
  few registered operations; everything else uses native generation. These are
  provider modes, never a router.
- **Interpretation rules.** Health questions use `harness.status`; visible
  content needs fresh `computer.observe`; physical surroundings need fresh
  camera evidence. Quoted examples, hypotheticals and bare application names
  authorize nothing; an unclear target gets one concise clarification.
- **Lookup.** Missing public facts are looked up in the conversation with
  `web.search` (leads) and `web.fetch` (evidence). Explicit research is
  delegated to Darwin as a bounded Question or Learn.
- **Completion checks.** Claims of opening, unlocking or pausing need this
  Run's matching verified receipt; ungrounded claims return to the loop.

Specialist Tasks run on the same loop and capability core; see
[Tasks](../../articles/tasks.md#how-tasks-run).

## Context accounting

Before every inference the actual templated request (with images) is counted.
The model server must acknowledge the exact input ceiling for every step, or
the adapter fails closed. Under pressure only older pageable read bodies with
exact reread paths may be projected; the packet, Objective, receipts and latest
observation stay complete. Streams require a finish state and are never
reconnected or replayed. Reasoning stays private.

## Models and hardware residency

- Hardware is a set of independent component slots; persisted owner selections
  beat code fallbacks. A Task's model lease displaces only overlapping
  components and restores the saved selection afterwards.
- Models are never substituted, and context, precision or resources are never
  reduced to make one fit; layers do not spill to CPU unless an owner-approved
  profile allows it.
- `model.added` activates Heimdall's Model Task: inspect, record the immutable
  source manifest, benchmark (same prompt, 256-token ceiling, one discarded
  warmup, three samples) and apply the smallest measured configuration change.
- **Settings → AI & Voice** owns residency and the microphone, speaker, camera
  and voice choices; hardware monitoring is read-only.

## In this section

- [Realtime voice](voice.md): the speech pipeline from wake word to speaker.
- [Self-improvement](self-improvement.md): Heimdall's Audit and Harness2.

The authoritative statement of these rules is
[DESIGN.md](https://github.com/Resource-Hacker/obsidience/blob/main/DESIGN.md#execution).
