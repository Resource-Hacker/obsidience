# Obsidience

**The knowledge graph is the harness.** A plain Obsidian vault + a small
executor + the HEREBRUM HUD, standalone. See `DESIGN.md` for the laws.

## Quickstart

```sh
./scripts/dev.sh            # harness daemon (:8765) + Electron UI with HMR
```

or piecewise:

```sh
./scripts/obsidience serve      # daemon: API, scheduler, indexer
./scripts/obsidience status     # what the harness sees
./scripts/obsidience run Tasks/vault-gardening   # run one task now
./scripts/obsidience review     # list staged proposals (approve/reject <file>)
cd ui && pnpm dev               # the HUD
```

Open `vault/` directly in **Obsidian** — it's a normal vault. You edit freely;
agents can only stage proposals into `_staging/` for your review. Receipts and
review decisions are git-committed.

## Layout
- `vault/` — the system itself (charters, runbooks, tasks, knowledge, receipts)
- `harness/` — Python daemon (FastAPI :8765): index, retrieval, executor, scheduler
- `ui/` — Electron HUD (3D graph backdrop + floating panes + voice)

## Voice
- STT: faster-whisper (CPU) via `/api/voice/transcribe`; mic button in the chat pane.
- TTS: kokoro-js in the app, using the local model at
  `/var/lib/ai/models/kokoro-82m-v1.0-onnx` (override: `HEREBRUM_KOKORO_CACHE_DIR`).

## Requires
- `jarvis-gemma` llama.cpp server on `127.0.0.1:8081` (any OpenAI-compatible
  endpoint works — set `llm_base_url`/`llm_model` in `obsidience.toml`).
