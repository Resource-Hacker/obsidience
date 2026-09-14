# Obsidience

Obsidience is a graph-native local-agent harness and modular Linux desktop shell.
A maintained Markdown wiki supplies durable knowledge. Chat and speech enter the
Executive Agent's native DeepSeek Harness loop; independently queueable specialist
work follows explicit Task, Runbook, Skill and Tool dependencies.

The Harness owns conversation, knowledge, model resources, capability validation,
Review and execution receipts. Hyprland owns composition and desktop input;
Quickshell presents native controls and panes, and a WebKit presenter displays
the shared React/Three.js knowledge graph. Cordis's explicit dependency and
lifecycle principles govern integration across these boundaries.

Read [DESIGN.md](DESIGN.md) for the ontology and execution laws, and
[the Shell documentation](obsidience/shell/README.md) before native desktop setup.

## Fresh installation knowledge

This repository distributes a reviewed starter graph in
[`obsidience/defaults/vault/`](obsidience/defaults/vault/), separate from the live
Vault. It includes the Executive, Alexandria, Darwin and Heimdall; their reusable
capability library; project architecture; and empty subjects and observation
folders. It contains no previous owner's computer inventory or personal knowledge.

From the repository root, prepare the Python and native Executive dependencies:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r obsidience/harness/requirements.txt
npm --prefix obsidience/harness/execution/deepseek ci --ignore-scripts --no-audit --no-fund
./obsidience/scripts/obsidience init
```

Initialization installs the graph once and creates a local Vault Git audit trail
with no remote. It refuses to overwrite any existing Vault. Application updates
never replace live Articles or synchronize local knowledge into shared defaults.
See [installation knowledge](obsidience/defaults/README.md) for the publication
and update workflow.

The live `obsidience/vault/`, `obsidience/evidence/`, and `obsidience/state/` trees
are ignored by the application repository. This includes conversations, local
preferences, Sources and Inbox, archives and proposals, runtime databases,
connections, model assignments and device state. Article approvals commit only
inside the separate local Vault repository.

## Configure this installation

Create an ignored `obsidience/obsidience.toml` from
[`obsidience.example.toml`](obsidience/obsidience.example.toml). Configure the
model endpoint/catalog, model storage and hardware selections for this machine
before running inference. Default Agent and Task Articles select `auto`; the
repository supplies no model weights or saved device assignments.

```toml
llm_base_url = "http://127.0.0.1:8089/v1"
llm_model = "obsidience-gemma"
```

This is a development project, not a universal desktop installer. Native shell,
session, application launch and model scripts include Linux integration profiles
that must be reviewed and configured for the target host. Do not apply another
installation's monitor, storage or service settings blindly. Machine-specific
operating instructions belong in the ignored `AGENTS.local.md`.

Durable Auto-curate and periodic schedules are not inherited from the development
machine. Empty runtime observation folders retain their ordinary local writers.
The optional voice/session unlock capability is documented in the library but
is not granted by the starter Executive; enabling it is a local owner's choice.

## Run and develop

```sh
./obsidience/scripts/obsidience status
./obsidience/scripts/obsidience serve
./obsidience/scripts/obsidience index
pnpm --dir obsidience/ui install --frozen-lockfile
pnpm --dir obsidience/ui typecheck
pnpm --dir obsidience/ui build
```

The API defaults to loopback port 8765. The native UI is started by the configured
desktop session; do not launch the retired Electron interface beside it. Backend
changes require only the Harness reload; graph changes require rebuilding and
reloading the graph presenter. Preserve the secure locker and compositor.
Instruction-only changes need no restart.

Validate the affected behavior directly. Preserve existing tests, use a narrow
existing check when needed, and do not add tests or run broad suites unless asked.

## Knowledge and execution

```text
Chat / speech → Executive identity + context → DeepSeek model / Tool loop
Specialist work → Task → Runbook → Skill → Tool
Feed / explicit research → immutable Source → Darwin → Inbox → Alexandria
Accepted Article changes → Review / local audit → graph + retrieval
```

- The Executive answers and operates through its explicit direct Skill catalog.
- Darwin researches and produces bounded, cited Source handoffs.
- Alexandria curates and links maintained knowledge through the existing writers.
- Heimdall independently checks evidence and performs receipt-safe recovery.

Knowledge links never grant a capability. Tool arguments, exact targets,
observation leases, cancellation, Review, receipts and completion acceptance
remain code-owned. Uncertain effects are not replayed. Thinking animation shows
the actual supplied context and remains lit through speech; the central orb
follows the output waveform.

The Realtime connection uses Pipecat transport, NeMo/Nemotron speech recognition
and CPU Pocket TTS. Device selection and optional camera lifecycle support are
installation configuration. Both final speech transcripts and typed Chat use the
same Executive session; partial speech can prepare a cancellable prompt prefix
without running Tools or committing a request early.

## Project layout

| Path | Responsibility |
| --- | --- |
| `obsidience/harness/` | API, CLI, conversation, execution, capabilities, models, knowledge and speech |
| `obsidience/shell/` | Native desktop/session adapters, panes and graph presenter |
| `obsidience/ui/` | Shared React/Three.js graph and interface bundle |
| `obsidience/defaults/vault/` | Reviewed, distributable starter Articles |
| `obsidience/vault/` | Ignored live Articles and local audit repository |
| `obsidience/evidence/` | Ignored immutable Sources, Inbox and evidence |
| `obsidience/state/` | Ignored SQLite, connections, settings and runtime artifacts |
| `obsidience/scripts/` | Development and runtime entry points |
| `obsidience/tests/` | Existing behavior and architecture checks |

Previously published Git history is distinct from the current installation
snapshot. Removing live files from a new commit does not remove them from older
commits, branches, forks or existing clones.
