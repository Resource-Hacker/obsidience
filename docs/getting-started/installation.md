# Installation

This page installs the Harness, its optimizer components and a fresh local
Vault from the reviewed starter graph. The desktop Shell and voice are separate
layers described at the end.

## 1. Clone the repository

```sh
git clone https://github.com/Resource-Hacker/obsidience.git
cd obsidience
```

All commands below run from the repository root.

## 2. Install the Python dependencies

The Executive's Google ADK loop is a pinned Python requirement. Create the
project virtual environment at `.venv` (the `obsidience` launcher script uses
exactly this path):

```sh
python -m venv .venv
.venv/bin/python -m pip install -r obsidience/harness/requirements.txt \
  -c obsidience/harness/requirements.lock.txt
```

Then install the pinned optimizer components used by Heimdall's Audit:

```sh
python3 obsidience/scripts/install-optimization
```

The installer downloads the exact Harness2 upstream archive, verifies its
digest, applies the tracked patch and builds an attested wheel; AutoSaddler is
installed from its pinned revision. `--build-only` builds the wheel without
installing it. See [Self-improvement](../modules/harness/self-improvement.md).

## 3. Create your local Vault

```sh
./obsidience/scripts/obsidience init
```

`init` installs the starter graph from `obsidience/defaults/vault/` once, through
the ordinary Article writer, and creates a local Git audit repository inside the
new Vault with **no remote**. It validates and assembles the complete template
before installing it and **refuses an existing destination**, including a
symlink, so it can never overwrite a live Vault.

Use `--vault-dir PATH` for an alternate destination, and set the same
`vault_dir` in `obsidience/obsidience.toml` before running the Harness there.

The starter graph contains the Executive, Alexandria, Darwin and Heimdall
Agent identities, the reusable Task/Runbook/Skill/Tool library, the project's
architecture knowledge and empty world subjects. It contains no previous
owner's inventory, preferences, conversations, Sources, proposals or receipts.
Durable Auto-curate is off and no periodic schedules are enabled.

## 4. Configure this installation

Create the ignored `obsidience/obsidience.toml` from the example:

```sh
cp obsidience/obsidience.example.toml obsidience/obsidience.toml
```

Review the model catalog (`obsidience/harness/models/runtime.py`), model
storage and hardware selections before running inference. Default Agent and
Task Articles select the model `auto`; the repository supplies no model weights
or saved device assignments. Every key is described in
[Configuration](../configuration.md).

Machine-specific operating notes belong in the ignored `AGENTS.local.md` at the
repository root.

## 5. Build the graph UI

```sh
pnpm --dir obsidience/ui install --frozen-lockfile
pnpm --dir obsidience/ui build
```

The build writes `obsidience/ui/out/renderer/`, which the Harness API serves to
the Shell's graph presenter.

## What stays private

The live `obsidience/vault/`, `obsidience/evidence/` and `obsidience/state/`
trees, `obsidience/obsidience.toml` and `*.local.md` notes are ignored by the
application repository. That covers conversations, local preferences, Sources
and Inbox, proposals, runtime databases, model assignments and device state.
Article approvals commit only inside the separate local Vault repository.

Pulling application updates never copies defaults into live knowledge, and
local knowledge is never synchronized back into the shared defaults. The
[installation knowledge README](https://github.com/Resource-Hacker/obsidience/blob/main/obsidience/defaults/README.md)
describes how reviewed changes to the starter graph are authored.

## Optional layers

=== "Desktop Shell"

    Unit sources live beside the code that owns them
    (`obsidience/harness/systemd/`, `obsidience/shell/systemd/`). An
    installation copies the ones it needs into `~/.config/systemd/user` after
    adapting their paths. `obsidience/shell/session/install-session` (run as
    root) installs the `Obsidience` Wayland session entry and the greetd
    configuration. Validate before a live change:

    ```sh
    Hyprland --verify-config --config obsidience/shell/adapter/hyprland/hyprland.lua
    desktop-file-validate obsidience/shell/session/obsidience.desktop
    systemd-analyze --user verify obsidience/shell/systemd/*.service \
      obsidience/shell/systemd/*.target
    ```

    See [Shell](../modules/shell/index.md).

=== "Voice"

    Install the speech requirements (`obsidience/harness/requirements-speech.txt`)
    into the same environment once their locally patched checkouts exist, choose
    the microphone, speaker and voice under **Settings → AI & Voice**, and
    review the `realtime_*` keys in [Configuration](../configuration.md#voice).
    See [Realtime voice](../modules/harness/voice.md).

=== "Memory"

    Set up the local Hindsight service with its private PostgreSQL database,
    then enable it with `[memory] hindsight_url`. See [Memory](../memory.md).
