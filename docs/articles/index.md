# Articles

An **Article** is one Markdown file in the Vault and one node in the knowledge
graph. Its `type` frontmatter field declares exactly one of six meanings:
[Knowledge](knowledge.md), [Agent](agents.md), [Task](tasks.md),
[Runbook](runbooks.md), [Skill](skills.md) or [Tool](tools.md). The
[Ontology](../ontology/index.md) explains why these six exist and how authority
flows between them.

The pages in this section explain each type and list the starter Vault's actual
instances. Those catalogue tables are **generated at build time** from the
frontmatter of the Articles in
[`obsidience/defaults/vault/`](https://github.com/Resource-Hacker/obsidience/tree/main/obsidience/defaults/vault)
(by the site hook `docs/hooks/catalogue.py`), so they always match the
reviewed starter graph that `obsidience init` installs. Your live Vault starts
from the same Articles and then evolves through Review.

## Anatomy of an Article

Every Article is an Open Knowledge Format document: YAML frontmatter, then a
Markdown body. Common document fields (`type`, `title`, `description`,
`sources`, root `status`) stay at the root; Obsidience bindings live under the
`obsidience` key. This is the starter Tool Article for `vault.search`:

```markdown
---
type: tool
title: vault.search
description: Search only the executing Agent's owned and checked-out graph.
obsidience:
  binding: capability:vault.search
  source: obsidience/harness/capabilities/vault/search.py
---

## Runtime

Search only the executing Agent's owned and checked-out graph. ...

## Reference

Hybrid BM25/vector search over the accepted graph. ...
```

- Root `status` is document lifecycle only (`draft`, `stable`, `deprecated`).
  Task status, inputs, queues and results live in SQLite; execution never
  rewrites or re-embeds Articles.
- Standard Markdown links to exact Article files are graph edges; code, images
  and URLs are not.
- A parent Article uses its folder's own name (`Projects/Projects.md`), never
  `index.md`; it is an index by having children.
- Unknown or imported fields round-trip without trust: parsing is not
  admission, and an imported `verified` flag approves nothing.

## The starter graph at a glance

| Type | Where in the Vault | Owner of definitions |
| --- | --- | --- |
| Knowledge | `Architecture/`, `Games/`, `Media/`, `News & Research/`, `Projects/`, `Websites/`, `Agents/Executive/Preferences/` | Alexandria curates ordinary Knowledge; Heimdall owns Agent branches and executable definitions |
| Agent | `Agents/<Name>/<Name>.md` | Heimdall (definitions), owner Review |
| Task | `Tasks/` | Heimdall (definitions), owner Review |
| Runbook | `Runbooks/` | Heimdall (definitions); Darwin generates missing ones through Review |
| Skill | `Skills/<tool.id>.md` | Paired 1:1 with its Tool |
| Tool | `Tools/<tool.id>.md` | Paired 1:1 with its Capability in code |
