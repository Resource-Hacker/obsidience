# Executive composition

DeepSeek Harness 0.2.0-rc.2 and Cordis 4.0.4 are pinned together. The
supported `dsh --profile obsidience` launcher runs the upstream DeepSeek
agent loop. The API lifespan owns one resident child, inherited private pipes,
and teardown. `plugin.mjs` supplies scoped native Tools, identity/prompt assembly,
model transport, step boundaries and cancellation through public Cordis APIs.
It contains no model decision loop. `runner.py` binds these ports to the existing
model resource owner and shared `CapabilityDispatch` operation/receipt boundary.

Install the exact dependencies from this directory with:

```sh
npm ci --ignore-scripts --no-audit --no-fund
```

Python requirements remain in `../../requirements.txt`. Restart only the Harness
after changing this composition. The generated CLI profile lives below the
existing runtime directory; no extra daemon or systemd service is installed.

The full native argument contract comes from `capabilities/registry.py` and is
validated before dispatch. The advertised schema uses DeepSeek's supported
vocabulary and typed object unions that Gemma's native template can render.
Conditional requirements and string/numeric bounds remain enforced by the
original schema and capability owners. Tool calls use the provider's native
function channel. Ordinary text passes the shared completion authority locally,
without asking the model to generate an extra completion call.

Native V4 messages use producer-owned source kinds and first-class Tool roles.
The model adapter keeps Tool call IDs and fresh image attachments intact and
filters internal outcome records before provider inference. Native detached
inspection uses the session owner's registered message projections. Manual
compaction shares the turn's cancellation lifetime and drains before lease release.

One persistent native DeepSeek session owns each Executive conversation, with
the same ID for typed Chat and final voice transcripts. The upstream JSONL
persistence plugin saves native user, assistant and Tool events and resumes them
after a Harness restart. SQLite owns public Chat projection and ingress, Tool
intents/results and continuation records. `sessions.py` projects native history
for context and prewarming and reconciles accepted replies. The pinned native
`dsh-compaction-basic` and `dsh-token-meter` plugins own automatic pressure,
confirmed-overflow recovery and manual compaction. Summary inference borrows the
existing model reservation and cannot execute Tools or become a public reply.
Native checkpoints shadow balanced spans while retaining the original JSONL log.
The configured threshold
is kept in the existing settings ledger (60–90%, default 80%); automatic compaction
retains a recent tail of 16% of the model window and summary output is capped at
2,048 tokens within the model's output allowance. Manual compaction occupies the
same Executive work slot; STOP or new foreground input cancels summary inference
and drains native maintenance before releasing the existing model lease.
Only the next model request may resolve an observation image; bytes and leases
stay in memory and are consumed on that response. Unknown/stale/failed/uncertain
effects retain the existing rejection and no-replay rules.

The Executive's accepted identity and Skill bindings still decide which real
capabilities exist for it. The Thinking Packet contains identity, current
context and retrieved knowledge. Advertising a native capability does not claim
that its Tool or Skill Article body was read. Scheduled and specialist Tasks
retain their authored Task/Runbook procedures and share the operation boundary.

Obsidience supplies application services to DeepSeek through this adapter.
`vault.search`, `vault.read` and `vault.list` expose its existing knowledge owner
as native Tools. Fast context retrieval uses that same index before the first
model step; further retrieval is chosen in the native loop. Source capture,
Article proposals and Review keep their existing writers and receipts.
This follows the knowledge-provider pattern in
[Tencent's dsh-weknora plugin](https://github.com/Tencent/WeKnora/tree/1ef38fdb8b19347b82d3a99f6f17d75ac09ad606/packages/dsh-weknora).
The comparison adopted a design reference, with no WeKnora runtime dependency
or copied code. Its optional server-side answer pipeline is not part of the
Executive path; the current model reasons over returned evidence directly.

`hindsight.mjs` mounts the optional native Cordis memory service. Its bounded,
non-generative recall comes from the Agent-scoped Obsidience port; Hindsight
owns historical observations while the existing Vault and Alexandria/Review
own durable Knowledge. Deployment and the complete retention/promotion flow
are documented in [the memory port](../../memory/README.md).

Versions, npm integrity records and licensing are recorded in `package-lock.json`
and the repository's `artifacts.lock.json`. Upstream remains a developer preview;
update the lock and adapter together, then exercise real Chat, voice, a native
Tool, observation and cancellation before changing the live composition.
