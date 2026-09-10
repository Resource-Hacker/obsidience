---
type: knowledge
title: Executive model selection
sources:
- resource: obsidience/harness/models/runtime.py
- resource: obsidience/harness/conversation/runtime.py
- resource: obsidience/harness/execution/executor.py
obsidience:
  approved_at: '2026-09-10T23:49:22.333585+00:00'
  provenance: Owner-authorized Architecture reorganization and source audit at a3a04c6add819a67662a1116e643713a3b4c1324
---

Model and reasoning effort belong to each Task. An explicit Task selection wins;
automatic routing is only the fallback. The fallback chooses the responsive
local Gemma model for Executive work and the fully GPU-resident Qwen specialist
model for other Agents. [Query](/Tasks/query.md) and
[Computer Use](/Tasks/executive/operate.md) explicitly select `obsidience-gemma`;
their authored reasoning efforts remain independent.

Settings > AI & Voice stores the residency selection for each device; the model
runtime enforces it. The Hardware monitoring pane does not select models. A Task lease may
temporarily displace only the components on hardware it needs and restores the
saved assignments afterward. Model layers never spill to CPU. The live Models catalog, saved residency settings and attested Source manifests,
not this Architecture Article, supply ports, quantization, measurements, context
sizes and valid GPU layouts. Hardware telemetry reports observed device state.

One selected reasoning model handles one activation. Speech recognition,
turn-taking, speech synthesis, vision projectors, and model servers are runtime
components, not additional Agents or reasoning authorities. A spoken request
uses the model and reasoning effort on its selected work Task, exactly as the
same typed request does. The Realtime connection has no model selector.

Model capacity never relaxes the exact Task, Runbook, Tool, Skill, Knowledge,
and acceptance contract. A model that cannot fit a valid hardware layout or the
actual provider request fails clearly rather than partially offloading or
silently truncating context.

## Relationships

- `implements` [Local-first architecture](/Agents/Executive/Architecture/Harness/local-first-architecture--7d8e77cc.md) — Local Task models remain replaceable runtime components rather than framework authorities.
- `depends_on` [Task activation](/Agents/Executive/Architecture/Harness/task-activation--b30a4642.md) — The selected Task is the sole source of model and reasoning effort.
- `related_to` [Real-time Executive](/Agents/Executive/Architecture/Harness/real-time-executive.md) — Speech delivers work to the same per-Task model selection as typed Chat.
