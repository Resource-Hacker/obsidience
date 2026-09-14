# Installation knowledge

`vault/` is the reviewed starter graph distributed with Obsidience. It contains
four Agent identities, the reusable Task/Runbook/Skill/Tool library, implementation
and Cordis architecture knowledge, empty world subjects, and empty observation
folders. It contains no previous owner's workstation inventory, preferences,
conversations, news editions, Source captures, proposals or receipts.

## Start a fresh installation

After installing the Python dependencies, run from the repository root:

```sh
./obsidience/scripts/obsidience init
```

This creates `obsidience/vault/` through the existing Article writer and gives
that Vault its own local Git audit repository with **no remote**. Initialization
refuses an existing destination, including a symlink. The complete template is
validated and assembled before it is installed. Use `--vault-dir PATH` for an
explicit alternate destination, and set the same `vault_dir` in your local
`obsidience/obsidience.toml` before running the Harness there.

Configure models, device selections and local integrations separately. The
starter Agent and Task models use `auto`; no model weights, GPU assignments,
connections or enabled periodic schedules are copied. Durable Auto-curate is off;
the existing runtime observation folders permit their own local projections.
The optional `session.unlock` Tool/Skill is documented but is not granted to the
default Executive. Voice unlock requires an explicit choice by the local owner.

## Existing installations

Do not initialize over or replace an existing Vault. Pulling application updates
never copies defaults into live knowledge. Keep your existing Vault, Sources,
SQLite, model/media settings and connection configuration; all are ignored by the
application repository.

Article approval writes audit commits only when `vault/.git/` is a repository of
its own. It never stages or commits the application repository. An existing Vault
can opt into a local audit repository with `git init` inside that Vault; configure
its commit identity locally and do not add a publication remote. SQLite remains
the execution and Review authority even when Git audit is disabled.

## Change shared defaults

Edit an exact Article in `obsidience/defaults/vault/` as a separate development
change. Review its complete body, metadata, citations and links. Retain only
reusable project knowledge, explicit capability bindings and generic defaults.
Use the native Article writer/codec, preserve the paired Tool/Skill contract,
and validate the resulting graph and dependency closure in a disposable Vault.

Never bulk-export the live Vault or infer publishability from its folder, trust
level or Auto-curate setting. New knowledge is local by default. A live correction
can be reauthored here only after removing installation facts, personal authority,
Source IDs, approval timestamps and execution state. A directory named Defaults
does not itself sanitize content.

The application ignores the entire live `vault/`, `state/` and `evidence/` trees,
including their future files. Local configuration and `*.local.md` installation
notes are also excluded. These rules govern new snapshots; they do not erase data
from previously published commits or other Git refs.
