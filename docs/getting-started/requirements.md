# Requirements

Obsidience is developed on one Linux workstation and published as a development
project. It does not detect and configure arbitrary hardware for you. This page
describes what a host needs in general terms; the exact devices, outputs and
model files of any installation belong in that installation's ignored
`AGENTS.local.md`, never in the repository.

!!! note "Review before you run"
    Unit files, launchers and compositor configuration in the repository are
    integration profiles written for the development host. Read them and adapt
    paths, devices and outputs before copying them to your own system.

## Core runtime

| Component | Expectation |
| --- | --- |
| Operating system | Linux with systemd user services. The Shell's package policy names Arch Linux packages; other distributions need equivalents. |
| Python | A current CPython 3 with `venv`. The project is developed on Python 3.14; the Harness requirements are pinned in `obsidience/harness/requirements.txt` with the lock file `requirements.lock.txt`. |
| Node.js and pnpm | Needed to build the shared graph UI in `obsidience/ui/` (Vite 7, React, Three.js). Vite 7 needs Node.js 20.19+ or 22.12+. |
| Git | The local Vault keeps its own Git audit repository with no remote. |

The Harness alone (API, scheduler, knowledge index, Review) runs headless. The
desktop Shell, voice and the optional providers below are separate layers you
can add once the Harness works.

## Local models

The Executive and every specialist Task run on a **local llama.cpp server**
through the Google ADK loop. Plan for:

- **An NVIDIA GPU with enough memory for the model you select.** Model
  reservations are checked through NVML (`nvidia-ml-py`) before a model is
  loaded, and the model runtime never silently lowers precision, context or
  offload to make a model fit. The repository ships **no model weights**; the
  model catalog in `obsidience/harness/models/runtime.py` and the hardware
  selections must be reviewed for your machine. The default model id is
  `obsidience-gemma`, a Gemma 4 model served by llama.cpp.
- **A llama.cpp server that acknowledges the exact input-token limit.** The
  ADK model route fails closed unless the server confirms the admitted input
  count on every model step (the `X-LLAMA-Input-Token-Limit` and
  `X-LLAMA-Input-Tokens` response headers). The development build uses a
  locally patched llama.cpp recorded in `artifacts.lock.json`
  (`llama_cpp_executive_admission`); see
  [llama.cpp](../integrations/llama-cpp.md).
- **A CPU text embedder.** Knowledge retrieval (and Hindsight, when enabled)
  uses EmbeddingGemma 2 behind llama-server's OpenAI-compatible
  `/v1/embeddings` endpoint, CPU only (`obsidience/scripts/embed.sh`,
  configuration key `embed_url`).

## Desktop shell (optional layer)

The Shell is a Wayland desktop built from upstream parts. The development
session uses:

- **Hyprland** as the compositor, started as one UWSM session by **greetd**;
- **Quickshell** (Qt 6 with QtWebEngine) as the single shell host, panes and
  graph presenter;
- **PipeWire/WirePlumber**, NetworkManager, BlueZ, UPower and udisks2 as the
  ordinary Linux services underneath.

The repository carries the recipes for a locally rebuilt Hyprland package and a
pinned, patched Quickshell runtime under `obsidience/shell/adapter/`. The full,
names-only package list is in the
[Shell README](https://github.com/Resource-Hacker/obsidience/blob/main/obsidience/shell/README.md#package-policy).
Display layout is installation configuration: Surfaces are mapped to monitors
through `~/.config/obsidience-shell/surface-layout.json`, seeded from
`obsidience/shell/defaults/initial-surface-layout.json`.

## Voice (optional layer)

Realtime speech needs a microphone and speaker, a CUDA GPU for streaming
recognition and CPU capacity for text-to-speech:

- Pipecat local audio transport, NVIDIA NeMo with Nemotron Speech Streaming
  EN 0.6B (on the GPU), Smart Turn and a CPU wake-word spotter, and Pocket TTS on
  CPU. Their Python packages are listed in
  `obsidience/harness/requirements-speech.txt`, which refers to locally patched
  checkouts that you prepare for your host.
- Echo cancellation references the selected speaker's monitor: a supported DSP
  microphone owns its reference, other microphones use PipeWire's WebRTC
  module.

See [Realtime voice](../modules/harness/voice.md).

## Optional providers

| Provider | Enables | Configuration |
| --- | --- | --- |
| [Hindsight](../integrations/hindsight.md) with PostgreSQL and pgvector | Per-Agent historical memory and the Memory graph view | `[memory] hindsight_url` |
| [codebase-memory-mcp](../integrations/code-graph.md) | The Code graph view | `[graphs] codebase_url`, `codebase_project` |
| SearXNG | Local `web.search` (otherwise a DDGS fallback is used) | `[web] searxng_url` |
| Harness2 and AutoSaddler | Heimdall's instruction improvement (`harness.optimize`) | `python3 obsidience/scripts/install-optimization` |
| Jellyfin and media providers | The [Media](../modules/media.md) module | private `obsidience/state/media.json` |
| A PC-hosted TV session | The [TV](../modules/tv.md) module | units in `obsidience/tv/systemd/` |

Each optional provider is off until you configure it. Memory never falls back
silently: missing Hindsight provider configuration fails at startup, and
disabling Hindsight does not enable an alternate memory implementation.
