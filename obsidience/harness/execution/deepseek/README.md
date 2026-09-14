# Executive composition

The supported `dsh --profile obsidience` launcher runs the upstream DeepSeek
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

DeepSeek session objects are ephemeral per activation. The existing SQLite
conversation, Tool intents/results and continuation records remain authoritative.
Only the next model request may resolve an observation image; bytes and leases
stay in memory and are consumed on that response. Unknown/stale/failed/uncertain
effects retain the existing rejection and no-replay rules. No DeepSeek shell,
independent scheduler, file persistence or attachment-file plugin is installed.

The Executive's accepted identity and Skill bindings still decide which real
capabilities exist for it. The Thinking Packet contains identity, current
context and retrieved knowledge. Advertising a native capability does not claim
that its Tool or Skill Article body was read. Scheduled and specialist Tasks
retain their authored Task/Runbook procedures and share the operation boundary.

Versions, npm integrity records and licensing are recorded in `package-lock.json`
and the repository's `artifacts.lock.json`. Upstream remains a developer preview;
update the lock and adapter together, then exercise real Chat, voice, a native
Tool, observation and cancellation before changing the live composition.
