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
- The development build carries no automated test suite. Do not create tests,
  fixtures or test infrastructure, or restore deleted ones from history, unless
  the owner explicitly requests tests. Use a narrow existing check only when it
  resolves a concrete uncertainty; avoid routine broad runs.
- Restart only affected processes. Documentation needs no restart. Preserve the
  secure locker, compositor and live applications during backend maintenance.
- Keep the user informed and carry authorized changes through verification.

## Publication and installation knowledge

Keep internal development history separate from the GitHub publication clone.
The installation contract identifies their locations and selected public scope.
The internal checkout is the source of truth for local work; the publication
clone stages only reviewed public changes and retains public history. Port exact
files or hunks, never merge private commits, copy Git objects or mirror all refs.
Fetching remote metadata does not authorize merging or rebasing it into internal
work. Review new files and diffs, validate the affected behavior and scan for
private data before an explicitly scoped push from the publication clone.

Project Knowledge describes source and publication boundaries. Architecture
explains implementation; application inventory describes the deployed instance.
A published commit is not evidence of deployment. Source and Code graph views
remain read-only projections. Local source edits require an explicitly assigned
coding agent with a bounded owner request; project descriptions never grant the
running Executive edit, shell or deployment capabilities.

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
record adopted code, revisions and licenses in `artifacts.lock.json`. Adopt a
maintained framework when it makes the system better (one per concern, staged
behind a switch with a rollback); never add a duplicate owner to bypass a missing
dependency. The principles live in the Golden ontology
(`Architecture/Harness/action-ontology`).

## Ontology and execution

Knowledge, Agent, Task, Runbook, Skill and Tool are the six Article types.
Articles explain knowledge and procedure; code-owned capability definitions
supply executable schemas and validation. A Tool requires an exact binding,
paired Skill, and explicit grant through its execution owner.

Chat and final speech enter the Executive Agent's Google ADK model/Tool loop.
Its identity owns standing instructions and direct Skills; there is no
Executive Task, standing Runbook or preliminary conversational router request.
Independently queueable specialist work retains Task → Runbook → Skill → Tool
and runs on the same ADK loop and capability core.

Preserve fresh target binding, observation leases, cancellation, Review,
completion verification and no replay of uncertain input. A schema advertisement
is not an Article read or evidence of invocation. Full thinking ignition and
labels use only the actual supplied context and Tool-return refs. The route's
hierarchy waypoints and the Articles one link from a supplied one may carry a
visibly softer passage glow; nothing lights beyond that one link.

Use the existing Article writer and owner API for live Vault changes. UI,
Source, graph projections, default templates and Git never become competing
knowledge authorities. Physical desktop deployment requires the installation's
local configuration and direct acceptance on its actual hardware.
