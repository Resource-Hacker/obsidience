# Runbooks

A **Runbook** gives reusable ordered or branching operating instructions for
completing a Task. Procedure, branching, retry and Tool order belong here, not
in Task hierarchy.

| Field (under `obsidience`) | Meaning |
| --- | --- |
| `task` | The exact Task this procedure completes. |
| `for_agent` | The Agent the procedure applies to. |
| `skills` | The exact Skills the procedure may load. A Runbook loads only its declared Skills. |
| `subrunbooks` | Decomposition into child Runbooks (acyclic). |
| `owner_maintained` | Marks a procedure the owner maintains. |

Rules that keep Runbooks safe for small models:

- **Bindings only narrow.** Runbook operation Tools and runtime instruction
  sections may narrow a Task's authority, never widen it.
- **Missing links fail closed.** A missing or malformed Skill link stops
  activation; the model never invents a replacement.
- **Reference-only procedures** (`Runbooks/Operations`) declare their Agent and
  required Skills without a Task. They are read when needed and add no Task,
  standing packet or grant.
- **An Agent's standing instructions** belong in its identity Article, not in
  a Runbook. The Executive has no standing Runbook.
- **Generated Runbooks.** When an assigned Task lacks an applicable Runbook,
  `task.assigned` activates Darwin's Generate → Runbook, which proposes one with
  an explicit minimal Skill subset; the Task waits for Review. Existing Runbook
  improvement belongs to Heimdall's Audit.

## Starter Vault Runbooks

<!-- catalogue:runbooks -->
