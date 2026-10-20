# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the major version is 0, any release may change interfaces.

Entries are grouped by Module (Harness, Shell, Media, TV), and Harness entries
by the concepts of the [Golden ontology](obsidience/defaults/vault/Architecture/Harness/action-ontology.md).

## [Unreleased]

## [0.1.0] - 2026-10-19

The first public release of Obsidience, a graph-native, local-first agent
harness and Linux desktop shell. Everything below is new in this release.

### Added

#### Harness

- **Agents.** The Executive Agent runs typed chat and final speech transcripts
  through one Google ADK model/Tool loop. Its identity Article owns its standing
  instructions and its direct Skill catalog; there is no router and no
  preliminary model call. Three specialist Agents share the same loop: Darwin
  researches and hands off cited Sources, Alexandria curates and links
  Articles, and Heimdall checks evidence, performs receipt-safe recovery and
  onboards new models (inspect, source, benchmark, configure). The Executive
  runs on a local llama.cpp model (Gemma 4 26B-A4B in the reference setup)
  with recorded patches for exact input admission and Tool-argument grammar,
  MTP drafting, and a warm model slot saved and restored across restarts.
- **Tasks and Runbooks.** Independently queueable specialist work activates
  Task → Runbook → Skill → Tool from exact accepted graph edges. A scheduler
  and execution ledger record activations, runs and Tool receipts, support
  cancellation and recovery, verify completion, and never replay an uncertain
  effect. The starter library includes Archive, Audit, Curate, Generate,
  Improve, Ingest, Link, Merge, Query, Repair and Research Tasks with their
  Runbooks.
- **Skills, Tools and Capabilities.** Each Tool is a code-owned Capability
  contract under `obsidience/harness/capabilities/`, advertised to the model as
  a native function declaration, with one Tool Article and exactly one paired
  Skill. The capability core keeps argument validation, exact target binding,
  observation leases, model leases and receipts. Tools cover the Vault (list,
  search, read, propose, validate, maintenance), Sources and web research,
  memory recall and retention, Tasks, computer observation and input, window
  placement, a rolling screen replay, the camera, application launch, Media,
  the TV, models and the Harness itself.
- **Knowledge and Review.** Knowledge follows the LLM-wiki pattern: immutable
  Sources and an agent-maintained wiki of Open Knowledge Format Markdown
  Articles, every one a node of one graph. Agents stage proposals; accepted
  changes land through owner Review and a local Vault Git audit trail with no
  remote, then flow into retrieval and the graph. Activation builds the
  smallest complete context packet with explicit context accounting. A
  reviewed starter Vault ships in `obsidience/defaults/vault/`, and
  `obsidience init` installs it without ever overwriting an existing Vault.
  Open Knowledge Format is its own module (`knowledge/okf.py`: codec, reserved
  documents, links and a spec conformance check) under the Obsidience Article
  profile; every reader goes through it and the Vault validator checks the spec
  before the profile.
- **Memory.** Optional per-Agent Hindsight banks hold facts, experiences and
  consolidated observations with their original dates, kept separate from
  accepted Knowledge. Recall is bounded and starts at admission. The
  Executive's mental models feed at most three Curate recommendations at a
  time into owner Review. Hindsight 0.10.3 runs with recorded patches. Background memory work runs in
  upstream's dedicated worker process, so the request-only API that serves
  recall is never stalled by retain or consolidation.
- **Instruction improvement.** Heimdall's Audit improves Agent and Runbook
  instructions from captured failures with Google Research Harness2's
  Propose–Probe–Compose search and AutoSaddler V2 candidates, lineage and
  rollback. Trials run in isolated ADK sessions and dispatch no effects; a
  candidate is published only through Review after repeated baseline and
  control comparisons. Failed or refused Executive turns are captured too (the
  Executive's Runtime section is the editable unit), a stale or unreproduced
  case settles instead of blocking the queue, an interrupted Audit resumes its
  saved job, and Audit's proposal sessions may run on a cloud model through the
  official Codex or Claude Code CLI while trials keep the local model.
- **Voice.** Realtime speech on Pipecat's local transport: a CPU wake-word
  spotter with a ready chirp, NVIDIA NeMo Nemotron streaming recognition with
  early finals and a silence gate, and end-of-turn detection from Silero VAD
  and Smart Turn plus the Executive's own semantic verdict. That verdict is
  speculated at pauses together with the first response and memory recall, so
  answers start before the speaker finishes. Pocket TTS speaks sentence by
  sentence from the reply's control line, Markdown is spoken as prose, and
  talking over a reply ducks it. The speech stream stays fed between
  sounds so chirps and replies start without a dropout, a reply that ends in a
  question reopens the microphone for the answer, Pocket TTS can run with
  dynamic int8 weights, and the completion check rejects replies that only
  promise or decline to look instead of using the Tool.
- **Runtime.** A loopback API (port 8765) that admits only local clients, the
  `obsidience` CLI (`init`, `status`, `serve`, `index`), model catalog and
  hardware residency leases, and a deploy script that restarts only changed
  owners at an idle moment, verifies them and rolls back on failure.

#### Shell

- **Action Trace.** Each run reads in the ontology's terms (a conversation
  turn is not a Task); a Hindsight recall opens into memory cards with type,
  age, recorded date and timing, and the Code graph shows each coding-agent
  lookup as a card with its matched symbols.

- **Desktop shell.** Hyprland owns composition, focus, clipboard and window
  movement; one Quickshell host serves the native panes (Chat, Library, Tasks,
  Reviews, Reader, Knowledge, Graph, Source, Models, Hardware, Camera,
  Settings, Media, Applications, Terminal and more) across Surfaces on several
  monitors. Includes a patched `hyprland-obsidience` package recipe,
  xdg-desktop-portal-hyprland capture fixes, a secure session locker on
  ext-session-lock with PAM, the Obsidian Gold theme, a snipping tool and an
  optional agent canvas tab for a separately installed nodeterm.
- **Graph UI.** A React/Three.js bundle rendered in a QtWebEngine stage. The
  knowledge graph shows the Executive at the center with subjects and Articles
  in craters on layered glass shells and the specialist Agents orbiting as
  satellites. Thinking turns light exactly the Articles in the supplied
  context; a Memory view draws each Agent's Hindsight bank as a timeline tube
  and lights exactly the recalled memories; a Code view lays out a repository
  indexed by codebase-memory-mcp, with a Follow mode for saved files.
- **Edge Cast.** A browser extension and native messaging host that cast the
  YouTube video in Edge to the TV with one button.

#### Media

- An independent media catalogue built on Jellyfin, which owns delivery and
  per-user resume. Obsidience adds discovery, explicit acquisition through
  optional provider services, a native Media pane and the `media.library`,
  `media.acquire` and `media.pause` Tools. Media bytes never pass through the
  model or the Harness.

#### TV

- A PC-hosted television session: a headless sway compositor streamed by
  Sunshine to Moonlight on a Fire TV, an mpv player with a live-channel tuner,
  1080p on the integrated GPU by default and a 4K mode, and a separate Android
  TV instance in its own container. The Executive's spoken replies also play
  on the TV through Snapcast. A Fire TV agent and the remote control the
  session, and the Executive drives it through the `tv.control` Tool.

#### Other integrations

- An optional Discord bot with isolated conversations, voice and a live graph
  camera, and an optional Matter lights controller with music visualization.

#### Project

- Apache-2.0 license and NOTICE; contributing, code of conduct, security and
  support guides; issue forms, a pull request template, a proposed label set,
  Dependabot configuration and GitHub Actions build checks (UI typecheck and
  build, Python byte-compile, Ruff).
- A documentation site on GitHub Pages organised by the ontology (each
  Article type, each Module, each upstream integration), with the real graph
  UI as an interactive demo on Obsidience's own knowledge, code and history.

### Milestones before 0.1.0

- 2026-08-20: first graph-native Harness development build.
- 2026-08-28: the modular Quickshell host.
- 2026-09-13: published as `main` with the reusable starter Vault.
- 2026-10-09: Google ADK became the only Executive and specialist loop.
- 2026-10-12 to 2026-10-13: the PC-hosted TV and the Media catalogue.
- 2026-10-15: project reorganization by Module and ontology; the automated test
  suite was removed in favor of direct validation.
- 2026-10-18 to 2026-10-19: Harness2 instruction improvement and speculative
  speech admission.

[Unreleased]: https://github.com/Resource-Hacker/obsidience/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Resource-Hacker/obsidience/releases/tag/v0.1.0
