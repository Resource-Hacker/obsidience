# Obsidience

Obsidience is a graph-native local-agent harness and modular Arch Linux desktop
shell built on Hyprland. A maintained Markdown wiki is the durable brain; typed
graph edges dispatch work, and a bounded RAPTOR retrieval pipeline supplies the
exact Knowledge needed for each activation. The system is optimized first for
small local models.

Obsidience owns the visible shell and agent surfaces. Hyprland owns composition,
outputs, windows, input routing, VRR, fullscreen behavior, and XWayland. Linux,
systemd, PipeWire, NetworkManager, and the other mature system services remain
upstream plumbing. Each replacement arrives as a small, independently testable
slice rather than another monolithic desktop environment.

Read [DESIGN.md](DESIGN.md) for the canonical ontology and execution laws.

## Development commands

```sh
./obsidience/scripts/obsidience status
PYTHONPATH=. .venv/bin/pytest -q
pnpm --dir obsidience/ui typecheck
pnpm --dir obsidience/ui build
```

Harness commands remain independently available:

```sh
./obsidience/scripts/obsidience serve
./obsidience/scripts/obsidience run Tasks/improve
./obsidience/scripts/obsidience run Tasks/check
```

The native UI starts with the selected desktop session. Do not launch the
retired Electron development helper beside either native shell.

The normal development services are:

- `obsidience-harness-dev.service` - API, interpreter, and real-time supervisor on `127.0.0.1:8765`
- `obsidience-shell-host.service` - native Samsung Wayland shell host
- `obsidience-shell-knowledge.service` - canonical Three.js knowledge desktop
- `obsidience-shell-surface-usbc.service` - native USB-C X11 Surface host
- `obsidience-shell-surface-dp4.service` - native DP-4 X11 Surface host

Those are the accepted KWin-session services still running on the workstation.
The separate `hyprland-shell` branch adds an isolated Samsung-only canary:

- `obsidience-hyprland-session.target` - Hyprland development-session boundary
- `obsidience-shell-hyprland-host.service` - the same native Quickshell host
- `obsidience-shell-hyprland-knowledge.service` - the same canonical graph host
- `obsidience-shell-hyprland-notifications.service` - session-local mako owner

The canary is not yet the login default and does not alter the accepted KWin
layout or services.

The read-only System Application record continues to describe that live KWin
session until a physical Hyprland cutover succeeds. It is current-state
inventory, not the desired-state declaration; this branch and
`system-packages.toml` describe the target without falsifying the machine.

Graph Settings → Display selects the one Surface that owns the whole live
knowledge graph. The setting is global for this development slice; individual
Agent placement is intentionally deferred.

The Electron development service is disabled on `native-shell`; its complete
pre-cutover implementation remains on `archive/electron-20260828`. The harness
and affected native shell hosts are restarted after every project change so
the live workspace always matches the working tree.

### Real-time command mode

The top-bar volume control starts and stops the ordinary Realtime Task. A fixed
Pipecat and NVIDIA NeMo speech runtime uses Nemotron Speech Streaming EN 0.6B
on the RTX 4080 SUPER, listens through the Hardware-selected microphone and
speaks through Pocket TTS on CPU. Pipecat's upstream `LocalAudioTransport`
opens both endpoints through process-scoped Pulse routing; there is no browser
audio client, audio WebSocket, or custom capture/playback loop. The OBSBOT camera
is awake exactly while Realtime is ready, with its SDK auto-sleep timer disabled,
so its microphone follows the camera's real hardware state. Hardware
offers the Star Trek Computer, HAL, and Ultron Pocket voices. Each final transcript
runs through the model and reasoning effort selected on the Realtime Task;
speech transport never becomes another Agent, planner, or Tool owner.

The adjacent Play/Pause control is disabled until speech is ready. It toggles
the existing Realtime mode without changing the selected Task model.
Obsidience retains intent, Tool, policy, memory, and action authority.

The supervisor API is `GET /api/realtime`, `POST /api/realtime/start`,
`PATCH /api/realtime/mode`, `POST /api/realtime/stop`, with state updates on
`/ws/realtime`.

## Object model

- Every graph node is an Article.
- Knowledge is the default Article kind, including domains and parent indexes.
- Tasks state outcomes; Runbooks state process.
- Every leaf Tool has one exact Capability entrypoint and one paired Skill; each
  Skill teaches only that Tool.
- Agents own checked-out Tasks, Runbooks, Tools, Skills, and Observations.
- The Tasks pane projects scheduled, event-triggered, and active Tasks.
- Source is one read-only filesystem view: wiki Markdown, application code,
  stable System descriptors, and immutable raw sources remain typed and
  distinct while every displayed path is the real project-relative disk path.

The shared Library contains Tasks and Tool+Skill pairs. Runbooks are synthesized
for individual Agents. The Tasks pane contains only active activation rules and
executions, not the complete Task repository.

## Agent fleet

- Executive - user-facing coordinator and operator
- Alexandria - Curator
- Darwin - Researcher and generator
- Heimdall - Guardian

The Executive's configured personal name is identity data only. Architecture,
paths, protocols, and UI semantics use `Executive`.

## Knowledge loop

```text
request -> Task -> Runbook -> Skill -> Tool -> Capability entrypoint
                    + fast hybrid Knowledge context
        -> evidence -> acceptance -> wiki maintenance
```

When Knowledge is missing, Executive delegates a bounded Question or Learn Task
to Darwin. Every new immutable raw Source emits `source.added`, one trigger on
Darwin's existing Learn Task. Darwin drops one source-backed synthesis into the
physical `obsidience/evidence/inbox/`; its `source.inbox` event activates Alexandria's
centralized Ingest Task. Alexandria stages coherent Articles for owner Review,
Heimdall verifies consequential changes, and the original Task can retry with
the new Knowledge.

## Project layout

- `obsidience/vault/` - accepted Knowledge, Task, Runbook, Tool, Skill, and Agent Articles
- `obsidience/evidence/` - immutable raw evidence plus the physical research Inbox
- `obsidience/harness/` - the Harness Module: `interfaces/{api,cli}`, direct
  `{config,execution,knowledge,conversation,models,realtime,computer,web,host}`
  subsystems, and `capabilities/` paths mirroring exact dotted Tool IDs
- `obsidience/shell/` - the native Shell Module: Hyprland adapter and session,
  native Surfaces, panes, desktop graph, Reader, Terminal, and bounded
  compositor integration; KWin code remains temporary migration rollback
- `obsidience/ui/` - the canonical React/Three.js knowledge-graph bundle used
  by the native graph-only WebKit surface
- `obsidience/scripts/` - development and runtime entry points
- `obsidience/tests/` - executable architecture and behavior contracts
- `obsidience/state/` - the runtime database, model settings, launch contracts,
  and other operational state
- `obsidience/state/system/` - stable physical hardware, interface,
  model-assignment, and speech
  descriptors; live values remain in Hardware and Realtime APIs
- `obsidience/obsidience.toml` - project configuration
- `AGENTS.md` - the schema and development law for the wiki and harness

Open `obsidience/vault/` directly in Obsidian if desired. The Reader provides the same
article hierarchy inside the application, with dockable Knowledge and Source
explorers and one center viewer for both Markdown and source code.

Selecting an Article cross-filters Source to that Article's exact Markdown file
and every associated code, System, or raw-source file. Clicking a row opens the
bytes at that exact displayed disk path; there is no copied Reader document or
synthetic Source file. The physical System Source is
`obsidience/state/system`: `HARDWARE` and `APPLICATIONS` are peers, Hardware
contains Compute, Drives, and Devices, and a Drive exposes the actual files
beneath its volume. Applications currently identifies Obsidience as the
developing desktop shell and the web browser as external/not yet integrated.
Private `@view/` keys stabilize UI identity; they never manufacture Source
truth or become ontology kinds. Source folders use the same
four Agent icons as Library checkout, but assignment means a Knowledge scope:
the ordinary fast search prioritizes related accepted Articles without copying
files, widening Tool authority, or dumping a full subtree into a prompt.

This is an implementation of [Karpathy's LLM-wiki
pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f),
extended so the wiki, raw sources, harness code, and System descriptors form one
OS-like development tree. Obsidience is both the harness and the shell project.
Linux remains the plumbing—kernel drivers, filesystems, systemd, udev,
PipeWire/WirePlumber, NetworkManager, and compositor protocols are reused.

Every physical presentation endpoint is an Obsidience **Surface**. Every pane
uses one generic placement contract: pane ID, Surface ID, local rectangle, open
state, and z-order. The initial Hyprland canary admits only the Samsung
`HDMI-A-1` on the RTX 4080 at `5120x1440@240`, scale 1, 10-bit, with
fullscreen-only VRR. USB-C and DP-4 stay on the accepted isolated Xorg recovery
path until Samsung gaming and lock/session behavior pass physical acceptance.

The same Quickshell registry, pane placement, graph, Reader, terminal, launcher,
and theme run under both compositors during migration; there is no second UI.
Canary state is namespaced so testing cannot overwrite the accepted KWin pane
layout. Pointer dragging remains Surface-local, and later multi-Surface keyboard
transfer remains one atomic placement revision owned by the primary shell.

KWin, Plasma Login Manager, KScreenLocker, and KDE packages remain recoverable
until Hyprland has working lock/PAM, Polkit, portals, crash recovery, HDR/VRR,
and WoW acceptance. They are rollback, not the target architecture. Once those
gates pass, obsolete KWin/Plasma/Openbox/Xorg paths are deleted instead of kept
as a parallel deprecated system.

Obsidience is an ordinary directory backed by `/home`; `/var/lib/ai` is the
Models storage location. `/home` and `/var/lib/ai` are separate Btrfs subvolume
mounts on one shared filesystem and share the same free-space pool. Obsidience
has no dedicated partition or quota.

The Python package root retains only `__init__` and `__main__`. Filesystem depth
expresses stable responsibility: prefer one subsystem level, go deeper only for
true hierarchy such as speech or dotted Tool IDs, keep cross-subsystem imports
explicit and `__init__` files side-effect-free, and do not create generic
`utils`, `common`, or `core` junk drawers.

## Configuration

The Executive endpoint is OpenAI-compatible:

```toml
llm_base_url = "http://127.0.0.1:8089/v1"
llm_model = "obsidience-gemma"
```

Tasks have independent model and reasoning pickers, including `xhigh` where the
model supports it. `auto` selects Gemma 4 26B-A4B for Executive and Qwen3.8 9B
Distill Heretic Q8 for specialist Agents. Hardware is configured per component:
the fallback configuration places Gemma on the RTX 4000 Ada and OmniParser on
the RTX 4080 SUPER, while saved Hardware selections win. A Task temporarily
replaces only overlapping components and restores that saved selection
afterward; inference never spills model layers to CPU.

Additional Task models include Qwen3.8 HOMEUSER on the RTX 4000, the two-GPU
Qwen 27B profiles, and Muse Glimmer 30B. Muse is valid either text-only on the
RTX 4000 or on both GPUs with vision and DFlash; dual-GPU measured 42.46 tok/s
and is the preferred Task layout. Models contains reasoning models only.
Realtime speech is fixed infrastructure shown in Hardware rather than a model
or backend picker.

Models is the inventory and measurement pane. It shows each installed model's
supported modalities and features, compatible GPU layouts, context,
quantization, current state,
latest benchmark, and immutable Source manifest, with direct Benchmark and
Reader configuration actions. Hardware remains the independent saved residency
surface. A new model or artifact revision emits `model.added`, which activates
Darwin's ordinary Model research Task and its inspect, Source, benchmark, and
configuration Tool+Skill pairs.

Hardware cards include live memory and utilization bars plus the available
device sensor set: CPU/RAM/load, AMD iGPU media telemetry, and NVIDIA VRAM,
thermals, power, clocks, fan, engines, power state, and PCIe link. Telemetry is
read-only and pauses its periodic refresh when the interface is not visible.

## Validate

```sh
PYTHONPATH=. .venv/bin/python -c \
  'from obsidience.harness.capabilities.registry import execute; print(execute("vault.validate", {}, {}))'
PYTHONPATH=. .venv/bin/pytest -q
PYTHONPATH=. .venv/bin/python -m compileall -q obsidience/harness
pnpm --dir obsidience/ui typecheck
pnpm --dir obsidience/ui build
```
