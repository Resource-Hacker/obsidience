---
type: knowledge
title: Executive model selection
obsidience:
  approved_at: '2026-08-27T11:49:26'
  provenance: proposed by Alexandria (task Tasks/link)
---

Model and reasoning effort belong to each Task. An explicit Task selection wins;
automatic routing is only the fallback. The fallback chooses the responsive
local Gemma model for Executive work and the fully GPU-resident Qwen specialist
model for other Agents. [Query](/Tasks/query.md) and
[Computer Use](/Tasks/executive/operate.md) explicitly select `obsidience-gemma`;
their authored reasoning efforts remain independent.

Hardware owns the warm component assigned to each device. A Task lease may
temporarily displace only the components on hardware it needs and restores the
saved assignments afterward. Model layers never spill to CPU. The live Models,
Hardware, and Source manifests—not this Architecture Article—are authoritative
for ports, quantization, benchmark results, context sizes, and valid GPU layouts.

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

- `implements` [Local-first architecture](/Agents/Executive/Architecture/local-first-architecture--7d8e77cc.md) — Local Task models remain replaceable runtime components rather than framework authorities.
- `depends_on` [Task activation](/Agents/Executive/Architecture/task-activation--b30a4642.md) — The selected Task is the sole source of model and reasoning effort.
- `related_to` [Real-time Executive](/Agents/Executive/Architecture/real-time-executive.md) — Speech delivers work to the same per-Task model selection as typed Chat.
