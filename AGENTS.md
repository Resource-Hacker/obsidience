# Obsidience development contract

Read `DESIGN.md` before changing the Harness. If `AGENTS.local.md` exists, read
it for this installation's additional operating contracts and owner preferences.
That file is local and must never be staged for publication.

Apply the `karpathy-guidelines` and `obsidience-development` skills when installed.
Use their essential workflow even in a checkout without them:

- Make the smallest coherent change in the existing design. Preserve unrelated
  work, dirty files, authority boundaries and a rollback path.
- Validate actual behavior with relevant logs, API/UI observations and the
  compile/build steps needed for the affected code.
- Do not create or modify tests, fixtures or test infrastructure unless the
  owner explicitly requests tests. Preserve existing tests. Use a narrow existing
  check only when it resolves a concrete uncertainty; avoid routine broad suites.
- Restart only affected processes. Documentation needs no restart. Preserve the
  secure locker, compositor and live applications during backend maintenance.
- Keep the user informed and carry authorized changes through verification.

## Publication and installation knowledge

When asked to publish the local version as `main`, use the local working tree
as the source of truth. Fetching remote metadata does not authorize merging or
rebasing remote changes into it; integrate GitHub changes only when requested.

`obsidience/defaults/vault/` is the reviewed, tracked installation template.
`obsidience/vault/`, `obsidience/evidence/`, `obsidience/state/`, local configuration
and installation notes are private to the installation and ignored in this repo.
Never force-add them, stage a live Vault export, or use a commit of live data as a
parent of a new public release. Existing published history requires a separately
authorized cleanup if it contains installation data.

Use `obsidience init` only for a fresh destination. It cannot overwrite a live
Vault. Existing knowledge remains under its ordinary Article/Review writers.
A reviewed reusable improvement may be authored separately in the default
Articles; machine inventory, preferences, conversations, permission grants,
Source IDs, approval history and receipts must not be copied with it.
The local Vault's separate Git repository is an audit trail without a remote;
its Review commits must never touch the application index or branch.
See `obsidience/defaults/README.md` for the complete boundary.

## Cordis composition

Follow Cordis's dependency and lifecycle design throughout the Harness, Shell,
UI and integrations. Plugins provide or consume explicit service interfaces;
modules keep their current product boundaries. Declare required dependencies
and optional integrations, register cleanup with acquisition, and stop/drain
owned work on cancellation and dependency loss.

Keep one owner for each store, conversation, scheduler, model reservation and
desktop input path. Preserve committed receipts and never replay uncertain
effects. Prefer maintained upstream components through supported adapters;
record adopted code, revisions and licenses in `artifacts.lock.json`. Do not
add a generic framework or duplicate owner to bypass a missing dependency.

## Ontology and execution

Knowledge, Agent, Task, Runbook, Skill and Tool are the six Article types.
Articles explain knowledge and procedure; code-owned capability definitions
supply executable schemas and validation. A Tool requires an exact binding,
paired Skill, and explicit grant through its execution owner.

Chat and final speech enter the Executive Agent's native DeepSeek model/Tool
loop. Its identity owns standing instructions and direct Skills; there is no
Executive Task, standing Runbook or preliminary conversational router request.
Independently queueable specialist work retains Task → Runbook → Skill → Tool.

Preserve fresh target binding, observation leases, cancellation, Review,
completion verification and no replay of uncertain input. A schema advertisement
is not an Article read or evidence of invocation. Thinking glow uses only the
actual supplied context and Tool-return refs; links never expand that set.

Use the existing Article writer and owner API for live Vault changes. UI,
Source, graph projections, default templates and Git never become competing
knowledge authorities. Physical desktop deployment requires the installation's
local configuration and direct acceptance on its actual hardware.
