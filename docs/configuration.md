# Configuration

Each installation keeps its settings in the ignored file
`obsidience/obsidience.toml`. Start from the tracked
[`obsidience.example.toml`](https://github.com/Resource-Hacker/obsidience/blob/main/obsidience/obsidience.example.toml)
and never store credentials in it.

The loader is `obsidience/harness/config.py`. A key that matches a field of its
`Config` dataclass sets that field (path fields become paths); every other key
or table lands in `CONFIG.extras`, where the subsystem that owns it reads it
with a default. A key you do not set keeps the default shown below.

!!! note "How this reference was derived"
    The core keys are the `Config` dataclass fields. The other tables list every
    `CONFIG.extras.get(...)` (and `CONFIG.extras[...]`) read in the Harness,
    with the default written at that call site. Keep the TOML tables
    (`[memory]`, `[web]`, `[graphs]`) after all top-level keys, as TOML requires.

Device choices (microphone, speaker, camera, voice) and model residency are
**not** set here: they are owner selections under **Settings → AI & Voice** and
the Hardware assignment, stored in the installation's state.

## Core

| Key | Default | Meaning |
| --- | --- | --- |
| `vault_dir` | `obsidience/vault` | The live Vault directory. Set it to match `obsidience init --vault-dir`. |
| `db_path` | `obsidience/state/obsidience.sqlite3` | The Harness SQLite ledger and index database. |
| `host` | `"127.0.0.1"` | API listen address. Keep it on loopback. |
| `port` | `8765` | API port. The `OBSIDIENCE_PORT` environment variable overrides it. |
| `git_commit` | `true` | Commit approved Article changes to the Vault's own local Git audit repository. Never touches the application repository. |

## Models and execution

| Key | Default | Meaning |
| --- | --- | --- |
| `llm_model` | `"obsidience-gemma"` | Default served model id from the model catalog (`obsidience/harness/models/runtime.py`). Agent and Task Articles that select `auto` resolve through it. |
| `task_reasoning_effort` | `"medium"` | Installation default reasoning effort for Tasks that do not set their own. |
| `llm_temperature` | `0.4` | Sampling temperature for model steps. |
| `max_steps` | `24` | Tool-loop step cap per activation. |
| `adk_model_client` | `"local"` | ADK model route. `"local"` streams from llama-server over the Harness's HTTP pool; `"litellm"` restores ADK's official `LiteLlm` route (same requests, more CPU). |
| `tick_seconds` | `20` | Longest scheduler wait in seconds; admissions, completions and foreground release also wake it. |
| `concurrency` | `1` | Concurrent autonomous Task executions the scheduler admits. |

## Retrieval

| Key | Default | Meaning |
| --- | --- | --- |
| `embed_url` | `"http://127.0.0.1:8791"` | The EmbeddingGemma 2 embedding service used by the Knowledge index. |
| `search_k` | `24` | Candidate count per retrieval lane before fusion. |
| `rrf_k` | `60` | Reciprocal-rank-fusion constant for combining the lexical and dense lanes. |

## Conversation

| Key | Default | Meaning |
| --- | --- | --- |
| `conversation_window` | `true` | Bound the provider's view of the Executive conversation to a window that rebases at idle edges (normally six exchanges / 4K estimated tokens, rebasing to three / 2K). `false` disables the window. |
| `memory_summary` | `true` | Include the Executive's cached Hindsight mental-model pages as one bounded, unverified prompt section. `false` keeps them out of the prompt while per-turn recall continues. |

## Voice

All voice keys are read by the speech worker or the Realtime runtime; restart
the Harness (speech worker) to apply them.

| Key | Default | Meaning |
| --- | --- | --- |
| `realtime_wake_spotter` | `true` | A CPU keyword spotter hears the wake word about 0.2 s after it is spoken and plays the ready chirp before ASR text arrives. `false` keeps ASR-only wake detection. |
| `realtime_smart_turn` | `true` | Smart Turn v3.2 judges each pause on CPU. `false` restores the fixed 700 ms pause; a model that fails to load also falls back to it. |
| `realtime_smart_turn_model` | the v3.2 CPU ONNX path set in the speech worker | `"bundled"` selects Pipecat's bundled Smart Turn v3.1; otherwise a model path. |
| `realtime_short_replies` | `true` | Complete short replies ("yes", "no", "never mind") end the turn at the model's verdict even when scored incomplete. |
| `realtime_asr_silence_gate` | `true` | Skip ASR GPU steps 0.7 s after VAD speech or the last recognized word; each VAD onset replays its 320 ms pre-roll. `false` runs ASR continuously. |
| `realtime_asr_dtype` | `"bfloat16"` | Encoder precision for streaming ASR: `"bfloat16"` or `"float32"`. |
| `realtime_asr_phrases` | `obsidience/state/realtime-asr-phrases.txt` | Phrase-boosting file (one phrase per line, `#` comments; the wake word is always included). `false` disables phrase boosting. |
| `realtime_asr_early_final` | `false` | At the first 200 ms pause, decode the tail once more and send the words as a pause edge for speculative admission. |
| `realtime_semantic_turns` | `false` | Contextual speech admission: the Executive judges whether an utterance is complete in the same request that drafts its first response, speculated at pauses. |
| `realtime_early_speech` | `true` | Speak claim-checked sentences of a voice turn before completion acceptance. `false` speaks only the accepted reply. |
| `realtime_barge_in_ducking` | `true` | Speech over a reply ducks it, holds it once you keep talking and resumes it after a false alarm. `false` stops playback on speech onset. |
| `realtime_tts_quantize` | `false` | Pocket TTS uses dynamic int8 weights in its FlowLM (CPU, less memory, same voice file). Read at speech worker start. |

See [Realtime voice](modules/harness/voice.md) for how these fit together.

## Optional provider tables

### `[memory]`

| Key | Default | Meaning |
| --- | --- | --- |
| `hindsight_url` | unset (memory disabled) | Base URL of the local Hindsight API, for example `"http://127.0.0.1:8790"`. Leave unset until the service is configured. See [Memory](memory.md). |

### `[web]`

| Key | Default | Meaning |
| --- | --- | --- |
| `searxng_url` | unset | A local SearXNG instance for `web.search`. Without it, `web.search` uses its DDGS fallback. |

### `[graphs]`

| Key | Default | Meaning |
| --- | --- | --- |
| `codebase_url` | `"http://127.0.0.1:9749"` | codebase-memory-mcp's HTTP endpoint for the Code view. |
| `codebase_project` | the repository path with `/` replaced by `-` | The indexed project to display. |

## Environment variables

| Variable | Meaning |
| --- | --- |
| `OBSIDIENCE_PORT` | Overrides `port`. |
| `OBSIDIENCE_OPTIMIZER_BACKEND` | `harness2` (default) or `autosaddler`, the retained rollback search backend for `harness.optimize`. |
| `OBSIDIENCE_MEDIA_CONFIG` | Path of the private Media configuration (default `obsidience/state/media.json`). |
| `OBSIDIENCE_DISCORD_CONFIG` | Path of the private Discord integration configuration (default `obsidience/state/discord.json`). |

## Example

```toml
llm_model = "obsidience-gemma"
git_commit = true
realtime_semantic_turns = true
realtime_asr_early_final = true

[memory]
hindsight_url = "http://127.0.0.1:8790"

[web]
searxng_url = "http://127.0.0.1:8888"
```
