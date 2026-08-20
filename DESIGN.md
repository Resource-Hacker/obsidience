# Obsidience — the knowledge graph *is* the harness

Dev-build design doc (v1). Parallel experiment to the Hermes-plugin conversion:
this side bets on **pure graph-native**: one vault, one small interpreter, no
agent framework underneath.

## The four authoring primitives

The vault exposes exactly four primary authoring primitives. Nothing else is
architecture; everything else is either knowledge (notes) or runtime state.

| Primitive | Question it answers | Folder | Links |
|---|---|---|---|
| **Task** | *What* needs to be accomplished | `Tasks/` | `subtasks:` (ordered, recursive), `runbook:` (leaf tasks) |
| **Runbook** | *How* a task is completed — sequencing, branching, verification, recovery | `Runbooks/` | `skills:`, optional extra `tools:` |
| **Skill** | How to use one or more tools *correctly* — parameters, safety rules, interpretation, failure handling | `Skills/` | `tools:` |
| **Tool** | The executable capability itself | `Tools/` | `binding:` → a registry implementation |

- **Tasks are recursive.** A task either has ordered `subtasks:` (a container —
  its subtasks are how it completes, no runbook needed) or it is a leaf and
  **must** link a runbook. Missing runbook → `blocked/awaiting-runbook`, never
  improvised.
- **Runbooks are procedural.** Imperative steps with stop-and-report
  conditions. They name the skills they need; they never explain tool usage
  inline — that's what skills are for.
- **Skills are reusable tool knowledge.** One skill can cover several tools;
  several runbooks can share one skill.
- **Tools are executable.** A Tool note documents and *binds* a capability
  implemented in the harness registry (`binding: builtin:vault.read`). Screen
  capture, OCR, ASR, TTS, retrieval, shell execution, UI input, and model
  delegation are all tools; instructions for operating them are skills;
  "maintain the wiki" / "answer the user" / "research a question" are
  runbooks; every user request or background job is a task.

## Agents (who — principals, not a fifth authoring primitive)

Subagents are **literal agents**, exactly like HEREBRUM's fleet: Alexandria
(curator), Darwin (researcher), Heimdall (guardian). Each is an identity note
plus a private subtree under `Agents/<Name>/`, and tasks bind to them with
`assignee: "[[Agents/<Name>]]"`. The four authoring primitives describe the
work (what/how/knowledge/capability); agents are *who*. One interpreter
runtime executes every session — **as** the assigned agent (its identity is
the persona, and an agent `tools:` list further narrows the skill-granted
set). Visually each agent is its own satellite ball orbiting the main graph
(the HEREBRUM satellite machinery), carrying its subtree and assigned tasks.

## The runtime is not a primitive

The harness is the **interpreter**:

```
Task
  → choose Runbook            (leaf) — or expand Subtasks (container, in order)
  → load required Skills      (runbook.skills → union of their tools)
  → authorize and invoke Tools (only the authorized set exists in-session)
  → collect evidence          (immutable receipt per run)
  → update Task state
```

A task instance carries runtime properties in system-written frontmatter —
`status` (`draft → pending → running → blocked | review | completed | failed`),
inputs (`params:`), outputs/evidence (receipt links), timestamps — without
creating a fifth architectural category. The scheduler fires `pending` tasks
(and cron-`schedule:`d ones); acceptance criteria route terminal success to
`review` for the owner unless `auto_done: true`.

## Laws

1. **Edges dispatch, vectors inform.** Control flow resolves through exact
   wikilinks (task → subtasks/runbook → skills → tools). Retrieval only
   assembles the activation briefing. Similarity never selects what runs.
2. **Owner writes freely; agents propose.** The owner edits the vault in
   Obsidian; agents write only staged proposals (`_staging/`) which the owner
   approves/rejects. The harness itself writes only `Receipts/` and task
   runtime frontmatter.
3. **Mechanism in code, policy in vault.** The interpreter contains no policy.
4. **Tool authorization is closed.** A session gets exactly the tools its
   skills (plus runbook extras) grant — plus `task.complete`. Nothing else.
5. **Receipts are immutable; git is the audit trail.**

## UI vocabulary

The **Jobs** pane is where tasks are *assigned* (created, parameterized,
scheduled, run, watched). "Job" is operational vocabulary for a task instance
under the interpreter — it is not a fifth primitive.

## Components

```
vault/      Tasks/ Runbooks/ Skills/ Tools/ Knowledge/ Receipts/ _staging/
harness/    the interpreter: indexer (FTS5+BGE hybrid, RRF), briefing,
            executor, scheduler, review ops, FastAPI :8765, STT
ui/         Electron HUD: the 3D graph backdrop (original HEREBRUM engine,
            paint pipeline, and the owner's recovered tuning) + floating
            panes: Jobs, Operator (chat+voice), Review Queue, Reader, Harness
```

## Non-goals for v0

Adjudication lanes, sealed validators, per-agent vault
isolation, secrets. Trust model: one owner + staged proposals + git. Add
ceremony only when the dev build earns it.
