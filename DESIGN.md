# Obsidience design

Older dated design notes are archived locally by the installation; consult the archive before reviving a retired design.

Current design as of 2026-10-08, each rule stated once. This file is published:
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
  and licenses in `artifacts.lock.json`. No generic framework or language migration.

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
  **Module** (Harness, Shell, UI, Vault, Tests). Neither becomes an Article or authority.
- Harness packages stay shallow (`interfaces/{api,cli}`, one level of subsystems,
  `capabilities/` mirroring Tool IDs); explicit imports, side-effect-free `__init__`, no
  `modules`/`utils`/`common`/`core` drawers.
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
  automatic Repair, operational Model characterization, Runbook evaluation.
- Exactly these four have one `type: agent` Article each; Merge absorbs a parallel role
  charter into it. The Library is a passive catalog, never an Agent or assignee.
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

Conversation and Tasks share one compiler, retrieval and CapabilityDispatch.
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

- Chat and final speech enter the Executive's one native DeepSeek Harness session
  (pinned in `artifacts.lock.json`). Its identity owns standing instructions, `skills`,
  model and reasoning effort. DeepSeek receives accepted native schemas directly: no
  preliminary model call, router, request classification, Executive Task or standing
  Runbook. Schema availability does not mean Articles were read.
- DeepSeek sequences model/Tool steps; the capability owner keeps argument validation,
  receipts, fresh target verification, cancellation and completion acceptance. Native
  text is accepted locally by the completion authority; `task.complete` remains for
  structured failure, Review and computer-state verification and is provisional until
  finalization. Read-only failures return to the model; no identical-call heuristic or
  forced completion after ambiguous observation. Fresh observations may supersede read
  failures but never erase failed or uncertain effects.
- An empty complete stop gets one controller continuation; a second fails. Truncated,
  output-limited or partial-Tool stops get none.
- **Conversation**: one native session per conversation ID; only New Conversation rotates
  it; speech lifetime is not conversation lifetime and speech failure never finalizes it.
  Upstream JSONL persistence resumes after restart; native recovery never replays an
  interrupted Tool. SQLite is the public Chat projection, ingress ledger and receipt
  authority: the user turn is stored before execution; an assistant turn only for a
  current, completed, nonempty reply; cancelled, failed or stale output never becomes one;
  rotation never deletes rows. The child uses private pipes and keeps no durable files.
  Old stores upgrade only offline; never import over a successor or rewind receipts.
- **Projection**: completed outcomes render as status/summary; admitted records drop once
  an outcome exists; current runtime context precedes the latest exact exchange; internal
  completion records are audit-only; execution and prewarm share the projection.
- **Compaction**: upstream `dsh-compaction-basic` through the model lease, no Tool
  dispatch or speech; bounded recent tail and summary; summaries need nonempty Goal,
  Constraints and corrections, Verified state and Outstanding; failed, empty, truncated or
  Tool-unbalanced summaries are rejected and originals stay recoverable; threshold is a
  60–90% setting. A summary is history, not verified state; an unavailable estimate alone
  cannot start compaction.
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
- **Notices**: known failed/reviewed outcomes produce transient notices; only accepted
  completion supplies their summary; notices never create successful history or change the
  speech connection. Every activation gets an explicit local clock; historical timestamps
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
  discarding its single token. It never runs, dispatches, publishes, writes conversation
  or compacts; final speech, Chat, STOP and teardown cancel it; leases preempt it; busy
  hardware skips it. Final admission recompiles the complete request. Standby readiness is
  reported only after preparation succeeds.

### Specialist Task loop

- Scheduled, event and delegated Tasks use their accepted Runbooks and the same executor,
  scheduler, receipts and Review. Each response is one provider-constrained JSON action
  restricted to authorized actions, with bounded finish/parse diagnostics; no
  Task-specific parsers.
- Decision schemas follow each proposal contract. Source-bound Learn exposes only
  `source.read` and `task.complete` until a complete matching-hash read receipt exists.
  Evidence-bound completions need explicit failed status on non-success branches; Review
  is not a terminal choice without a proposal or acceptance gate. Wikilinks around
  `source://` citations normalize to the Source URI.
- Model and reasoning effort are per-Task (Article or per-run owner choice, else the
  installation defaults); the Executive keeps its Agent-owned setting. Reasoning stays
  private. Model-family templates own control tokens at the provider boundary.
- Ledger `task_ref`/`runbook_ref` columns record the actual instruction owner (Executive
  identity for conversation).

### Context accounting and provider

- Before every inference the actual templated request (with images) is counted; engines
  that support it enforce an exact input ceiling before queueing and acknowledge it, and
  the adapter fails closed without that acknowledgement. Unavailable multimodal counts fail.
- Under pressure only older pageable `source.read`, `web.fetch` or version-attested
  `vault.read` bodies with exact reread paths may be projected; packet, Objective, receipts
  and latest observation stay complete. Only a verified pre-enqueue overflow permits one
  projected retry; irreducible overflow is rejected.
- SSE via pinned `httpx-sse` in one API-lifetime pool; only real deltas renew the
  inactivity deadline; reasoning is discarded; a finish state and end marker are required;
  never reconnect or replay partial output.
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
  never cameras.
- `tv.control`: one private identity-bound LAN television through upstream ADB;
  discrete power with display/wake readback, registered app launch, backend state read from
  Android services (foreground app, audio-service playback, volume/mute, media sessions, text
  input, content this Harness opened) before any screen image, which is skipped while video
  plays, bounded accessibility labels and one remote key/text action per observation. Media
  keys verify their effect from the audio service. The Executive's per-turn metadata renders
  the last read state with its age, never contacting the TV while building the prompt.
  Protected video may omit pixels while accessible controls remain available. Text requires an active
  Android text-input method; custom keyboards use visible remote navigation.
  Missing observation or text focus is correctable before dispatch; transport or
  uncertain-effect failures remain terminal. Navigation completion requires explicit
  established outcome evidence. Bounded commands,
  cancellation and no uncertain replay. Navigation delivery is not playback proof;
  app results and player evidence determine availability. No arbitrary shell or address.
- `lights.set`: precheck every fixture, durably save appearance before OFF and restore on
  ON, one write per fixture with bounded readback (ACK is not status), never replay,
  per-fixture receipts, group success only when all verify; occupancy schedules nothing.

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
  trace or receipts; `task.inspect` keeps original/omitted counts. `harness.status` history
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
  are presentation; memory IDs are never regenerated; no Article placement authority;
  native edges stay in the Memory view. Missing provider configuration fails startup,
  never falls back silently.
- Recall is bounded (automatic tighter than explicit `observations.recall`); failure never
  authorizes replay. Native settings own consolidation; reconnect preserves pauses.
  Conversation requests and Task objectives carry distinct provenance labels; original
  dates, order and journals are preserved. Diagnostic turns set
  `memory_writeback: false` and are never delivered later.
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

- Heimdall Audit uses pinned Microsoft AutoSaddler V2 as the single improvement path
  (`harness.optimize`), sharing the existing loop, reservations, scheduler, writer and
  Review. Trials intercept every Tool before dispatch and prove decision behaviour only.
- Bounded decision inputs are captured after the actual receipt commits; rejected calls
  and failed work enter Audit's FIFO after Repair, never preempting foreground work; one
  unchanged failure admits one job. Cases are private evaluation Source, need exact
  receipt-attested inputs (empty or visual prompts never qualify) and are never full replay.
- Five distinct cases × five repetitions; automatic suites pair the rejection with four
  accepted controls from other runs (never duplicates; waits visibly when short); rubrics
  are the actual validators; unsupported contracts and code defects are explicit findings.
- Candidates change only Agent/Runbook bodies; all cases must pass, training improve and
  Tool counts hold; the latency bound applies only to Executive at reasoning `none`.
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
- NeMo is the sole turn/interruption owner: provisional VAD is presentation; confirmed
  speech interrupts before endpointing; only final transcripts start work; NeMo's stop edge,
  never a visible transcript, ends the user's turn. Keep the 700 ms pause allowance; never
  end a turn on missing ASR words while VAD hears speech. Inference
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
- Cues (installation clips; missing clips are silent): no processing clips or timers; a
  started ready chirp finishes; STOP, mute, mode change and shutdown cancel. Code, not model
  wording, replaces spoken confirmation with a completion chirp for receipt-verified
  reflex effects; failures and uncertain effects never chirp success.
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
  with rollback; `system-packages.toml` is additive policy (omission never removes).
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
  chronological tube; Code anchors its project and never displays layout fallbacks as
  relationships. Proximity never attests a relationship.
- **Thinking animation** shows exactly the supplied packet and Tool-return refs: never
  expand through adjacency; cross-links only between endpoints of the same original group;
  ancestors carry beams only; Tool/Skill glow means instructions supplied, not called.
  Activity comes only from context supplied, Tool dispatch/results, intentional Reader
  loads, committed writes and Review outcomes, never hidden reasoning; "returned" is not
  real-world success. Speech holds the packet through
  playback, then fades; STOP clears it. Operations are presentation, never replay
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
engine, KWin paths, Xorg bridges and Electron. Historical Sources, receipts and rows remain
read-only provenance and never resume collection or replay work.

## References (patterns only)

[Cordis primer](https://github.com/deepseek-ai/deepseek-harness/blob/c291e7961a515f6d7af9304e7fd1d257929aef26/docs/cordis-primer.md)
and [composability paper](https://arxiv.org/abs/2608.25512);
[WeKnora dsh-weknora](https://github.com/Tencent/WeKnora/tree/1ef38fdb8b19347b82d3a99f6f17d75ac09ad606/packages/dsh-weknora)
(its answer pipeline deliberately unused); [ADK compaction](https://adk.dev/context/compaction/);
[Hindsight practices](https://hindsight.vectorize.io/best-practices);
[Gemma 4 formatting](https://ai.google.dev/gemma/docs/core/prompt-formatting-gemma4);
[Graphify](https://github.com/Graphify-Labs/graphify/tree/33362d969292b57eda82f3fbd9eb5f3f5bc9bbc2)
(relationship evidence, connectivity, reconciliation); Omarchy Aero Snap. Code is imported
only when recorded in `artifacts.lock.json`; a coding agent's code index grants nothing.
