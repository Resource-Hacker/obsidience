---
binding: capability:task.complete
kind: tool
source: obsidience/harness/capabilities/task/complete.py
title: task.complete
---

End the active Task session with one terminal result.

Arguments: `{"status": "completed|failed|review", "summary": "..."}`.

The Tool is always available. The summary records the verified outcome,
proposal, or exact blocker. Tool success means the result was recorded; it does
not independently prove that the Task acceptance condition was satisfied.

`review` is valid only when this exact execution staged at least one unresolved
proposal or the Task Article has an explicit authored acceptance gate. A
downstream Task's review state does not put the caller in review.

An archive with an exact `Merge is incomplete` blocker cannot complete review.
The Tool returns the missing referring Article refs so the active Merge can
stage their redirects and retry completion.
