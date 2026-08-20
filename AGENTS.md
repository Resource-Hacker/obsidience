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

## Phase 1 directive (owner, 2026-08-20) — finish before anything else

Codex now owns Obsidience development. The single interpreter must perform the
old fleet's Curator, Researcher, and Guardian duties as vault task families —
NOT as agents. Full directive with the gap list and acceptance criteria:
`~/Documents/HEREBRUM-Subagent-Architecture.html`. Summary of gaps to build:

- Curator: `curate-note` (one bounded improvement/pass), `archive-stale`
  (+ `_archived/` move convention in review).
- Researcher (all new): `web.fetch` + `web.search` tools, `safe-web-research`
  skill (one source per doc, dates+URLs, failed-fetch honesty, backpressure
  ≥3 pending → stop), `learn` + `research-a-question` runbooks/tasks;
  proposals target `Sources/` (raw layer only — never Knowledge directly).
- Guardian: `evidence-audit` (sample claims → supported/weakened/contradicted/
  unresolved → bounded proposals), `verify-harness` (+ deterministic
  `harness.status` tool), runbook content hash recorded in receipts.

Knowledge import from the old system starts only after Phase 1 acceptance.
