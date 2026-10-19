# Obsidience design

Older dated design notes are archived locally by the installation; consult the archive before reviving a retired design.

Current design as of 2026-10-09, each rule stated once. This file is published:
installation facts (hardware, outputs, devices, addresses, grants, model files, paths)
belong only in the ignored `AGENTS.local.md`. Publication rules: `AGENTS.md` and
`obsidience/defaults/README.md`. Where this file and code disagree, fix this file.

Obsidience is a standalone, graph-native agent harness for small local models:

> The knowledge graph is the harness, and each activation should give the model the
> smallest complete packet needed to succeed.

It follows [Karpathy's LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
immutable raw Source, an agent-maintained Markdown wiki and its schema are ordinary files.
Authored folder-index Articles are the summaries (no automatic recursive summarisation).


## Design laws

1. **One Article graph is authoritative.** The Vault defines knowledge, work, procedure,
   Tool authority and guidance, and Agent identity; UI trees, menus, schedules and
   prompts are projections that consume the navigation manifest's exact IDs.
2. **Every Knowledge graph node is an Article.** A parent indexes and condenses its
   descendants; a leaf is complete. `index`/`folder`/`domain` are presentation roles.
   Generated index titles are capitalized; Tool identifiers keep exact spelling.
3. **Edges dispatch; retrieval informs.** Tasks resolve one exact accepted Task and its
   bindings; conversation resolves the Executive's direct Skills. Similarity, links and
   model output never create authority.
4. **Definitions and execution are separate.** Articles define reusable objects;
   occurrences, attempts, status, traces and results live in the execution ledger.
5. **Shallow is the default.** Deeper only when every child is independently useful.
6. **No fictional Tool.** A Tool exists only with one real `capability:<Tool title>`
   binding and one Source-linked entrypoint.
7. **Optimize for small models.** Explicit contracts, narrow choices, stable names, short
   Articles, closed Tool sets and deterministic validation over prompt cleverness.
8. **Disk paths are literal.** Wiki and raw Sources are durable; indexes, DTOs,
   embeddings and UI trees are derivations; a shown Source path is the exact file opened.

## Cordis composition

Adopted 2026-09-12 for Harness, Shell, UI and integrations (Article
`Architecture/Harness/cordis-composition`).

- Plugins provide or consume explicit service interfaces and own their effects; plugin
  and service are implementation roles, not Article types or grants. Modules keep their
  product boundaries.
- Declare required dependencies and optional integrations; never import another owner's
  private state or add a duplicate owner to bypass an unavailable service.
- Register cleanup with acquisition (subscriptions, timers, clients, workers, leases);
  stop and drain owned work on cancellation, dependency loss and teardown.
- One authority per store, conversation, scheduler, model reservation and desktop input
  path. Reloads never undo delivered effects; keep receipts and uncertain-outcome handling.
- Prefer maintained upstream components through supported adapters; record adopted code
  and licenses in `artifacts.lock.json`. Adopt a maintained framework when it makes the system better (one per
  concern, staged behind a switch with a rollback); the principles live in the Golden ontology.

## Independent conversation surfaces

An integration may bind a separately accepted Agent identity to its own native
ADK conversations. Discord uses the Obsidience Discord Bot identity and exact
guild/channel/member bindings; it shares execution and model owners while keeping
its conversation history, direct Skills, scoped Knowledge and Hindsight bank
separate from the Executive. External members do not inherit workstation-owner
authority. Controller admission, completion verification and effect receipts stay
in the same execution core.

Scene membership is presentation metadata. The independent Discord Agent and its
Memory are absent from the Executive scene and normal Memory wall, while remaining
available for explicit management. Its dedicated camera surface stacks accepted
Knowledge above its own unverified Hindsight projection. Real Agent/run and native
bank events drive activity; camera output contains no private reasoning or raw
transcripts. The local virtual camera is selected by a normal Discord client;
the official bot transport carries audio.

## Article ontology

Six types, through Open Knowledge Format v0.2 with the Obsidience profile:

| Type | Meaning |
| --- | --- |
| `knowledge` | Facts, constraints, context, explanations, indexes, domains |
| `task` | A reusable outcome with inputs and acceptance conditions |
| `runbook` | The process for completing a Task |
| `tool` | One registered executable interface: arguments, effects, failures |
| `skill` | Exact instructions for using one Tool correctly |
| `agent` | An accountable executor: role, assigned Tasks, scoped Knowledge, Memory |

- Common OKF fields keep upstream shapes; application fields (`runbook`, `tool`,
  `skills`, `assignee`, `triggers`, `auto_curate`, …) live under `obsidience`. Unknown or
  imported fields (`verified`, `generated`, …) round-trip without trust; parsing is not
  admission. OKF is a document base, not an executor.
- Root `status` is document lifecycle (`draft`/`stable`/`deprecated`). Task status,
  inputs, FIFO and results live only in SQLite; execution never rewrites or re-embeds
  Articles.
- Parent Articles use `Folder/Folder.md` (never `index.md`/`log.md`). Standard Markdown
  links parsed by one CommonMark parser are edges; code, images and URLs are not.
- Outside the six types: **Source** (read-only evidence view), **Capability** (machinery
  behind one Tool at `obsidience/harness/capabilities/<dotted segments>/<leaf>.py`) and
  **Module** (a top-level product component; the Modules are listed once in the
  `Architecture/Architecture` Article). Neither becomes an Article or authority.
- Harness packages stay shallow (`interfaces/{api,cli}` with one API router per resource
  in `interfaces/api/routes/`, one level of subsystems, `capabilities/` mirroring Tool
  IDs); explicit imports, side-effect-free `__init__`, no `modules`/`utils`/`common`/`core`
  drawers.
- Accepted Articles are concise and current: no duplicate summaries, migration history,
  receipts, filler, fictional bindings or generic edges.

**Hierarchy law.** Decomposition uses one same-kind field (`subtasks`, `subrunbooks`,
`subtools`, `subskills`); acyclic. A selected descendant carries its ancestors; selecting
a parent Task includes descendants unless excluded. Only `subtasks` creates Task
hierarchy; `task.create` records causation only, and activation never authors a
definition (Generate does, via `vault.propose`). Tasks use an ordered `triggers` list
(singular `event` is legacy read-only); triggers change bindings, never identity or
acceptance. Procedural stages belong in a Runbook unless separately queueable with their
own acceptance; Task hierarchy never executes descendants in sequence.

## Work, procedure and capability

```text
Task -> applicable Runbook -> paired Skills -> Tools -> Capabilities  (+ Knowledge)
Executive conversation: Agent identity -> direct Skills -> Tools -> Capabilities
```

- Each callable `<tool.id>` has one `Tools/<tool.id>` Article and one `Skills/<tool.id>`
  titled `Using <tool.id>` with singular `tool: [[Tools/<tool.id>]]`; multi-Tool order
  belongs in the Runbook. A Skill may declare exact `requires`. Keep Obsidience to the thin
  typed, authorized, verified adapter over a maintained package where one exists.
- The code-owned Tool definition is the executable contract; Articles explain it and add
  no second call schema. Keep Article-to-Capability provenance; change adapters and
  documentation together. New Tools need an accepted pair and an explicit grant.
- A leaf Task must resolve an applicable accepted Runbook; Runbooks load only declared
  Skills. Missing or malformed links fail closed; the model never invents replacements.
  Conversational bindings cannot widen a Task's authority; Runbook `operation_tools` and
  runtime instruction sections may only narrow.
- `Agent.tasks` assigns work, `Agent.skills` is the conversational catalog,
  `Agent.knowledge`/`exclude_knowledge` scope context and grant nothing; there is no Agent
  Tool or Runbook list. Runbook `task`/`for_agent` bindings express applicability.
  Unbound `for_agent` Runbooks are read-only references: no Task, grant, prompt content
  or proposal authority.
- An assigned Task without an applicable Runbook emits `task.assigned` → Generate →
  Runbook: Darwin picks the minimal Skill subset with explicit `metadata.skills`
  (omission or catalog copying is not selection); the Task waits for Review.
- The graph shows declared dependencies (Runbook→Tools, Task→Skills/Tools, Agent→Skills)
  as derived views; displaying a related Article never assigns or grants anything.

## Agents and Knowledge organization

- **Executive** (root Agent, the Brain) interprets the owner's request, operates,
  delegates directly and returns verified results; a personal name is identity data only.
  **Alexandria** (Curator): Ingest, Curate, Merge, Link, Improve, Archive, wiki freshness.
  **Darwin** (Researcher): Question, Learn, Generate. **Heimdall** (Guardian): Audit,
  automatic Repair, operational Model characterization.
- These four core roles each have one `type: agent` Article; optional integration Agents
  use the same identity, direct Skills, Knowledge checkout and separate Memory contracts.
  The Obsidience Discord Bot is an OmniBot Agent with its own admitted member conversations.
  Merge absorbs parallel role charters. The Library is a passive catalog, never an Agent or assignee.
- Shared design: `Architecture/Architecture`; owner preferences:
  `Agents/Executive/Preferences`; procedures: `Runbooks/Operations` with exact Skills;
  configuration explanations and incident lessons: `Architecture/Shell`; project knowledge:
  `Projects`. No forced Observations, Subagents or Agent-local Architecture folders.
- Agent scope (`knowledge`, `exclude_knowledge`) applies before lexical/vector top-K,
  expansion, reads, listings, maintenance candidates and graph membership; missing
  principals fail closed; folder proxies are navigation, not permission. A checked-out
  Article is one shared identity; checkout changes are revision-checked and revocation
  stops decisions under the stale scope. Source-tree checkout only biases retrieval.
- Each Agent's Memory is its own Hindsight bank; owner inspection grants no Agent
  cross-bank access. Handoffs supply only their exact evidence.

## Activation and retrieval

Conversation and Tasks share one compiler, retrieval, ADK loop and capability core.
The visible Thinking Packet, each Article once, in order: (1) Agent identity; (2) Task and
acceptance (Tasks only); (3) immutable Objective; (4) Tool Articles; (5) paired Skills;
(6) applicable Runbooks (Tasks only); (7) bindings and exclusions, always including the
newest bounded Shell Scene or an unavailable reason (grants nothing); (8) up to five
Knowledge Articles from lexical+dense RRF (≥3 direct hits when available, ≤2 direct
neighbours); (9) history projected from the native conversation (no conversation Article).

- **Objective** = exact bound owner request, else Task title plus ordered Runbook titles;
  it drives retrieval, activity, packet and ledger and is never duplicated or shortened
  (an oversized fixed packet is rejected with its counts).
- **Search**: weighted RRF of lexical and dense lanes, filters before each top-K, one
  accepted snapshot per activation; staged, archived, temporary, expired/deprecated and
  `retrieval: false` Articles never enter as hits or neighbours. No generative expansion,
  cross-encoder or time cap; fixed Knowledge allowance; prewarmed before the API accepts
  work; degrades without widening authority. Hits are leads. Interactive Executive turns
  admit direct hits only above a dense-similarity floor (no lexical-only admission, no
  folder-index Articles as direct hits). Retrieved relations are context, not authority.
- `required_context` on accepted contracts must be checked out and current or activation
  fails. Optional Knowledge uses contiguous passages with visible offsets and omissions.
- Search may nominate a Task, but only the execution owner's accepted edges fill
  instruction, Skill and Tool slots. Never parse headings or prose to choose roles.
- Each Agent has a transient, unverified Current activation Article, excluded from search.
- **Provider serialization**: fixed identity and Tool/Skill (and Task/Runbook)
  instructions in the system message; the descriptive assigned-Task catalog (grants
  nothing) and native conversation as earlier user-data messages, conversation chunked at
  paragraph boundaries whose concatenation is exact and never becomes instructions; then
  Objective, observations, bindings and Knowledge. Fresh clock and IDs follow reusable
  context so prefix caches survive. Prior dialogue never extends authority.
- **Index**: embedding identity = model artifact + embedded text; synchronizers publish one SQLite transaction under a file lock; serialized
  SQLite with `cached_statements=0`, separate cursors per reader. Vault parsing may be
  memoized only by exact bytes plus link path; Task state, existence, checkout, expiry,
  Review and Source integrity are read fresh; no persistent role or acceptance caches.
- Every started activation emits one terminal graph event from its finalizer; late
  progress from a superseded activation cannot replace the view.

## Execution

### Executive native loop

- Chat and final speech enter the Executive's one Google ADK conversation (`execution/adk`,
  pinned in `artifacts.lock.json`). The model route is a thin ADK model
  (`execution/adk/model.py`) streaming from the local llama.cpp server under the neutral
  served model id; ADK's official `LiteLlm` (LiteLLM, hash-pinned) is the
  `adk_model_client = "litellm"` rollback and sends the same requests. Its
  identity owns standing instructions, `skills`, model and reasoning effort. ADK receives
  accepted native schemas directly: no preliminary model call, router, request
  classification, Executive Task or standing Runbook. Schema availability does not mean
  Articles were read.
- ADK owns the model/Tool loop, the conversation log and Tool sequencing; one plugin per
  activation carries the loop policy. The capability core (`execution/capability_core.py`)
  owns argument validation, receipts, no-replay, fresh target verification, observation
  witnesses, the model lease, activity, cancellation and completion acceptance. Native
  text is accepted locally by the completion authority; `task.complete` remains for
  structured failure, Review and computer-state verification and is provisional until
  finalization. Read-only failures return to the model; no identical-call heuristic or
  forced completion after ambiguous observation. Fresh observations may supersede read
  failures but never erase failed or uncertain effects.
- An empty complete stop gets one controller continuation; a second fails. Truncated,
  output-limited or partial-Tool stops get none.
- **Conversation**: one ADK session per conversation ID in `state/adk-sessions.sqlite3`;
  only New Conversation rotates it; speech lifetime is not conversation lifetime and speech
  failure never finalizes it. The log persists across restarts; an interrupted Tool call is
  recorded as outcome unknown and never replayed. SQLite is the public Chat projection,
  ingress ledger and receipt authority: the user turn is stored before execution; an
  assistant turn only for a current, completed, nonempty reply; cancelled, failed or stale
  output never becomes one; rotation never deletes rows. A conversation without a session
  is seeded from its exact public turns; runs without a conversation use an in-memory
  session for that run only.
- **Projection**: completed outcomes render as status/summary; admitted records drop once
  an outcome exists; current runtime context precedes the latest exact exchange; internal
  completion records are audit-only; execution and prewarm share the projection.
- **Window**: the provider sees the conversation from one anchor owner message on; the
  anchor moves only at an idle edge once the window outgrows its bound
  (`conversation_window`). Normal limits are six exchanges / 4K estimated tokens,
  rebasing to three / 2K with at least two exchanges. Eligible exchanges await
  confirmed native extraction; delays allow overlap through 12 / 8K before rebasing
  with an explicit missing-memory warning. The two-exchange minimum remains, so
  these are overlap thresholds, not absolute token caps. A content-free gap range
  keeps that warning until extraction is confirmed. Hindsight recall and
  `observations.recall` supply earlier context when available; no summary compaction.
- **Completion checks**: every computer Tool used needs its own verified receipt; a later
  Tool cannot conceal a failure. Unlock claims need this run's verified `session.unlock`;
  open/launch/navigate claims need verified `application.launch`, `window.activate` or
  `computer.act`; pause/stop claims need verified `media.pause` (recaps of earlier work
  allowed). Ungrounded claims return to the loop. Dispatch rejects calls outside the
  allowed set even though full schemas stay advertised.
- **Interpretation**: health → `harness.status`; visible content → `computer.observe`;
  physical surroundings → fresh camera evidence. Quoted examples, hypotheses, bare target
  corrections and withdrawals authorize nothing; a bare application name never implies
  launch or focus; unclear targets get one concise clarification. Missing evidence yields a
  factual failure, never an invented outcome. Recognized speech proves receipt of that
  utterance only.
- **Clarify** targets the active owner turn (≤8 × 2,000 characters at model/Tool
  boundaries); Objective, Task and grants are unchanged; text after closure is unapplied.
- **Lookup/delegation**: missing public facts use `web.search` (leads) and `web.fetch`
  (evidence, bound to the run) in the conversation — never a Lookup Task, `knowledge_gap`
  outcome or failure-triggered continuation. Explicit research delegates Question/Learn
  bound to the original request; arguments cannot manufacture provenance; the finding
  returns before publication unless `await_publication` was requested.
- **Notices**: known failed/reviewed outcomes produce transient notices. Accepted
  completion supplies the public summary; recorded failures use bounded, fixed
  explanations of the exact run's recorded cause and delivery uncertainty. Chat,
  speech and owner-command views share that projection, never raw exceptions or
  provider text. Notices never create successful history or change the speech
  connection. Controller failures may enter native history as explicitly labeled
  historical result data, never successful dialogue or replay authority.
  Every activation gets an explicit local clock; historical timestamps
  are not current-time evidence.
- **Finite lanes** (provider modes, never a router): a HassIL lane executes complete simple
  light and TV on/off, pause/stop and literal local-time commands as one exact ordinary dispatch
  with no model call or recall and no fabricated model span (quoted, negated, conditional,
  compound and question forms go to the model). A one-token scorer chooses among
  schema-valid complete proposals plus native generation for registered launch, unlock,
  `harness.status`, registered lights, bounded room-camera questions and an exact Article
  read after a fresh scoped search; research, compound, steered, image, prior-effect,
  failed or reasoning-enabled requests use native generation. It checks the full budget,
  served model and label distribution; probabilities are not confidence; caches hold only
  tokenizer labels.
- **Speech preparation**: after a confirmed interruption drains, the first partial starts
  one cancellable warmup on idle resident hardware with the same context and schemas,
  discarding its single token. It never runs, dispatches, publishes or writes
  conversation; final speech, Chat, STOP and teardown cancel it; leases preempt it; busy
  hardware skips it. Final admission recompiles the complete request. Standby readiness is
  reported only after preparation succeeds. With contextual speech admission, partials
  run speculative admission (below) instead of this warmup.
- **Contextual speech admission** (optional `realtime_semantic_turns`, off by default):
  an acoustic endpoint offers a provisional utterance to the same Executive and native
  Tool schema. Its actual first response begins with a private completion marker;
  incomplete speech stays in the worker and joins the next segment.
  Endpoint text checks include those held words; a noise-only VAD segment cannot
  turn them into an empty request or replace their original timing evidence.
  No public turn, native session event, Tool dispatch or memory write occurs before
  completion. A complete response binds the exact utterance, conversation/window,
  model and accepted instructions,
  then enters ADK once through its normal completion and capability authority without
  regenerating that first response. Fresh audio, STOP, mode/session changes and teardown
  invalidate owned inference. Missing/invalid markers fail closed. A 30-second abandoned
  continuation expires without execution; it is not a sentence-completion timer. A
  direct answer is handed over at its control line while it still generates: the turn
  binds, and when it consumes the answer its claim-checked sentences go to early speech
  as they arrive, before completion acceptance, as an ordinary step's would. A protocol
  break, provider failure or cancellation after that hand-off stops generation, retracts
  the early speech and fails the already recorded turn; an answer no submission takes is
  stopped by the next admission or cancellation. Native Tool calls and unfinished
  verdicts are buffered whole. The
  completion protocol's rules live in the cached Executive system prompt on every step
  and transport (no marker without a private control), and each admission request adds
  only a short trailing private control message that names the transcript and keeps the
  unfinished-turn rule adjacent, so admission, speech warms and later ADK steps share one
  system/Tool/history prefix and the verdict's uncached tail no longer re-reads the rules
  (a control appended to the owner's own message was reverted 2026-10-19: a bare "Yes"
  was answered as if it addressed the control text). Hindsight's fixed recall notice is
  in the system prompt as well; the memory message carries a short label. An
  exact HassIL command is complete by its full-grammar match and takes the reflex route
  without a model admission. Admission adopts an earlier speech partial's Hindsight
  recall for the same Agent and previous request when the request has the same words
  (case, punctuation and spacing aside) or extends the partial's words (the partial
  holds at least half of the request words' characters), without waiting for a new
  recall: the newest finished one, else a running one. Only when none covers does a
  new recall start, after the utterance's running one finishes (Hindsight completes a
  cancelled recall's work anyway, so at most one runs and none is cancelled).
  Memory then comes from that partial's text, while the model reads the final text; a
  background recall of the admitted words reports how many memories the two share
  (trace only). Standby
  preparation waits until the candidate's turn starts or the candidate ends, so it
  cannot replace the admitted request's cached tail before the turn's next step.
  **Speculative admission**: each speech partial starts (or reuses) its recall at once;
  this same admission (recall, verdict and first response) runs only at a pause edge,
  words unchanged for 0.2 s or an explicit pause edge, at most three per utterance, on
  idle resident capacity, like the speech warmup: leases preempt it, busy hardware skips
  it, exact HassIL commands skip it, and a partial with other words cancels and joins it.
  A candidate whose words still wait for a pause is admitted afresh; a miss reports
  whether the cancelled request was in flight, and the fresh admission records how
  recently (after_stale_request_ms). It publishes, dispatches and writes nothing. When the
  candidate arrives, a finished or running speculation for the same words (case,
  punctuation and spacing aside) is adopted after the live binding checks and the
  submission's validation; its prompt, Tools, model and scope bind against the turn's own
  compile when the run consumes it. The turn records the exact text the model answered.
  Otherwise it is cancelled and the final text is admitted afresh. A speculative response
  that broke the marker protocol for the same words fails closed (no second attempt).
  Standby waits while a speculation is running or unadopted.

### Specialist Task loop

- Scheduled, event and delegated Tasks use their accepted Runbooks and the same executor,
  scheduler, receipts and Review, and run on the Executive's ADK loop and plugin (one
  in-memory session per run). Each step is one native Tool call (the request requires a
  call, so the engine's grammar admits only an advertised Tool); a Tool-less reply is
  not a completion (three strikes fail the run) and only `task.complete` finishes. Tool
  results carry the remaining decision budget; a third identical call is refused before
  dispatch. Foreground demand cancels only unfinished inference.
- Each step advertises only the Tools its controller state allows, with schemas that
  follow the active proposal and completion contract and, in a Repair step, the call
  its inspected plan permits; the complete code-owned contract
  is validated before dispatch. Source-bound Learn exposes only
  `source.read` and `task.complete` until a complete matching-hash read receipt exists.
  Evidence-bound completions need explicit failed status on non-success branches; Review
  is not a terminal choice without a proposal or acceptance gate. A Curate no-change
  completion is offered as evidence only its bound Source and the Articles it has read
  in full at their current revision. Wikilinks around
  `source://` citations normalize to the Source URI.
- Model and reasoning effort are per-Task (Article or per-run owner choice, else the
  installation defaults); the Executive keeps its Agent-owned setting. The model route
  maps effort to the template thinking switch and reasoning budget. Reasoning stays
  private. Model-family templates own control tokens at the provider boundary.
- Ledger `task_ref`/`runbook_ref` columns record the actual instruction owner (Executive
  identity for conversation).

### Context accounting and provider

- Before every inference the actual templated request (with images) is counted; engines
  that support it enforce an exact input ceiling before queueing and acknowledge it, and
  the adapter fails closed without that acknowledgement (on the ADK route, the model
  client checks the acknowledgement headers of every model step and records the admitted
  count). Unavailable multimodal counts fail.
- Under pressure only older pageable `source.read`, `web.fetch` or version-attested
  `vault.read` bodies with exact reread paths may be projected; packet, Objective, receipts
  and latest observation stay complete. Only a verified pre-enqueue overflow permits one
  projected retry (prefill); on the ADK route the preflight already projected to the exact
  count, so a refusal at the guard fails closed. Irreducible overflow is rejected.
- Model steps, standby preparation and controller replies stream with pinned `httpx-sse`
  in one API-lifetime pool. Reasoning is discarded; a
  finish state is required; never reconnect or replay partial output.
- Provider metrics and phase edges are measurements only, never used for retry or
  completion.

### Computer use

- Every activation carries a bounded semantic **Shell Scene** (applications and module
  panes per Surface, awake state, grid with `grid_edges` units); compositor IDs, geometry
  and pixels stay private. No second scene graph, capture service or mutation path.
- One resolver owns targets: registered application ID (registry match needs the actual
  app_id/class), else exact app_id; panes by `pane_id`. Titles are never selectors;
  ambiguity fails closed; "what am I looking at" uses `focused`; several matches use the
  uniquely focused one or ask; an optional exact title filter (current titles verbatim)
  grants no effects.
- `computer.observe` captures one exact toplevel without focusing it; the image goes only
  to the next model message, is never persisted, and once consumed never stands in for
  current pixels. Sleeping Surfaces fail immediately and are never woken. The Harness
  refreshes the native Scene before/after capture and before using a point and waits for
  acknowledged revisions (an unrelated Surface revision rebinds only if every other target
  field is unchanged); at most one read-only recapture on `stale_scene`. No geometry
  tolerance, fixed delay or polling.
- `computer.act`: one point (0–999 grid of the preceding image) bound privately to that
  image and a one-use lease; any intervening Tool, invalid response, completion or
  cancellation discards it. The window adapter validates process start time, identity,
  geometry, image age, focus, awake/unlocked Surface, pointer and occlusion immediately
  before one action via the private virtual-pointer client; no OCR/pixel gate, point
  relocation, extra model or input daemon. Acknowledgement proves delivery only. Scope
  `input` (one attempt; acknowledged delivery + fresh post-observation) or `state` (≤3
  steps, each with a new image, visual verification) is fixed by the first call. A
  geometry-only change before any activation or pointer movement admits one fresh
  observation (`correction_allowed`); otherwise acknowledged or uncertain input is never
  replayed and other failures leave only completion. A rejected visual completion
  consumes its image. Points, pixels and leases never enter trace, Source or Vault;
  mismatch diagnostics name fields, not values. `window.drag` shares this contract.
- `window.activate` and `window.place` are separate explicit effects; exact tile success
  requires the layout's addressed-window readback; a verified no-op is reported as such.
- `application.launch` dispatches once, follows the launched unit and awaits the Scene
  readiness witness: exit before readiness fails, timeout is unverified, nothing
  authorizes replay, a repeated launch after failure is blocked. Browser URLs are optional
  launch arguments; page or playback state needs fresh observation.
- `session.unlock` exists only where the installation owner grants it (never inherited),
  invokes the fixed session-lock helper over native IPC with no caller command or password,
  dispatches once and requires fresh unlocked state. No browser-facing unlock exists.
- `media.pause`: one MPRIS Pause on the verified browser session (unique owner,
  process/start time, track), fresh Paused/Stopped readback; no toggle, start, retry,
  click fallback or tab guessing.
- `camera.observe`: one fresh frame from the selected physical camera's owner (or one
  bounded direct capture rejecting corrupt frames); ephemeral pixels; an occupied device is
  a blocker, never permission to stop its consumer; `wake: true` only for a current
  request, never replayed; no continuous observation or recording. Optional owner
  tracking keeps one stream, local face embeddings (never photos/video) and the sole motor
  connection; recognition is personalization, never authentication. Agent video feeds are
  never cameras. Optional `look` (left, right, up or down, as seen in the picture) asks that
  tracker to turn one bounded step for this request before the frame; its motor loop alone
  steers there, holds briefly so looks compose, and returns to following by itself, at
  once after a failed or cancelled capture.
- `tv.control`: one private identity-bound LAN television through upstream ADB;
  discrete power with display/wake readback, registered app launch, backend state read from
  Android services (foreground app, audio-service playback, volume/mute, media sessions, text
  input, content this Harness opened) before any screen image, which is skipped while video
  plays, bounded accessibility labels and one remote key/text action per observation.
  Intents (play content, exact volume, mute, pause/resume) are target states: read the audio
  service, act only on a difference, confirm from fresh readback, re-read before one retry.
  Keys go through a virtual remote from Android's `hid` tool, with `input keyevent` as the
  fallback. The Executive's per-turn metadata renders the last read state with its age,
  never contacting the TV while building the prompt; a private ledger keeps that state and
  recent intent outcomes across restarts. The sideloaded Obsidience TV agent
  (`obsidience/tv/firetv-agent`: an accessibility service and a notification listener, no network
  permission) answers state, the UI tree, volume, media-session transport and on-screen notices,
  and pushes state changes, over an abstract Unix socket that admits only the ADB shell user.
  The Harness reaches it through an ADB forward on the identity-verified transport, owns that one
  connection, caches its pushes for the prompt line and falls back to ADB whenever it is absent.
  The agent clicks visible skip-ad controls in known video apps (YouTube, Pluto, Tubi).
  Protected video may omit pixels while accessible controls remain available. Text requires an active
  Android text-input method; custom keyboards use visible remote navigation.
  Missing observation or text focus is correctable before dispatch; transport or
  uncertain-effect failures remain terminal. Navigation completion requires explicit
  established outcome evidence. Bounded commands,
  cancellation and no uncertain replay. Navigation delivery is not playback proof;
  app results and player evidence determine availability. No arbitrary shell or address.
- `lights.set`: precheck commissioned fixtures through one native Matter controller,
  bind node and endpoint, preserve native appearance through power changes, and verify
  fresh readback. Per-fixture receipts distinguish acknowledgment from verified state;
  uncertain effects never replay. Color and level commands explicitly request zero
  transition time. The same controller owns visualization and ordered restoration,
  with finite camera/audio measurements; optical behavior requires physical evidence.
  Matter fabric state is encrypted outside the repository. Occupancy schedules nothing.

## Scheduler, receipts and recovery

- A Task definition is not a request: each event or user turn is one `task_activations`
  occurrence with its own Objective, inputs and result; `runs` link to it; status/FIFO is
  a projection. Completed occurrences are never implicitly replayed; Review resolves the
  originating occurrence.
- Each Tool call commits intent before dispatch and an immutable receipt on return
  (identities, Tool hashes, outcome, duration, result hash). Interrupted effects, missing
  coverage, changed inputs, pending Reviews and continuations block replay; only attested
  read-only or proven-undispatched work passes restart admission. Cancellation keeps
  completed results and marks in-flight effects unknown; lease cleanup always releases. A
  failed completion cannot conceal earlier effects.
- **Admission**: count direct, scheduled and external Task identities before claiming
  capacity; never preclaim periodic work. Ready Source Inbox heads → other bound events →
  periodic work; each class chronological, per-Task FIFO intact, cron keeps its due time;
  never preempt an active Task. One fresh role resolver per tick; claim before waiting for
  the executor semaphore. Admissions, completions and foreground release wake the scheduler.
- **Foreground**: a conversation turn, accepted wake or Realtime startup closes autonomous
  admission and asks active work to yield; only the provider request is cancelled;
  in-flight Tools record receipts; the interrupted occurrence stays for explicit
  disposition and is never replayed by cron. Attested user-requested continuations stay
  eligible; idle listening reserves nothing.
- **Resources**: GPU reservations are model-runtime admission conditions checked before
  claim and inside the lease (NVML free memory plus cached fit estimates; estimates never
  justify lowering model, precision, context or offload). Only registered yieldable
  components are reclaimable. Shortfalls keep the exact occurrence waiting with its
  reason; ephemeral requests get an explicit unavailable result; denial before effects is
  not a failed run. Optional owner-enabled helper reclamation is identity-checked, once,
  never escalated.
- **Retry and settlement**: restart-interrupted event Tasks return to `pending`; owner
  Retry pins the failed run and admits only read-only/no-Tool attempts. A Task in `review`
  is not idle and `task.create` must not rerun it; Review decision and finalization are
  order-independent. Settlement never reports failed work as performed or replays a Tool:
  stale occurrences settle only via exact creator receipts with original signed argument
  spellings (`1` equals `1.0`; type substitutions or altered values stay unresolved),
  recording a no-effect receipt and advancing one FIFO head atomically. Controller
  receipts may attest that staging never began; known no-publication rejections match
  committed result hashes; a pending Review dependency blocks retry without spending it.
  Complete Tool receipt coverage may let an independent queued Curate occurrence pass
  a terminal run with an exact returned `task.create` rejection for forbidden memory-event
  delegation or mismatched scheduled maintenance candidate fields. The current Tool hash
  and complete result hash/length must match. The old run remains; no call is replayed,
  and generic errors grant no recovery.
- **Health and Repair** (event-driven; no scheduled model inspection; Check is retired):
  startup, Task completion and one inotify observer over Source and Vault drive
  reconciliation off the event loop. The status Tool and Tasks pane share one current-issue
  projection; idle terminal failures are history; failures are never rewritten. Supported
  findings activate Heimdall Repair via `harness.degraded`: passes use only
  `harness.status`/`harness.repair`, at most eight attempts, then fresh status, keyed by
  findings plus contracts so an unchanged pass cannot loop. One automatic retry per
  original Task/event/activation key, committed atomically with its receipt and never
  reset by later runs (one further attempt only for an implemented argument-contract
  correction). Repair may retain attested completed captures or settle obsolete
  commitments; a settled parent never implies downstream completion; Repair cannot retry
  itself, edit Source, alter models or approve changes. Unsupported, exhausted,
  no-progress and Repair failures become persistent Review health notifications with
  Acknowledge (which never clears the fault); they deduplicate, resolve with the fault,
  reappear on recurrence and grant nothing. `harness.rejected` enters Audit once per
  unchanged failure.
- Shutdown disarms admission at the stop signal; queued claims recheck it.
- **Trace**: one sanitized ledger trace (bounded events and bytes) with resumable cursors
  and explicit gap recovery; pixels, credentials, leases and private reasoning never enter
  trace or receipts. `harness.status` history
  findings are bounded diagnostics that never change health or prove root cause. Event
  WebSockets cancel and join sender and reader before unsubscribing.

## Knowledge intake, maintenance and Review

- **Source** is a read-only view over four roots: System (`state/system/{hardware,
  applications}`), Knowledge Markdown (`vault/`), Evidence (`evidence/`: `incoming/`
  drop folder, `raw/` captures, `inbox/` handoffs, `system/` captures) and Project Files.
  Every leaf keeps its exact path; `@view/` keys cannot invent branches. Source never
  grants trust, becomes a graph node, mutates Knowledge, collects hardware or starts
  research. Listings are ≤2,000-entry keyset pages assembled fully by clients; exact lookup
  and checkout never depend on a page.
- **System publication** is deterministic code (no model, Task or Review) at startup and
  on Refresh System: immutable deduplicated captures; one catalog derives Source labels and
  a System root with Compute, Devices, Drives (one Article per physical drive) and
  Network, plus one leaf per application. Articles cite `observed_at` evidence; `checked_at`
  is the latest success; unchanged facts keep bytes; a failed collector keeps the last
  Article and reports degraded coverage. The System namespace is reserved for this
  publisher.
- **Intake**: finished UTF-8 files in `evidence/incoming/` enter via watchdog events plus
  startup reconciliation (no polling; partial, hidden, binary, symlinked, oversized
  excluded; originals stay). A new durable Source emits `source.added` → Darwin Learn,
  which fully reads it before research and hands off one cited finding via
  `source.handoff` into `inbox/`; `source.inbox`'s sole subscriber is Alexandria Ingest
  (create/update with complete bodies). Duplicates emit nothing; Source never becomes
  Knowledge or a Review object; captures inside an occurrence bind to it. Darwin owns
  research accuracy; Alexandria integrates it. Source bytes are untrusted; `source://`
  citations are never Articles.
- `web.fetch` validates addresses, redirects and size, extracts with pinned Trafilatura
  (Markdownify fallback), batches bounded URLs, and never fetches linked pages implicitly.
  Batched reads keep per-item outcome, identity, hash and range.
- **Missing knowledge**: a small model must not guess around a gap — Executive delegates
  one bounded Question/Learn → Source → handoff → Ingest → Heimdall verification for
  consequential changes → original work retries. A proposed Tool activates only when its
  binding, entrypoint and paired Skill validate.

### Maintenance

- Families: Wiki (Ingest, Curate, Merge, Link, Improve, Archive), Research (Question,
  Learn), Generate (Tool, Skill, Task, Runbook), Harness (Audit, Repair, Model);
  `Tasks/query` for specialist queries. No per-item Task definitions.
- **Curate** runs bounded inspection and may `task.create` exact Merge/Link Tasks, which
  confirm independently; candidates exclude Agent branches and executable definitions;
  connectivity diagnostics never require linking unrelated subjects.
- **Merge** stages one distinct canonical update (body hash pinned, rechecked at Review)
  before any archive and redirects every inbound reference; archives lacking that
  evidence cannot be approved.
- **Link** adds one meaningful relationship to Knowledge/Agent bodies, never authority, as
  a first-class Link review with exact wikilink, line and endpoint revisions; drift is a
  visible warning, never a hidden rebase; missing paths never resolve to a same-basename
  Article. A rejected draft cannot justify no-change; after two identical rejected
  dispatches only completion remains. Candidates dedupe by Task, sorted refs and revision.
- **Improve** edits, categorizes, expands, retitles and splits; folder Articles plus
  native hierarchy satisfy child coverage (no per-child tables of contents);
  `missing_index` only for a real folder lacking its Article.
- **Archive** handles one deprecated or evidenced superseded Article, keeping content,
  Sources and history under `_archived/`. `stale_after` routes to Audit, not falsehood;
  activation excludes expired and deprecated Knowledge while explicit reads keep access.
- Deterministically validated routine maintenance may auto-accept; conflicts,
  destructive lifecycle, authority changes and high-risk effects need Review.

**Auto-curate** is one owner-authored `auto_curate` boolean inherited from the nearest
explicit ancestor (false opts out); Agent scopes never extend to shared Library
definitions. It is permission, not truth, and never changes triggers. Only scoped
create/update Knowledge proposals may auto-approve; identity, capability, authority,
archives, conflicts, broken links, stale bases and memory-derived changes keep Review.
Metadata, Source prose and model output cannot grant it; Reader, rings and publication
share one backend resolver.

**Review**: one unresolved proposal per Article, pinned to its base revision; stale or
overlapping proposals fail closed; updates and redirects before dependent archives
(blocked decisions disabled); queue reads share the decision lock; failed responses
reconcile by reading, never by replaying the decision; approval is atomic. The harness
derives Link vs Article class; model and UI never guess it. `vault.read` separates the
editable body from generated inbound context, which must never be copied into an update.
`vault.propose` normalizes refs (never `[[Article]].md`); update/archive need an existing
target. Missing endpoint reads are reported together and the proposal retried only after
them. Backlinks come from graph resolution; Articles cited as evidence or changed need
full current reads, unrelated hits do not.

## Historical memory (Hindsight)

- Local Hindsight behind a native Cordis port owns Memory: per-Agent banks of native
  facts, experiences and observations with entities, original dates and evidence; filters
  are presentation; memory IDs are never regenerated for presentation (the owner-approved
  2026-10-09 EmbeddingGemma 2 migration re-imported every bank once, giving memories and
  observations new IDs; old IDs survive only in history); no Article placement authority;
  native edges stay in the Memory view. Missing provider configuration fails startup,
  never falls back silently.
- Recall is bounded (automatic tighter than explicit `observations.recall`); concurrent
  queries succeed independently under one deadline. Successful results survive another
  query's failure with a compact partial notice; total failure remains model-visible even
  without hits. Unfinished requests are cancelled and joined; owner cancellation propagates.
  Failure never authorizes replay. Native settings own consolidation; reconnect preserves pauses.
- Conversation requests and Task objectives carry distinct provenance labels. Intake
  preserves both full sanitized roles within explicit bounds and rejects oversized content;
  original dates, identities and journals survive retries. External completed-turn responses
  distinguish durable insertion, duplication, withholding and disabled intake. Native
  acknowledgment (`accepted`) differs from confirmed extraction (`extracted`): the latter
  requires the exact completed parent/children and explicit error-free child outcomes.
  Diagnostic turns reserve `withheld` identities before execution when
  `memory_writeback: false`; continuations and startup recovery cannot deliver them later.
- Hindsight keeps three Executive mental models current after consolidation (owner
  preferences and permissions, workstation changes, recent decisions). A changed page
  version becomes one attested Source and one `observations.memory.ready` occurrence
  bound to the exact model id and version; Curate reads the complete page, searches
  ordinary Knowledge, fully reads cited Articles and stages ≤3 recommendations, always
  owner Review, no archives, Agent-branch edits or delegated Tasks; one outstanding page
  handoff; outputs never re-enter Hindsight. Observations are not copied into Sources.
  Bank ownership, tags and links grant nothing.
- A maintenance hold pauses delivery, memory Curate (including delegated Links) and
  recovery while the outbox keeps turns and recall stays available; completion is proven
  only by verified acceptance. Quota deadlines defer delivery and repair. Failed
  consolidation uses native recover then deduplicated consolidate, once per unchanged
  source memory, never reimport or redating. Hindsight SQL joins the caller's transaction.

## Instruction improvement

- Heimdall Audit uses pinned Google Research Harness2 for the single improvement path
  (`harness.optimize`): one sequential Propose–Probe–Compose step, width one. AutoSaddler
  V2 retains immutable candidates, parent lineage, durable attempts and an explicit
  rollback backend. Both share the existing loop, reservations, scheduler, writer and
  Review. Trials dispatch no effect and prove decision behaviour only: each call is
  answered by frozen results or the contract validator. A captured decision may first take
  up to four read-only steps (Source and Article reads, search, `vault.validate`); they are
  answered from the current Vault into the trial's own context, and the contract grades the
  call that follows them. Executive trials run the ADK loop in an isolated in-memory
  session with no Hindsight recall or writeback.
- Bounded decision inputs are captured after the actual receipt commits; rejected calls
  and failed work enter Audit's FIFO after Repair, never preempting foreground work; one
  unchanged failure admits one job. Cases are private evaluation Source, need exact
  receipt-attested inputs (empty or visual prompts never qualify) and are never full replay.
  An owner re-check may judge the instructions in force now: the captured body, found by
  hash in the Vault's audit history, is replaced as a candidate trial replaces it; other
  consulted Articles must be unchanged. Automatic admission keeps the captured instructions.
- Five distinct cases × five repetitions; automatic suites pair the rejection with four
  accepted controls from other runs (never duplicates; waits visibly when short); rubrics
  are the actual validators; unsupported contracts and code defects are explicit findings.
  A job is admitted for a run's last rejection only; a run that ended in a Tool-contract
  dead end (a partly read cited Article, no dispatchable call, the output limit) is
  recorded as an implementation finding and admits no job.
- Candidates change only Agent/Runbook bodies, by replacing one whole paragraph or list
  item or adding one after it (a hard-wrapped sentence never crosses those units).
  Repetitions are independent samples, so cases compare by pass counts: the candidate must
  pass every training trial, at least four of which the baseline failed; the controls must
  not pass less often in total, nor any one of them by two or more repetitions, nor average
  over half a Tool call more. Controls the baseline mostly fails cannot show a regression,
  so the candidate must itself pass at least three quarters of the control trials. The
  final composed candidate receives independent full baseline/candidate measurements;
  Harness2 selection never proves improvement. The latency bound applies only to Executive
  at reasoning `none`. Only training evidence enters search or reflection. Lessons are
  bounded private optimizer artifacts retained after committed publication and its exact
  Audit receipt; cases freeze compatible lessons, dependency Articles, model, backend and
  implementation identity. Session, trial and job budgets survive resumption. The retained
  AutoSaddler backend ends its search at the first accepted candidate.
  Publication revalidates inputs, code, model and the returned receipt; owner-set
  `Tasks/audit` `optimization_auto_apply` (default off) may publish instruction bodies
  automatically; metadata, grants, model configuration and code always keep Review. Never
  call `run_task` for trials or add a second provider or scheduler; this is not code repair.

## Models and hardware residency

- Hardware is independent component slots; persisted owner selections beat code
  fallbacks. A Task lease displaces only overlapping components and restores the saved
  selection; STOP releases leases without loading defaults. Never substitute models or
  reduce context, precision or resources; layers never spill to CPU unless an
  owner-approved profile allows it. Switch Executive models via Article Review plus
  Hardware assignment, never by overwriting live state. Health requires the expected served
  model ID.
- `model.added` (existing entries baselined) activates Heimdall's Model Task:
  `model.inspect`, `model.source` (immutable manifests; weights never copied),
  `model.benchmark` (leases and restores), `model.configure` (smallest measured change);
  committed settings or measurements survive cancellation.
- Benchmarks: same prompt, 256-token ceiling, temperature 0 where supported, one discarded
  warmup, three samples; TTFT = median dispatch-to-first-public-output; tok/s = total
  completion tokens / total wall time. Secondary timings never replace them.
- Models lists Task reasoning models only; Settings → AI & Voice owns residency and
  microphone, speaker, camera and voice choices, never system defaults. Hardware
  monitoring is read-only, visible-pane only, no daemon; telemetry never assigns.

## Realtime

- Realtime is speech connection infrastructure, never a Task, Runbook, Agent, planner,
  verifier, memory, model selector or second reasoning path. Final transcripts enter the
  same Executive session as Chat. Pipecat `LocalAudioTransport`, NeMo turn taking with
  Nemotron streaming ASR on its reserved GPU, Pocket TTS on CPU; one worker, one
  conversation; no browser audio, audio WebSocket, custom capture/playback or UI microphone.
- Chat owns the mode controls (Wake word default, Realtime, Mute) and live transcript.
  The wake word is the Executive title; no text before it is admitted or stored. Mode
  changes drain and reject old revisions; the mode persists per login (a failed restore
  reports, no retry loop) and never becomes conversation, Task or Knowledge state.
  An address starts a speech segment or follows a 0.4-second gap in recognized
  words, optionally after hey/ok/okay. This recognition-gap heuristic governs wake
  admission, not acoustic endpointing or semantic completion. A trailing bare name
  waits up to 0.35 seconds for continuation; possessives remain rejected.
- NeMo owns acoustic turns and interruptions; confirmed speech interrupts before
  endpointing. In Realtime mode a Silero onset over a reply only ducks it (-15 dB) at
  once and holds it after 0.5 s of speech; recognized words commit the interruption as
  before, and 1.5 s of quiet without them resumes the reply where it was held, at most
  4 s of hold (owner decision 2026-10-19; off switch `realtime_barge_in_ducking`).
  With contextual admission enabled, its endpoint supplies a candidate,
  and the Executive's completion verdict plus an exact worker acknowledgement admits
  the final turn. VAD also invalidates pending semantic verdicts immediately. Otherwise,
  only final transcripts start work. Never end a turn on missing ASR words while VAD
  hears speech. Inference
  runs in one awaited worker thread; local NeMo patches are recorded and reapplied.
- Wake listening reserves the STT device with a yield callback (conflicting work drains it;
  release restores it); Realtime keeps a hard reservation; never wait indefinitely for
  voice.
- Echo cancellation references the selected speaker monitor: a supported DSP microphone
  owns its reference links through one native PipeWire client, others use the WebRTC
  module; reference failure is explicit, never a silent fallback. Streams forbid device
  fallback; event-driven device loss cancels the turn and drops readiness; a complete new
  endpoint permits one reacquisition. Silent clocked PCM is valid at startup. Devices and
  voice freeze at start. A camera that is the selected microphone is power-coupled to
  Realtime; otherwise not.
- Pocket is serialized; cancellation stops the producer and drains cleanup; synthesis
  failure is a delivery error that never erases the reply. Completion needs the ordered
  terminal marker after the last PCM write.
- Cues (installation clips; missing clips are silent): no processing clips or timers;
  the one exception is a spoken "On it." when a voice turn's Tool is still running after
  1.5 s (or a usually slower Tool starts): once per run, never over the owner or after
  reply audio began; it opens the reply, so the answer queues behind it (owner decision
  2026-10-19). Command text suppresses an unstarted opening chirp, while a started chirp finishes.
  STOP, mute, mode change and shutdown cancel. Code, not model
  wording, replaces spoken confirmation with a completion chirp for receipt-verified
  reflex effects, and for a short single voice command whose one effect Tool returns a
  verified receipt: the controller settles it and ADK's `skip_summarization` ends the turn
  without a closing model step (owner decision 2026-10-19). Failures, uncertain effects,
  informational results and compound or questioning requests stay spoken; failures and
  uncertain effects never chirp success. In wake mode a
  completed spoken reply that ends in a question, once its last audio is written, opens the
  command window as the name said alone would: the ready chirp replaces the completion
  chirp, and silence closes it the same way.
- Executive voice turns may speak each complete sentence of a model step that has emitted
  no Tool call before completion acceptance, once it passes the completion's own
  unsupported-claim check (owner decision 2026-10-08). A later Tool call or rejected
  completion stops that audio; acceptance speaks only the unspoken remainder. Chat text,
  persistence and cue rules are unchanged.
- The PCM envelope drives only the Executive orb; one `ShellApi` subscribes to
  `/ws/realtime`; no polling.

## Shell and Surfaces

```text
Linux services -> Hyprland -> adapter/hyprland -> Shell API -> one Quickshell host -> panes
```

- Hyprland owns composition, outputs, windows, input, VRR, fullscreen and XWayland; Linux
  services stay upstream plumbing. New OS responsibilities arrive only as Module slices
  with rollback; the Shell README's package policy is additive (omission never removes).
- Only the compositor adapter talks to Hyprland; it separates observation from validated
  commands and holds no retrieval, reasoning, presentation or Task logic. Shell events
  trigger only Tasks that declare them.
- greetd starts one UWSM Hyprland session; one Hyprland owns every output; one Quickshell
  host serves all Surfaces. Predecessor desktops, Xorg hosts, bridges and Electron are
  archive-only. A failing pane, model or graph never ends the session; basic desktop
  functions work without models; an independent terminal is the recovery path.
- A **Surface** is a presentation endpoint for one physical display workspace, not an
  Article, Tool or `wl_surface`; output mapping and tile grids are installation config.
- **Panes**: `PaneWorkspace` owns module definitions, Reader docking and one
  `PanePlacement` per pane (`pane_id + surface_id + local_rect + open + tile_bounds`).
  Each undocked module is one `FloatingWindow` identified only by initial app ID
  `io.obsidience.shell` and title `obsidience-pane:<pane_id>`. A new Wayland address gets
  one exact tile restore before observation; afterwards compositor geometry is truth; a
  failed restore leaves the record. Reload, teardown or compositor restart is never a user
  close. External applications are native clients, never embedded or mirrored.
- **Windows**: Hyprland's `lua:obsidience` layout is the sole focus, z-order, chrome,
  move/resize, `Alt+Tab` and tiling authority; focus is click-driven. One Surface-local
  grid (`SurfaceLayout`, Settings → Workspace); tile bounds are non-exclusive coordinates;
  5 px gaps stay compositor hit targets. `Meta+Arrow` resizes tiles, `Ctrl+Meta+Arrow`
  translates, `Meta+Shift+Arrow` moves to the nearest mapped Surface, `Meta+Esc` closes;
  each sends one token-bound request pinned to the live active address. Title bars use the
  standard interactive move. No modifier drag, button interception, wrapper, second focus
  service, mixed focus ring, QML drag/z-order authority, shared canvas or second placement
  authority.
- **OLED motion** (optional, off by default): bounded dephased seam drift and slow
  border/glow rotation advanced by one one-second compositor timer, writing only on
  rounded changes; panes on a seam share it; outer edges fixed; frozen without catch-up
  when fullscreen, locked, off or hidden. Only policy persists. No GIF decoder, per-pane
  timer, daemon, plugin, full-screen effect or second geometry store.
- **Input**: one compositor truth projected in Settings → Input; never per-Surface scaling,
  a second profile store or pane-issued compositor commands.
- **Lock**: the Quickshell `LockController` (one `WlSessionLock`, one `PamContext`, PAM
  `obsidience`) is the sole locker; outputs are opaque `#02060c`; only the
  `graph_surface_id` Surface shows the graph as decoration that never sees credentials;
  the prompt waits for a secure lock. Panes and the paused graph stay resident, never
  unmapped or rebuilt. `allow_session_lock_restore` lets a replacement host reclaim a
  fail-secure lock; the restart helper refuses while locked or locking. Pinned host patches
  live under `adapter/quickshell`. No Hyprlock, gtklock or second locker; greetd owns only
  fresh login; `hypridle` triggers lock and DPMS (security listeners ignore app
  inhibitors; no suspend).
- **Commands**: graph pages and panes send typed commands (`pane.present`, `pane.select`)
  over the loopback `obsidience.shell.v1` WebSocket with the host's per-start token; the
  server validates an allowlist and broadcasts `pane.state`. The API admits only loopback
  same-origin requests; Vault path traversal is refused.
- **Reader** is the single Article/Source viewer (native Qt Quick; no web Reader or second
  loader) with four dock slots and one atomic dock record; detaching maps exactly one
  window. **Terminal** is the sizing owner of the persistent `obsidience-ui` tmux view.
  **Settings** is one sectioned pane. One pane per function, no duplicate pane, graph or
  Reader; the Camera pane is video-only. One Shell palette, flattened into compositor and
  application theme contracts.

## Graph and UI projection rules

- The UI is a thin projection: no invented kinds, copied claim catalogs, static ontology,
  trust rules, second scheduler, memory store, hidden activation path or duplicated
  name/subject dictionaries. `/api/graph.navigation` is the sole naming contract; display
  aliases carry exact `article_ref`s; display edges and shortcuts never enter retrieval or
  authorization; body mentions never create capability shortcuts.
- **Presenter**: one Quickshell/QtWebEngine stage owns every renderer and simulation (one
  Three.js + `d3-force-3d` implementation); pane viewers receive WebRTC frames and own no
  scene. Its lifetime is the Shell session (a Harness stop never stops it); failed initial
  loads retry once per connected-backend interval; no restart loop; mutable HTML is
  `no-cache`. Page load is not renderer acceptance. `graph_surface_id` selects the
  Executive graph Surface.
- **Views**: Knowledge, Memory (Hindsight native) and Code (codebase-memory-mcp) share one
  Graph pane (`knowledge-graph`; `pane.select` switches). Provider edges never become
  Article relationships or permissions. Specialists orbit the Executive; the Library is
  never a satellite. All families share the node/label shaders; viewers replace whole
  frames and release buffers on last disconnect.
- **Layout**: one shared cloud implementation; Brain pinned; automatic radius; Branch
  clearance is the sole slider. Refreshes keep positions, velocities and cooling unless
  physical inputs change; status, labels, paint and settings never reheat. No fixed
  sectors, bearings, named-branch cases or second solver clock. Links follow their shells
  between exact endpoints. Pending Link previews exist only in the Scene; rejection removes
  only that preview; never restore an old whole-graph snapshot. Memory is an organic
  chronological tube; Code anchors its project and never displays layout fallbacks
  as relationships. Proximity never attests a relationship.
- **Thinking animation** ignites and labels exactly the supplied packet and Tool-return
  refs. Ancestors and the Articles one link from a supplied one are passed, not consulted:
  the beam reaches them and they glow visibly softer, unlabelled; nothing lights beyond
  that one link. Tool/Skill glow means instructions supplied, not called.
  Activity comes only from context supplied, Tool dispatch/results, intentional Reader
  loads, committed writes and Review outcomes, never hidden reasoning; "returned" is not
  real-world success. Speech holds the packet through
  playback; a finished route lingers six seconds, then fades; STOP clears it. Operations are presentation, never replay
  authority; never infer completion from animation.
- **Code activity** observes public coding-agent MCP call/result records and file changes,
  emitting only fixed labels and returned identities, never reasoning, messages,
  arguments, source or output. Memory recall lights actual returned IDs.
- The **thinking popup** projects the public trace with exact run/call pairing; metrics
  attach only to the same run and step; no second trace store or polling.
- Hidden, locked or reduced-motion stages pause and never catch up; idle motion is
  display-only and rate-capped.

## Definition of done

- The Vault validates with no broken load-bearing edges; every Tool has one paired Skill,
  exact binding and entrypoint; filesystem, Source, graph, Reader, Library and Tasks agree.
- Affected code compiles/builds (UI typecheck and build for UI changes); only affected
  services restarted; the affected interface and endpoints observed working. Physical
  desktop behaviour is accepted by the owner, never claimed by an agent.
- Accepted text claims no predecessor architecture or Tool without its real binding.

## Retired (do not restore)

Connections/Feeds (panes, API, collector, publication/retention, `web.feed`), Distill,
News/Top Stories, Check, Lookup, Executive Task/Runbook, request classification and the
packet router, Compact/Promote, Immediate/Temporary/Workstation Observations, custom
Hindsight categories, the WebKit presenter, PaneCanvas, processing cues, the layered graph
engine, KWin paths, Xorg bridges and Electron. The Generate-refinement evaluation path with
`harness.evaluate`, the `review.inspect` and `task.inspect` Tools, the synthetic
`@library/Skills` graph mirror and the automated test suite (new tests only on owner
request) are retired (2026-10-15). The DeepSeek Harness Executive loop (Node
child, npm Cordis composition, JSONL sessions; replaced by ADK 2026-10-09) and
conversation compaction (idle, manual Compact and its threshold) and the specialist
Python decision loop (provider-constrained JSON `{tool, args}` actions; replaced by the ADK
loop 2026-10-09) are retired. Historical Sources, receipts and rows remain
read-only provenance and never resume collection or replay work.

## References (patterns only)

[Cordis primer](https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/docs/cordis-primer.md)
and [composability paper](https://arxiv.org/abs/2608.25512);
[WeKnora dsh-weknora](https://github.com/Tencent/WeKnora/tree/1ef38fdb8b19347b82d3a99f6f17d75ac09ad606/packages/dsh-weknora)
(its answer pipeline deliberately unused);
[Hindsight practices](https://hindsight.vectorize.io/best-practices);
[Gemma 4 formatting](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4);
[Graphify](https://github.com/Graphify-Labs/graphify/tree/33362d969292b57eda82f3fbd9eb5f3f5bc9bbc2)
(relationship evidence, connectivity, reconciliation); Omarchy Aero Snap. Code is imported
only when recorded in `artifacts.lock.json`; a coding agent's code index grants nothing.


## Optional Discord integration

An explicit private installation consent attestation may separately enable local
per-member original voice samples in the Discord transport's own private state
directory. This opt-in dataset has bounded chunks, async writes and quotas,
excludes diagnostic streams, and gives each member native self-service status,
stop, start and deletion controls. It never enters Knowledge/Hindsight or changes
the shared speech model, TTS or voice identity.

`obsidience/discord` owns the official bot Gateway, voice receiver and audio players.
It uses a private configuration and systemd credentials, restricts itself to one configured
guild, and connects to voice only when explicitly asked. Bard is this installation's
public display name; the internal identity is `Agents/Discord/Discord`, the Obsidience
Discord Bot with role OmniBot. Additional bot features require implemented paired
Tools/Skills and an explicit Agent grant.

The Harness admits authenticated observed guild/channel/member identities into a dedicated
Discord conversation ledger. The native ADK loop, model leases and capability receipts are
shared infrastructure. Its context carries no Executive conversation, Shell Scene, private
Knowledge or Memory. The Agent checks out its own shared Media knowledge leaf. Discord
members are external speakers, never inferred workstation owners. Only accepted bot replies
and their attributed requests enter that Agent's separate historical Hindsight bank.

The existing speech owner accepts per-member PCM through an owner-only socket. Decoder,
VAD, wake and follow-up state are member-scoped; loaded NeMo and Pocket models and inference
locks stay shared. The first addressed Bard wake claims the channel until its reply
has drained. Other members' audio is not admitted to that request. Unaddressed audio/text
stays ephemeral. Muting the desktop input can retain the same sole worker in a mode with
no desktop microphone, AEC, output transport or Executive speech attachment. The same
mode retains Discord speech while desktop audio awaits hardware reconnection; the desired
desktop mode and hardware error remain visible. Reconnection drains that worker and its
model lease before reacquiring desktop transport. Dependency loss cancels pending work; a later voice event can reconnect without replaying it.
While that member owns a command, reply or native question-follow-up window, a
content-free speech ownership event defers optional Executive standby prefill. Desktop
wake, partial-speech preparation and foreground requests remain available. Native release
or worker teardown restores standby eligibility. Outgoing PCM fills the existing 400 ms
Opus prebuffer as soon as synthesis supplies it, then paces with that bounded lead.
The owner socket can exclude one specified member's next voice turn from Memory for
a 30-second diagnostic window; default requests retain their normal Memory policy.
Complete addressed control phrases use the existing short-reply endpoint after a
judged quiet pause. The final transcript carries bounded source timing stages,
so ASR, endpoint, dispatch and playback delays remain distinguishable; partial
recognition never dispatches an effect.

Bard uses a direct media-command path for exact pause, resume and stop requests, and
for unambiguous artist or recording matches from one fresh search. Explicit known
genre requests use the first finite recording whose returned title names that
genre; artist/title ambiguity still uses the Agent. Those requests
execute the accepted capabilities and completion checks without model generation or
Memory recall. Ambiguous requests enter the ordinary Agent with the actual search
results; they do not search twice. Successful voice playback uses a brief handoff
while retaining the full title in history; the final speech frame releases music.
The observed spoken play/plate confusion is corrected only for addressed voice
and requires a unique fresh recording match; unmatched corrections ask for
clarification. The exact spoken artist homophone "the weekend" maps to
"The Weeknd" in voice music slots and still requires fresh verified artist
metadata; general spelling hints are not automatic matches. Artist-owned collaboration credits and lyric-video presentation
labels may be removed for exact title matching, without accepting cover/version
substitutions or deriving performer identity from unrelated lyric publishers.
Follow-up choices reuse only the latest native search receipt in that member's
bounded conversation window. Media issues new turn-local selections under current
configuration; the Agent selects the requested offered recording from those identities.
No prior selection grant or expiring stream URL is reused. A new search replaces
the choices; a literal refusal consumes the offer with an acknowledgment and no
media effect. Successful playback of rebound choices retains its artist evidence
for explicit continuation. Attempted playback consumes choices. Three identical correctable
pre-dispatch rejections end the Discord turn; a genuinely corrected call still runs.

An explicit keep-playing request enables a member-bound continuous music mode in
the existing Discord player. It prefetches one fresh Media identity while the
current song plays and advances only after clean decoder end-of-file. It keeps
at most twenty recent identities to avoid immediate repeats. No additional Agent
turn or Memory write occurs between songs. Pause suspends selection and resume
continues the same track; stop, leave, requester departure, manual replacement
and playback failure cancel the mode and its owned work. Disabling only the mode
lets the current track finish. The authenticated metadata endpoint checks the
live transport generation, mode and member binding; Node rechecks them after
awaiting selection. Media remains the source authority, and the existing player
owns source extraction, decoding and output. Continuous playback is never enabled
by default.

Media catalogue selection and source admission remain owned by Obsidience Media. The bot
receives a held descriptor with exact file identity and a finite dispatch deadline, then
opens its own descriptor for FFmpeg audio playback. Shared music search admits native
Jellyfin Audio or exact public YouTube identities, prioritizing official recordings
and excluding unrequested named variants, positively identified live streams and
results without a known finite recording duration
without substituting another service. Whole verified-channel artist relevance ranks
ahead of presentation labels; a unique close spelling is an Agent-visible hint,
never an exact automatic recording match. Online playback uses an explicitly
configured direct best-audio route or the existing TorBox web-download service. Search
is read-only; an explicit play can prepare its exact public source once, with pending
and uncertain receipts distinct from playback. Expiring CDN URLs stay inside the
private owner handoff and provider child stdin, never model context, argv or logs.
The destination owns provider/decoder lifetimes and bounded streaming backpressure.
Replacement sources remain pending until an actual encoded audio packet is ready;
failed preparation preserves the previous player, paused position and continuous
mode. The music player's starvation bound covers the native downloader's existing
five-second timeout and two retries, with one second of scheduling margin. An
idle transition before decoder EOF is reported as a stream failure, not a song ending.
YouTube HTTP transport gets at most two native retries of the same source. After
output begins, resumed byte ranges must match before their response body is read;
missing/backward ranges and native restart-from-zero fallbacks fail closed. No
player restart or fresh source extraction is implied. Before any stdout write
has even been attempted, an anonymous download-time 403 may use the existing
YouTube account for one fresh extraction of the same recording. Metadata requiring
sign-in uses that same single account attempt. Best-audio selection and native
availability waits remain intact, with at most two reported waits totaling sixty
seconds. No account fallback is allowed after partial or uncertain output.
Failures retain only fixed
categories, phase and numeric byte counts, never upstream messages or CDN URLs.
A failed or uncertain dispatched Discord effect ends that activation's effects
and requires failed completion; failed play/resume receipts cannot support an
affirmative playback claim. Proven correctable pre-dispatch non-effects remain
correctable within the existing bounded command path.
Cancellation addresses the original
play request, never a newer item. Current bot delivery is audio only; a soundtrack is not
an acceptable implicit substitute for requested television/video. The implementation does
not supply a supported bot camera/Go Live sender.

The bot camera presentation projects the canonical accepted Discord Agent graph with
opaque public IDs and run-correlated activity. It reuses the Executive graph renderer
and its thinking routes. Public events contain no queries, conversation, reasoning,
Tool arguments/results, source paths, other Agent scopes or general trace stream.
A separate local virtual camera can expose this dedicated surface to an ordinary
Discord client; it is not a bot-token video sender.

Navigation declares scene membership separately from Agent registration. The Discord
Agent belongs to its independent scene; Executive satellites and activity exclude it.
The Library retains its identity for ordinary management and Review.
