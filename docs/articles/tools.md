# Tools

A **Tool** Article describes one registered executable interface to a real,
Source-backed Capability: its arguments, effects and failures. The schema and
execution live in code; the Article explains them.

| Field | Meaning |
| --- | --- |
| `description` | What the Tool does, as shown in catalogs. |
| `obsidience.binding` | Exactly `capability:<tool.id>`. |
| `obsidience.source` | The Capability's entrypoint file under `obsidience/harness/capabilities/`. |

## The executable contract is code

The code-owned Tool definition in
[`obsidience/harness/capabilities/registry.py`](https://github.com/Resource-Hacker/obsidience/blob/main/obsidience/harness/capabilities/registry.py)
is the executable contract: name, description, parameters, effect class and
adapter. The ADK loop advertises it as a native function declaration and the
model calls it through the provider's native function channel. Tool and Skill
Articles add **no second call schema** and no `{tool, args}` text format.

- **No fictional Tool.** A Tool exists only with one real `capability:`
  binding, one Source-linked entrypoint and one paired Skill. Tool metadata must
  match the registry exactly, but it can never choose an import path or an
  executable at runtime.
- **Explicit grants.** A new Tool needs an accepted Tool/Skill pair and an
  explicit grant through its execution owner: an Agent's direct Skills or a
  Task's Runbook. Repository schemas and default Articles alone confer no
  authority.
- **Effect class is reviewed code.** Which capabilities are read-only is a
  code-owned list; Article prose cannot declare an effect safe.
- **Receipts and no replay.** Every call commits intent before dispatch and an
  immutable receipt on return; uncertain effects are never replayed. See
  [Sources and Capabilities](../sources-and-capabilities.md#receipts-and-no-replay).

Change the adapter and its documentation together, keeping the exact
Article-to-Capability provenance.

## Starter Vault Tools

<!-- catalogue:tools -->

Several Tools are integration-specific (Discord, lights, TV, media, camera) and
need their providers and an explicit grant before they can run in an
installation. `session.unlock` is never inherited: it exists only where the
installation owner grants it.
