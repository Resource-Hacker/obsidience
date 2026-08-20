# Obsidience

**The knowledge graph is the harness.** A plain Obsidian vault + a small
executor + the HEREBRUM HUD, standalone. See `DESIGN.md` for the laws.

## Quickstart

```sh
./scripts/llm.sh &          # Obsidience's own Gemma server (:8089, RTX 4000 Ada)
./scripts/dev.sh            # harness daemon (:8765) + Electron UI with HMR
```

or piecewise:

```sh
./scripts/obsidience serve      # daemon: API, scheduler, indexer
./scripts/obsidience status     # what the harness sees
./scripts/obsidience run Tasks/wiki     # run the self-maintenance loop now
./scripts/obsidience review     # list staged proposals (approve/reject <file>)
cd ui && pnpm dev               # the HUD
```

Open `vault/` directly in **Obsidian** — it's a normal vault. You edit freely;
agents can only stage proposals into `_staging/` for your review. Receipts and
review decisions are git-committed.

Every Library primitive is recursively composable through its same-kind child
field: `subtasks`, `subrunbooks`, `subskills`, or `subtools`. The Library,
graph, Reader, validator, and interpreter all follow those exact ordered edges.
Dotted Tool bindings also receive generated namespace parents in the Library,
so `task.*` and `vault.*` display as expandable trees without duplicate notes.

## Layout
- `vault/` — the system itself (charters, runbooks, tasks, knowledge, receipts)
- `harness/` — Python daemon (FastAPI :8765): index, retrieval, executor, scheduler
- `ui/` — Electron HUD (3D graph backdrop + floating panes + voice)

## Voice
- STT: faster-whisper (CPU) via `/api/voice/transcribe`; mic button in the chat pane.
- TTS: kokoro-js in the app, using the local model at
  `/var/lib/ai/models/kokoro-82m-v1.0-onnx` (override: `HEREBRUM_KOKORO_CACHE_DIR`).

## Self-maintenance
`Tasks/wiki` (every 6h, Wikipedia Task Center × karpathy llm-wiki):
ingest-sources → lint-notes → validate-links → categorize-notes →
detect-contradictions → expand-stubs. Leaves auto-complete; every change they
want lands in `_staging/` for your review — **staging is the human gate**.
Drop raw documents into `vault/Sources/` and the next cycle integrates them.
`vault/log.md` is the append-only chronology (`grep "^## \[" vault/log.md`).

## Requires
- Any OpenAI-compatible LLM endpoint — default is Obsidience's own
  `scripts/llm.sh` (llama.cpp, local Gemma GGUF, `:8089`); change
  `llm_base_url`/`llm_model` in `obsidience.toml` to point elsewhere.
