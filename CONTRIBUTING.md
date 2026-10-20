# Contributing to Obsidience

Thanks for your interest in Obsidience. Questions, bug reports, ideas and pull
requests are all welcome.

- **Questions and ideas:** start a thread in
  [Discussions](https://github.com/Resource-Hacker/obsidience/discussions).
- **Bugs and concrete feature requests:** open an
  [issue](https://github.com/Resource-Hacker/obsidience/issues/new/choose) with
  one of the forms.
- **Security problems:** do not open a public issue; follow
  [SECURITY.md](SECURITY.md).

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## The ontology in brief

Obsidience is organized by its own ontology, the
[Golden ontology](obsidience/defaults/vault/Architecture/Harness/action-ontology.md).
Knowing it tells you where a change belongs.

Every node of the knowledge graph is an **Article**, a Markdown file in Open
Knowledge Format whose `type` is one of six:

| Article type | What it is |
| --- | --- |
| Knowledge | Useful context. The default type. |
| Agent | One accountable executor, with its standing instructions and direct Skills. |
| Task | A reusable outcome and its acceptance condition. |
| Runbook | Reusable ordered or branching operating instructions. |
| Tool | One registered executable interface to a real Capability. |
| Skill | How to use exactly one Tool. Skills are one-to-one with Tools. |

Some things are deliberately **not** Article types:

- **Source** is the real file or immutable evidence an Article cites.
- **Capability** is the executable code behind a Tool. A Tool's contract (name,
  parameters, output and implementation) lives in code under
  `obsidience/harness/capabilities/`; the Tool and Skill Articles explain it
  and never define a second call schema.
- **Module** is a physical product component. There are four: **Harness**,
  **Shell**, **Media** and **TV**.

Plugins, services, events, activations and runs are implementation or runtime
roles, not Articles either. Only explicit, accepted graph edges grant an Agent a
Task, Runbook, Skill or Tool; similarity, links and model output never do.

## Where a change belongs

| Change | Location |
| --- | --- |
| Harness: API, CLI, conversation, execution, capabilities, models, knowledge, memory and realtime voice | `obsidience/harness/` |
| Shell: compositor adapters, session, native QML panes, theme | `obsidience/shell/` |
| Shell's graph and interface bundle (React/Three.js) | `obsidience/ui/` |
| Shell's Edge Cast client | `obsidience/browser/edge/` |
| Media: catalogue service units and provider launchers | `obsidience/media/` |
| TV: PC-hosted TV session, its units and the Fire TV agent | `obsidience/tv/` |
| Optional Discord and lights integrations | `obsidience/discord/`, `obsidience/lights/` |
| Starter Agents, Tasks, Runbooks, Skills and Tools | `obsidience/defaults/vault/Agents/`, `Tasks/`, `Runbooks/`, `Skills/`, `Tools/` |
| Starter Knowledge | `obsidience/defaults/vault/<subject>/`, for example `Architecture/` |
| Unit files | Beside the code that owns them (`harness/systemd/`, `shell/systemd/`, `tv/systemd/`, `media/`) |
| Adopted third-party code, patches and pins | Recorded in `artifacts.lock.json`, license text in `LICENSES/` |

A new Tool is one change across three places: the capability entrypoint at
`obsidience/harness/capabilities/<group>/<name>.py`, its Tool Article in
`obsidience/defaults/vault/Tools/` and its paired Skill Article in
`obsidience/defaults/vault/Skills/`. The
[create-a-tool Runbook](obsidience/defaults/vault/Runbooks/create-a-tool.md)
states the contract.

`obsidience/defaults/vault/` is the reviewed, distributable starter graph. Never
commit a live Vault, `obsidience/vault/`, `obsidience/evidence/`,
`obsidience/state/`, `obsidience/obsidience.toml`, `AGENTS.local.md` or any
machine inventory, preferences, conversations, receipts or personal data. See
[installation knowledge](obsidience/defaults/README.md) for the boundary.

## Development setup

You need Linux, Python 3.14 for the Harness (the realtime speech worker runs in
its own Python 3.12 environment), Node.js 22 and pnpm. From the repository
root:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r obsidience/harness/requirements.txt -c obsidience/harness/requirements.lock.txt
python3 obsidience/scripts/install-optimization
./obsidience/scripts/obsidience init
```

`init` installs the starter graph into a new local Vault and refuses to
overwrite an existing one. Create an ignored `obsidience/obsidience.toml` from
[`obsidience.example.toml`](obsidience/obsidience.example.toml) and review the
model, storage and hardware selections for your machine before running
inference. Then:

```sh
./obsidience/scripts/obsidience status
./obsidience/scripts/obsidience serve
pnpm --dir obsidience/ui install --frozen-lockfile
pnpm --dir obsidience/ui build
```

The API listens on loopback port 8765. The native shell runs under Hyprland
with the Quickshell runtime described in the [Shell README](obsidience/shell/README.md).
The scripts include Linux integration profiles from the development machine;
review them for your host rather than applying them blindly.

## Design principles

Read [DESIGN.md](DESIGN.md) before changing the Harness. In short:

- **One Article graph is authoritative.** UI trees, menus and prompts are
  projections of it. Definitions live in Articles; occurrences, status and
  results live in the execution ledger.
- **Edges dispatch, retrieval informs.** Authority comes only from exact
  accepted edges.
- **Cordis-style composition.** Components provide or consume explicit service
  contracts and declare required dependencies and optional integrations. Every
  subscription, timer, worker, client and lease registers its cleanup when it
  is acquired. Each store, conversation, scheduler, model reservation and
  desktop input path has exactly one owner; others go through its interface.
- **Never replay an uncertain effect.** Receipts record what was dispatched and
  delivered.
- **Optimize for small local models.** Explicit contracts, narrow choices,
  stable names and deterministic validation over prompt cleverness.
- **Prefer maintained upstream components** through their supported extension
  points, pinned and recorded with their license in `artifacts.lock.json`.

Make the smallest coherent change in the existing design, and keep unrelated
cleanup out of the same pull request.

## Validation

The project has no automated test suite, on purpose. Validate the behavior you
changed directly: the relevant build, type check and lint, plus logs, API
responses or UI observations that show the change working. Do not add tests,
fixtures or test infrastructure unless a maintainer asks for them.

The CI build checks (`.github/workflows/ci.yml`) can be run locally:

```sh
pnpm --dir obsidience/ui install --frozen-lockfile
pnpm --dir obsidience/ui typecheck
pnpm --dir obsidience/ui build
python3.14 -m compileall -q -x '(^|/)(node_modules|\.venv|venv|out|dist|__pycache__)(/|$)' obsidience
python3.12 -m compileall -q obsidience/harness/realtime/speech obsidience/harness/config.py
ruff check --select E9,F63,F7,F82 --target-version py314 obsidience
```

If these drift from the workflow, the workflow is authoritative.
Documentation and Article-only changes need no build.

## Commits and pull requests

Commit subjects are imperative, sentence case and without a trailing period,
and say what the change does in behavioral terms, for example:

```text
Keep the Executive conversation's prompt cache on its own llama.cpp slot
```

A short area prefix is fine for documentation-only changes (`README: ...`).
The body explains why: the symptom, the evidence (logs, measurements, receipt
IDs) and what was validated. Keep one logical change per commit.

In the pull request, say what changed and why, how you validated it, and attach
screenshots or a short recording for anything visible in the shell or graph UI.
Never include secrets, credentials, tokens, personal data or machine-specific
configuration in code, logs, screenshots or commit messages.

Third-party code you add must be compatible with Apache-2.0. Integrate
copyleft or source-available software as a separately installed dependency
instead of copying it into the tree, and record every adopted component in
`artifacts.lock.json` (plus `LICENSES/` and `NOTICE` when its license requires
attribution).

## License

Obsidience is licensed under the [Apache License 2.0](LICENSE). By submitting a
contribution you agree that it is licensed under the same terms, as section 5 of
the license describes. No Developer Certificate of Origin sign-off or
contributor license agreement is required.

Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html);
while the major version is 0, any release may change interfaces. Notable
changes are recorded in [CHANGELOG.md](CHANGELOG.md).
