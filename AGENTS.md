# Obsidience — assistant guidance

This is the GREENFIELD graph-native harness experiment (parallel to the
Hermes-plugin conversion happening elsewhere). Read DESIGN.md first; its Laws
section is binding. Rules for working here:

- Do NOT modify the legacy stacks from this project (~/.local/src/opendex-hermes,
  /var/lib/ai/src/*, ~/.hermes) — copy-in only, and note provenance.
- Everything under ui/src/components/themes/jarvis/ and ui/src/main/tts/ is
  copied from HEREBRUM (2026-08-20) and then adapted; keep adaptations minimal
  and prefer thin hosts over editing the copied engine files.
- The vault is user-owned: never hand-edit accepted notes from automation;
  agent writes go through _staging/ + review. The harness alone writes
  Receipts/ and task status fields.
- Keep it a dev build: small modules, no ceremony, no new frameworks.
- After every source or vault change, restart the affected Obsidience dev
  process and verify its live health so the owner can test each iteration.
- The Library is the curated canonical repository and green book satellite for
  Tools, Skills, Runbooks, and Tasks. Jobs is only the scheduler surface for
  creating and operating scheduled tasks; do not turn it back into the catalog.
- Library checkout state is stored as typed wikilinks on the target identity
  note, never as a second ledger or a copied canonical note. UI order is
  Executive, Guardian, Curator, Researcher; highlighted means checked out.
- Graph hierarchy nodes are articles in the Reader. Never discard `@` node
  clicks: prefer the subject's authored `index.md` or `README.md`, then use a
  read-only generated index over its children when no authored hub exists.
- All four Library primitives use ordered recursive same-kind edges: `subtasks:`,
  `subrunbooks:`, `subskills:`, and `subtools:`. Keep one generic hierarchy
  projection in code; do not reintroduce task-only tree rendering. A parent
  checkout projects its descendant closure without copying canonical notes.
- Dotted callable Tool names project generated namespace index articles in the
  Library (`task` → `complete`, `create`; `vault` → its callable leaves). Keep
  canonical checkout storage on the real descendant Tool refs, never the
  generated `@library/Tools/*` presentation IDs.
- The Task shelf projects the owner-authored `executive`, `wiki`, and `research` taxonomy
  from `harness/obsidience/task_taxonomy.py`. Taxonomy nodes are stateless
  Reader articles, not runnable tasks; real Task notes absorb matching leaves,
  and only their authored `subtasks:` dispatch. Their stable
  `@library/Tasks/*` refs may be stored in an identity's `tasks:` checkout list
  and project the selected taxonomy closure without making it executable. The
  detailed `wiki/guard` tree supersedes the earlier short guard sketch.
- `Tasks/executive/assistant` is displayed as `Voice Assistant`
  and is the `voice.activation` event task. Voice-originated Operator turns
  enter that task context; typed turns do not. Executive task families are its
  siblings directly beneath `executive`, not children of `assistant`. HEREBRUM
  remains read-only source provenance and is never modified from this project.
- Expandable generated taxonomy rows are indexes; terminal generated leaves are
  articles. The Library must label them accordingly.
- The Skill shelf projects a generated one-for-one mirror of dotted callable
  Tools (`task/complete`, `task/create`, `vault/list`, and so on). Each Skill
  leaf reads as how to use its Tool and incorporates any authored Skill notes
  that declare that Tool. Authored Skills remain the canonical runtime
  authorization primitives; mirrors are Library navigation/checkouts.

## Phase 1 directive (owner, 2026-08-20) — finish before anything else

Codex now owns Obsidience development. The subagents are LITERAL agents
(owner decision 2026-08-20): Alexandria (curator), Darwin (researcher), and
Heimdall (guardian) exist as identities under `Agents/<Name>/`, tasks bind via
`assignee:`, one interpreter runtime executes each session AS the assigned
agent, and each agent renders as its own satellite ball orbiting the main
graph (already implemented). Phase 1 = complete each agent's duty kit.
Full directive with the gap list and acceptance criteria:
`~/Documents/HEREBRUM-Subagent-Architecture.html`. Summary of gaps to build:

- Curator: `curate-note` (one bounded improvement/pass), `archive-stale`
  (+ `_archived/` move convention in review).
- Researcher (all new): `web.fetch` + `web.search` tools, `safe-web-research`
  skill (one source per doc, dates+URLs, failed-fetch honesty, backpressure
  ≥3 pending → stop), `learn` + `research-a-question` runbooks/tasks;
  proposals target `Sources/` (raw layer only — never the Agent layer directly).
- Guardian: `evidence-audit` (sample claims → supported/weakened/contradicted/
  unresolved → bounded proposals), `verify-harness` (+ deterministic
  `harness.status` tool), runbook content hash recorded in receipts.

Knowledge import from the old system starts only after Phase 1 acceptance.
