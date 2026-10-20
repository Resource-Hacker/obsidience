# Document format (OKF)

Every Obsidience Article is one plain Markdown file with YAML frontmatter in the
[Open Knowledge Format](https://github.com/GoogleCloudPlatform/open-knowledge-format)
(OKF). The Vault is an OKF *bundle*: a directory of such files that any OKF
reader, Markdown editor or Git tool can open without Obsidience.

OKF supplies the portable **document contract**. Obsidience adds an **Article
profile** on top: six Article types, an `obsidience` namespace for application
fields, and the rule that Task execution state never lives in an Article. OKF is
not an agent runtime here, and nothing in a document grants trust or authority.

| | |
| --- | --- |
| Specification | [OKF v0.2 `SPEC.md`](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md) |
| Pinned revision | `ad30107c31c06aec8a7d5636e0d1058118604e6f` (2026-08-21) |
| License | Apache-2.0, notice in [`LICENSES/OpenKnowledgeFormat-Apache-2.0.txt`](https://github.com/Resource-Hacker/obsidience/blob/main/LICENSES/OpenKnowledgeFormat-Apache-2.0.txt) |
| Recorded in | [`artifacts.lock.json`](https://github.com/Resource-Hacker/obsidience/blob/main/artifacts.lock.json) (`open_knowledge_format`) |

## How Obsidience uses OKF

Two Harness modules divide the work, and every reader and writer goes through them.

| Module | Owns |
| --- | --- |
| [`harness/knowledge/okf.py`](https://github.com/Resource-Hacker/obsidience/blob/main/obsidience/harness/knowledge/okf.py) | The OKF contract: parsing and serializing frontmatter documents, reserved `index.md`/`log.md` names, bundle-relative link resolution, timestamp and actor rules, and conformance checks derived from the specification. It knows nothing about Article types. |
| [`harness/knowledge/format.py`](https://github.com/Resource-Hacker/obsidience/blob/main/obsidience/harness/knowledge/format.py) | The Article profile: the six types, the `obsidience` namespace, the flat view the Harness works with, Task-ledger separation, lifecycle freshness and Article admission (`validate_profile`). |

The Vault reader and writer (`knowledge/vault.py`), Review, proposals, the
scheduler, the System inventory publisher and `vault.validate` all call these
two modules; there is no other frontmatter parser for Articles. Body links are
read by one CommonMark parser in `knowledge/links.py`, which resolves paths with
the same OKF rule.

Upstream publishes no package, validator or JSON Schema for OKF, so the small
reference codec (`src/reference_agent/bundle/document.py`) is vendored with
attribution rather than installed. Obsidience's copy keeps CRLF bodies byte for
byte and rejects frontmatter that is not a mapping.

## The six Article types on OKF

OKF requires one field, `type`, and lets producers choose its values. Obsidience
admits exactly six:

| `type` | Meaning | Usual place | Typical `obsidience` fields |
| --- | --- | --- | --- |
| `knowledge` | Useful context; the default | anywhere | `context_role`, `required_context`, `auto_curate` |
| `agent` | One accountable executor | `Agents/<Name>/<Name>.md` | `role`, `tasks`, `knowledge`, `exclude_knowledge`, `skills` |
| `task` | A reusable outcome and its acceptance condition | `Tasks/` | `assignee`, `runbook`, `triggers`, `subtasks`, `acceptance` |
| `runbook` | Ordered or branching operating instructions | `Runbooks/` | `task`, `for_agent`, `skills`, `subrunbooks` |
| `skill` | How to use exactly one Tool | `Skills/` | `tool`, `requires` |
| `tool` | One registered executable interface | `Tools/` | `binding`, `source` |

Placement is a convention; the type alone decides meaning. A parent's Article
uses its folder's name, such as `Projects/Projects.md`: it becomes an index by
having children, never by being called `index.md`. See the
[ontology overview](index.md) for what each type may do.

## Frontmatter reference

### Root fields (OKF)

Fields the specification defines stay at the root with their upstream shapes.

| Field | Shape | Obsidience use |
| --- | --- | --- |
| `type` | string, required | One of the six Article types. |
| `title` | string | Display name; the file name is the fallback. |
| `description` | string | One sentence. For a Tool it must equal the registered Tool description (`vault.validate` reports drift). |
| `resource` | path or URI | The asset an Article describes, when there is one. |
| `tags` | list of strings | Cross-cutting labels. |
| `sources` | list of mappings | Provenance; see [Sources](#sources). |
| `generated` | `{by, at}` | Who or what produced the current content. |
| `verified` | `{by, at}` or a list of them | Imported confirmation events. Kept as data; never Review approval or authority. |
| `status` | `draft`, `stable` or `deprecated` | Document lifecycle only; absent means `stable`. Never Task progress. |
| `stale_after` | timestamp | The Article is stale from this instant; maintenance proposes an update. |
| `usage_window` | `{from, to}` | Frames `sources[].usage_count`. |

OKF's Attested Computation fields (`runtime`, `parameters`, `computation`,
`executor`, `attester`) are reserved at the root as well; no Obsidience Article
type uses them.

Every OKF timestamp is an ISO 8601 datetime **with an offset**, for example
`2026-10-19T08:30:00Z`. A date alone (`2026-10-19`) names a different instant in
every timezone and is reported. Actors in `generated.by` and `verified[].by`
follow the OKF convention: `human:<id>` for a person, `process:<id>` for an
automated process (the System inventory writes `process:obsidience-system-inventory`),
or `<producer>/<version>` for an agent or tool.

### The `obsidience` namespace

Application fields live in one mapping named `obsidience`, so other OKF readers
can ignore them safely. Typed edges in it name exact Articles, usually as
`'[[Folder/Article]]'` strings; they are application data, not OKF links.
Writing a known application field at the root, or a root OKF field other than
`status` inside the namespace, is an admission error. Unknown fields are kept where they were
written.

Task execution state (`status`, `params`, `event_queue`, `last_run`, `summary`,
`blocked_reason` and the other runtime fields) lives only in the SQLite
execution ledger. It is never written into a Task Article, and a Task Article
that carries it fails validation.

### Examples

A Knowledge Article:

```markdown
---
type: knowledge
title: Golden ontology
sources:
- resource: obsidience/harness/knowledge/okf.py
- resource: DESIGN.md
---

# Golden ontology

Obsidience classifies an object by what it does ...
```

A Tool and its one Skill:

```markdown
---
type: tool
title: vault.validate
description: Run deterministic validation of Article formats and load-bearing references.
obsidience:
  binding: capability:vault.validate
  source: obsidience/harness/capabilities/vault/validate.py
---
```

```markdown
---
type: skill
title: Using vault.validate
description: Use validation for structural integrity.
obsidience:
  tool: '[[Tools/vault.validate]]'
---
```

A Task, its Runbook and its Agent (abridged):

```markdown
---
type: task
title: Ingest
obsidience:
  assignee: '[[Agents/Alexandria/Alexandria]]'
  runbook: '[[Runbooks/ingest-sources]]'
  reasoning_effort: low
  triggers:
  - source.inbox
---
```

```markdown
---
type: runbook
title: Ingest procedure
obsidience:
  task: '[[Tasks/ingest]]'
  for_agent: '[[Agents/Alexandria/Alexandria]]'
  skills:
  - '[[Skills/source.read]]'
  - '[[Skills/vault.propose]]'
---
```

```markdown
---
type: agent
title: Alexandria
obsidience:
  role: curator
  tasks:
  - '[[Tasks/ingest]]'
  knowledge:
  - '[[Projects/Projects]]'
---
```

## Links

Body links are ordinary Markdown links to exact Article files. The
bundle-relative form, starting with `/`, is recommended because it survives
moving the linking Article:

```markdown
See the [Golden ontology](/Architecture/Harness/action-ontology.md).
See the [neighbouring Article](./other.md).
```

Links that point outside the Vault, images, code examples and web URLs are not
graph edges. A link to an Article that does not exist yet is allowed. Obsidian-style
`[[wikilinks]]` in a body are not OKF links: the Harness rewrites them to
bundle-relative Markdown links whenever it writes an Article, and
`vault.validate` lists any that remain as advisories.

## Sources

`sources` records what an Article was derived from. Each entry needs a
`resource`; `id`, `title`, `author`, `usage_count` and `last_modified` are
optional. Obsidience writes three kinds of resource:

- a web URL;
- `source://<uuid>`, a citation of immutable evidence in the Source store;
- a path without a scheme, which names a file **in the Obsidience checkout**
  (for example `obsidience/harness/knowledge/okf.py`). This is an Obsidience
  convention: such files sit outside the Vault bundle, so other OKF readers see
  an unresolvable path, which the format tolerates.

To attribute one claim, give the entry an `id` and cite it with a footnote whose
label is that `id`:

```markdown
---
type: knowledge
title: Example
sources:
- id: design
  resource: DESIGN.md
---

Parent Articles use their folder's name.[^design]

[^design]: Obsidience design notes
```

Write the footnote text as a title, not a bare file name: CommonMark reads
`[^design]: DESIGN.md` as a link definition rather than a footnote.

Sources are documentary provenance. They never bind code: a Tool's executable
entry point is the singular `obsidience.source`, which must match the
registered Capability exactly.

## Reserved documents

OKF reserves `index.md` (a directory listing) and `log.md` (an update history)
at every level. In the Vault they are never Articles: the Harness never reads
them as Articles, refuses to write an Article under those names (in any letter
case), and leaves them out of the graph. If you add one by hand, it must follow
OKF: an `index.md` has no frontmatter except an optional `okf_version` at the
Vault root, and a `log.md` groups entries under `## YYYY-MM-DD` headings.
`vault.validate` checks both.

## Validation

`vault.validate` checks the Vault in this order:

1. **OKF conformance** of every document (errors fail validation): parseable
   frontmatter, a non-empty `type`, and the reserved-document structure.
2. **Article profile** of every Article (errors fail validation): one of the six
   types, field shapes, namespace placement, Task-ledger separation and exact
   references.
3. **Load-bearing edges**: every `runbook`, `skills`, `tool`, `subtasks` and
   similar edge resolves to the right type, with one Skill per Tool.

OKF *SHOULD* guidance that a document departs from (a non-actor `generated.by`,
a timestamp without an offset, a body wikilink, a footnote without a matching
source) is listed on one advisory line and does not fail validation.

To check any directory as an OKF bundle, including a hand-authored one, call
the conformance checker directly:

```python
from pathlib import Path
from obsidience.harness.knowledge import okf

for finding in okf.check_bundle(Path("obsidience/defaults/vault")):
    print(finding.level, finding.rule, finding.path, finding.message)
```

`error` breaks OKF conformance, `warning` departs from SHOULD guidance, and
`info` is a condition readers must tolerate, such as a not-yet-written link
target or a checkout-relative source. The starter Vault (148 Articles) has no
errors or warnings; its infos are the checkout-relative sources and the absent
`okf_version` declaration.

## Writing an Article by hand

1. Pick the type from what the object does, then the folder: `Tools/`,
   `Skills/`, `Tasks/`, `Runbooks/`, `Agents/<Name>/` or a Knowledge folder.
   Never name the file `index.md` or `log.md`.
2. Start the file with `---`, the frontmatter, and a closing `---`. Write `type`
   and `title`; add a one-sentence `description`.
3. Put OKF fields at the root and application fields under `obsidience`. Leave
   out Task status and other runtime state.
4. Write timestamps with an offset and actors as `human:<you>`.
5. Link other Articles with Markdown links such as
   `[Ingest](/Tasks/ingest.md)`, and record provenance in `sources`.
6. Run `vault.validate` and fix every error. Reconcile advisories when you can.

When the Harness rewrites an Article it serializes
the frontmatter in its canonical YAML style (keys in order, long strings
folded); values, the body and its line endings are kept exactly.

## Where Obsidience departs from OKF

- Trust tiers are not derived from `verified`, and `verified` is never
  approval. Review owns acceptance.
- Unknown `type` values are valid OKF but are not Articles; the Vault admits only
  the six types.
- Checkout-relative `sources` resources, as described above.
- Typed relationships live in the `obsidience` namespace; body links stay
  untyped as in OKF.
- The Vault does not declare `okf_version` in a root `index.md`.
