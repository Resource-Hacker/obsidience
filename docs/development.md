# Development

Read [DESIGN.md](https://github.com/Resource-Hacker/obsidience/blob/main/DESIGN.md)
before changing the Harness, and the repository's
[AGENTS.md](https://github.com/Resource-Hacker/obsidience/blob/main/AGENTS.md),
the development contract for people and coding agents alike. An installation's
ignored `AGENTS.local.md` adds its own operating contracts; it is never staged
for publication.

## The development loop

1. **Inspect** the relevant current code, logs and live behavior.
2. **Make the smallest coherent change** in the existing design. Preserve
   unrelated work, dirty files, authority boundaries and a rollback path.
3. **Validate actual behavior**: build or compile what changed, then observe
   the affected logs, API responses or UI directly.
4. **Restart only what is affected**:

    | Change | Apply with |
    | --- | --- |
    | Harness (Python backend) | Reload only the Harness |
    | Graph UI (`obsidience/ui/`) | Rebuild the bundle, then reload the graph presenter |
    | Shell QML | `obsidience/shell/session/restart-shell` (refuses while locked) |
    | Documentation, instructions | No restart |

    Preserve the secure locker, the compositor and live applications during
    backend maintenance.

## Validation policy

The development build carries **no automated test suite**. Do not create
tests, fixtures or test infrastructure, or restore deleted ones from history,
unless the owner explicitly asks for tests. Use a narrow existing check only
when it resolves a concrete uncertainty, and avoid routine broad runs. Physical
desktop behavior is accepted by the owner on the actual hardware, never claimed
by an agent.

The definition of done:

- the Vault validates with no broken load-bearing edges, and every Tool has one
  paired Skill, exact binding and entrypoint;
- affected code compiles or builds (UI typecheck and build for UI changes);
- only affected services were restarted, and the affected interface was
  observed working;
- accepted text claims no predecessor architecture and no Tool without its
  real binding.

## Checks

```sh
# Graph UI
pnpm --dir obsidience/ui install --frozen-lockfile
pnpm --dir obsidience/ui typecheck
pnpm --dir obsidience/ui build

# Python: byte-compile, and fail on syntax errors or undefined names
python -m compileall -q obsidience
ruff check --select E9,F63,F7,F82 obsidience

# Shell, before a live session change
Hyprland --verify-config --config obsidience/shell/adapter/hyprland/hyprland.lua
desktop-file-validate obsidience/shell/session/obsidience.desktop
systemd-analyze --user verify obsidience/shell/systemd/*.service \
  obsidience/shell/systemd/*.target
```

The tree is not clean under ruff's full default rule set, so run a plain
`ruff check` only on the files you changed, as advice rather than a gate.

## Adopting upstream code

Prefer maintained upstream components through their supported extension
points. Record adopted code, its revision, digest and license in
`artifacts.lock.json` (license texts in `LICENSES/`), keep local patches as
tracked patch files, and stage a migration behind a switch with a rollback.
Never add a duplicate owner to bypass a missing dependency. See
[Integrations](integrations/index.md).

## Publishing and the starter Vault

`obsidience/defaults/vault/` is the reviewed, tracked installation template;
the live `vault/`, `evidence/` and `state/` trees, local configuration and
installation notes are private and ignored. Never force-add them or stage a
live Vault export.

To change a shared default, edit the exact Article in
`obsidience/defaults/vault/` as a separate development change: review its full
body, metadata, citations and links, keep only reusable project knowledge and
generic defaults, preserve the paired Tool/Skill contract, and validate the
graph in a disposable Vault. Machine inventory, preferences, conversations,
permission grants, Source ids, approval history and receipts never move into
defaults.

## This documentation site

The site is built with [MkDocs](https://www.mkdocs.org/) and
[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) from
`docs/` and `mkdocs.yml`, and deployed to GitHub Pages by
`.github/workflows/docs.yml`. Pull requests build it with `--strict`; pushes to
`main` also deploy it.

```sh
python -m venv /tmp/obsidience-docs
/tmp/obsidience-docs/bin/pip install -r docs/requirements.txt
/tmp/obsidience-docs/bin/mkdocs build --strict   # or: mkdocs serve
```

- The catalogue tables on the [Articles](articles/index.md) pages are generated
  at build time from the starter Vault's frontmatter by `docs/hooks/catalogue.py`;
  edit the Articles, not the tables.
- The `privacy` plugin downloads web fonts and the Mermaid runtime during the
  build and serves them from the site, so the build needs network access and
  readers make no third-party requests.
- Keep `docs/media/` and `docs/harness2.md` where they are: the README links
  to them.
