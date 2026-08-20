# Obsidience — the knowledge graph *is* the harness

Dev-build design doc (v0). Parallel experiment to the Hermes-plugin conversion:
this side bets on **pure graph-native**: one vault, one small executor, no agent
framework underneath.

## Thesis

The vault is a plain **Obsidian vault** (markdown + wikilinks + frontmatter).
It is *descriptional* (notes you read in Obsidian) and *functional* (the
executor resolves charters, tasks, and runbooks out of it and runs them) at the
same time. There is no separate config layer: changing the system's behavior
means editing notes.

## Laws

1. **Edges dispatch, vectors inform.** Control flow resolves through exact
   wikilinks/frontmatter (task → runbook, task → assignee charter). Vector +
   FTS retrieval only assembles *context* (the activation briefing). Similarity
   never selects what runs.
2. **Owner writes freely; agents propose.** The owner edits the vault directly
   in Obsidian — it's their vault. Agents can only write to `_staging/`;
   promotion into the vault requires a review decision. The harness itself
   writes only `Receipts/` and system frontmatter fields (task `status`).
3. **Mechanism in code, policy in vault.** The executor contains no policy:
   prompts, procedures, schedules, and agent identities are all notes.
4. **Runbooks are mandatory.** A task without a resolvable runbook is
   `blocked/awaiting-runbook`, never improvised.
5. **Receipts are immutable.** One markdown receipt per run, system-written,
   never edited. Live state lives in the harness DB; notes carry definitions
   and last-known outcomes.
6. **Git is the audit trail.** Review decisions and receipt writes commit to
   the vault's history with attribution.

## Components

```
vault/        the Obsidian vault (open it in Obsidian directly)
  Charters/   agent identities: name, model, allowed tools, voice, prompt
  Runbooks/   procedures (incl. meta-runbooks create-a-runbook / create-a-task)
  Tasks/      task notes: assignee, runbook, params, schedule?, acceptance
  Knowledge/  everything else the fleet knows
  Receipts/   system-written run receipts (immutable)
  _staging/   agent proposals awaiting review (+ _rejected/)
harness/      python daemon: indexer (FTS5 + embeddings), retrieval/briefing,
              executor loop, scheduler, review ops, receipts, FastAPI + WS
ui/           Electron app (HEREBRUM panes + 3D graph, rewired to the daemon)
```

## Task lifecycle

`draft → ready → active → review → done | failed | blocked`

- Scheduled task = task note with `schedule:` (cron). One-shot = no schedule.
- Executor session: charter body → task note → runbook body → activation
  briefing (hybrid retrieval, token-budgeted) → JSON-action tool loop against
  local Gemma (`llama.cpp :8081`) → receipt + status transition.
- `acceptance:` criteria present → terminal state is `review` (owner confirms)
  unless `auto_done: true`.

## Review system (kept deliberately simple)

A proposal is a markdown file in `_staging/` whose frontmatter says what it
wants: `action: create|update`, `target: <vault-relative path>`, plus
`agent`, `task`, `reason`. Review = **approve** (apply to target, git commit,
remove from staging) or **reject** (move to `_staging/_rejected/` with a note).
Surfaces: the Review pane in the UI and `obsidience review` in the CLI. The
staging folder is visible in Obsidian too — you can read proposals where you
read everything else.

## Voice

- **TTS**: kokoro-js in the Electron renderer, loading the local
  `kokoro-82m-v1.0-onnx` model already on this machine (no downloads).
- **STT**: faster-whisper in the harness (`/api/voice` WebSocket, 16k PCM
  chunks), lazy-loaded; if the model/package is missing the endpoint reports
  `disabled` and the UI hides the mic.

## Reuse map (fresh code, borrowed proven parts)

- Embeddings: fastembed + BGE-small ONNX from `/var/lib/ai/models/jarvis-knowledge`
  (same lib/model the old authority uses; offline).
- LLM: the running `jarvis-gemma` llama.cpp server (`127.0.0.1:8081`).
- UI: HEREBRUM's jarvis theme, pane workspace, 3D graph — copied, rewired to
  the Obsidience API; Hermes IPC stubbed out.
- Concepts carried from ADR-0001: activation briefing, mandatory runbooks,
  queue-closed blocking, receipts, edges-dispatch law.

## Non-goals for v0

Multi-agent adjudication lanes, sealed validators, per-agent vault isolation,
provisioning auto-tasks, cross-agent subtasks, secrets. The trust model is
"one owner + staged proposals + git". Add ceremony only when the dev build
earns it.
