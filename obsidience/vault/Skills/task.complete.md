---
type: skill
title: Using task.complete
obsidience:
  tool: '[[Tools/task.complete]]'
  approved_at: '2026-09-06T01:05:00'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

Use `task.complete` to record one terminal result for the active execution.

- Pass `{"status": "completed|failed|review", "summary": str}`.
  Keep `summary` within 2,000 characters and describe only the verified outcome,
  staged proposal, or exact blocker. Unknown statuses are rejected.
- `completed` requires an established outcome, `failed` records a terminal
  blocker, and `review` requires either a proposal staged by this exact
  execution or an explicit authored acceptance gate. A downstream status does
  not change the caller's status.
- If an evidence-bound maintenance or Ingest inspection needs no change, add
  `"outcome": "no_change", "evidence": ["exact inspected refs and supported conclusion"]`.
  Evidence has at most eight nonempty entries, 500 characters each. A short
  summary alone is not evidence. Never claim no-change after staging or publishing.
- A controller-attested `Article published` result may complete as changed.
  An unresolved staged proposal still requires `review`.
- Success returns `accepted: true` with the recorded status and summary. Tool
  success proves recording only; it does not independently prove the outcome.
- For interactive work, put the public answer in `summary`. Typed Chat and
  speech deliver that same terminal result; completion leaves an enabled
  speech connection available for the next request.
- Computer Use can finish `completed` only after the requested Tool returns
  its verified outcome. A fresh visual observation supports a visual answer;
  focus requires `window.activate`, placement requires `window.place`, and a
  launch requires a ready window. The returned semantic target must match any
  explicit application binding, and tile placement must return the exact
  attested destination edges. Intent, error text, dispatch, and input
  acknowledgement are insufficient. If no target is uniquely identified, finish
  `failed` with the clarification question in `summary`; if an operation is
  blocked, use `failed` with the exact blocker. Deliberate failure feedback is
  public but never becomes a successful assistant conversation turn.
- On `accepted: false`, stop and preserve the returned error. Invoke again only
  after the stated completion precondition has materially changed; never relabel
  an unverified result merely to obtain acceptance.

Controller-bound computer outcomes apply to every Task: Query cannot complete a computer action. For action, computer_scope must explicitly be input or state. Input requires the latest acknowledged click and actual fresh post-image. State additionally requires a current post-action image attached to the immediately preceding model input, plus verification: {"status":"established","observation":"visible evidence supporting the requested application state"}. The verification object has exactly status and observation, with 1-1,000 observation characters. It records the model's interpretation; it does not turn input delivery into independently verified semantic truth. An intervening Tool or response consumes that immediate image evidence. If the state is not established, complete failed with the actual limit; never manufacture evidence or relabel success. Historical receipts cannot satisfy a current outcome.
