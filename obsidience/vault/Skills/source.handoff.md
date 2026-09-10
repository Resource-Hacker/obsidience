---
type: skill
title: Using source.handoff
obsidience:
  tool: '[[Tools/source.handoff]]'
---

For Feed Distill, deliver the complete concise item summary once, preserving reporting dates and qualifications and citing the exact activating item plus any linked reporting actually used. The controller retains destination provenance. For Feed Distill, send exactly `title` and `content`; put all `source://` citations inside the Markdown content. There is no top-level `source_citations` argument. A successful handoff completes Distill; it does not claim Knowledge publication, and a changed second summary is rejected.

Deliver one complete supported finding from an authorized Darwin Research execution. Identity and destination come from the runtime.

Use `title` plus cited Markdown `content`, retaining dates, uncertainty and limitations; do not send transcripts or Source dumps.

Use the returned Inbox citation and `dropped` or `already present` delivery state. Neither claims publication. Report rejection precisely; do not fabricate evidence or repeat successful delivery.
