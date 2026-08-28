---
approved_at: '2026-08-21T04:02:08'
kind: skill
provenance: proposed by Codex (task research generation kit)
title: Propose article change
tool: '[[Tools/vault.propose]]'
---

How to propose vault changes that pass review.

- Read the target in this session and search for duplicates before proposing.
- Keep one concern per proposal; several small proposals beat one large one.
- `update` proposals contain the complete corrected body. Existing accepted metadata is preserved unless safe replacement fields are supplied in `metadata`.
- Never stage a second unresolved proposal for the same Article. Decide the
  first proposal or rerun against the newly accepted revision.
- The proposal body starts below the Article title. Do not copy the synthetic
  leading `# Title` shown by `vault.read`; the canonical title is frontmatter.
- Use only the safe typed metadata needed by the Article: `kind`, a Tool's exact
  `capability:<Tool title>` binding and singular matching `source`, singular
  Skill `tool`, Runbook `skills`, Task `runbook`, agent `assignee`, reasoning
  effort, owner-maintained state, or recursive child edges. Never supply plural
  `sources` for a Tool.
- The reason cites evidence with exact Article paths and fits in two sentences.
- When the exact Link Task invokes this Tool, preserve every existing useful
  link and let the harness classify the review. The Review pane will show the
  added and removed Article links; never supply `review_class` yourself.
- Never claim that a proposal is accepted. Finish with review status and name every staged article.
