# Skills

A **Skill** explains exactly how to use one Tool correctly. Each callable
`<tool.id>` has one Skill Article at `Skills/<tool.id>` titled
`Using <tool.id>`, with a singular `tool: [[Tools/<tool.id>]]` binding. Order
across several Tools belongs in the Runbook.

| Field | Meaning |
| --- | --- |
| `description` | One-line guidance shown in catalogs. |
| `obsidience.tool` | The one Tool this Skill binds. |
| `obsidience.requires` | Exact other Skills this Skill depends on (for example, `vault.search` requires `vault.read`, because a search hit must be read before it is relied on). |

Skills are how authority reaches a Tool:

- The **Executive's** direct Skills (`Agent.skills`) supply the native Tool
  catalog of its conversation.
- A **Task's** Runbook declares the Skills its procedure may load.

A Skill or Tool glowing in the graph means its instructions were supplied to
the model, not that it was called; actual calls show as separate operation
halos.

## Starter Vault Skills

<!-- catalogue:skills -->
