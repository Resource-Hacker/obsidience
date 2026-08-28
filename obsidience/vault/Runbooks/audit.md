---
title: Audit procedure
kind: runbook
owner_maintained: true
for_agent: '[[Agents/Heimdall/Heimdall]]'
task: '[[Tasks/audit]]'
skills:
- '[[Skills/listing-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/reading-source-evidence]]'
- '[[Skills/validating-the-vault]]'
- '[[Skills/proposing-changes]]'
---

1. Select one bounded audit scope: a material claim, its Source support, a
   suspected contradiction, or the load-bearing links around one article.
2. Read the complete article, relevant accepted neighbors, and each relied-on
   Source. For a graph audit, call `vault.validate` once and inspect only the
   exact reported edges. For a contradiction audit, compare the complete claims
   rather than matching isolated phrases.
3. Compare scope, dates, qualifiers, attribution, and relationship direction.
   Classify evidence as supported, weakened, contradicted, or unresolved; classify
   graph edges as valid or broken. Do not reduce uncertainty to a binary verdict.
4. Treat reports and summaries as leads. Source bytes, graph state, and the
   execution ledger are evidence. Never invent the intended target of an
   ambiguous link.
5. If a grounded correction is necessary, stage at most one complete article
   update. Heimdall never approves his own proposal and never edits Source.
6. Finish with `review` for a proposal or `completed` with the exact scope,
   classification, counts, and citations. A clean audit is valid.
