---
type: runbook
title: Model research procedure
obsidience:
  owner_maintained: true
  for_agent: '[[Agents/Heimdall/Heimdall]]'
  task: '[[Tasks/research/model]]'
  skills:
  - '[[Skills/model.inspect]]'
  - '[[Skills/model.source]]'
  - '[[Skills/model.benchmark]]'
  - '[[Skills/model.configure]]'
  - '[[Skills/observations.retain]]'
  - '[[Skills/observations.recall]]'
---


1. Read the ordinary `model.added` Task parameters and select only their exact
   `model_id`. Fail if the event lacks a registered model or artifact.
2. Apply [model.inspect](/Skills/model.inspect.md) to record its role, capabilities,
   artifact status, valid device sets, current settings, and free VRAM.
3. Apply [model.source](/Skills/model.source.md) and require the returned immutable
   manifest path and fingerprint.
4. If `hardware_assignable` is false or there is no nonempty valid local device set, complete with the inspected manifest and the explicit external-hardware limitation. Do not invent device names or benchmark/configure that external model. Otherwise apply [model.benchmark](/Skills/model.benchmark.md) once to each relevant valid device
   set. Preserve a failed fit or runtime test as evidence; never widen the set,
   offload model layers to CPU, or substitute a different model.
5. Compare only commensurate metrics. For Task models consider throughput,
   context, output reserve, complete GPU residency, and intended work. For
   real-time components consider frame deadline, first output, interruption
   acknowledgement, and late-output tail.
6. Compare proposed settings with inspected current settings first. If identical,
   skip configuration: unchanged settings need no restart or configuration Source.
   If measurements justify an actual change, apply [model.configure](/Skills/model.configure.md) with
   the smallest coherent settings change. There is no global operating profile:
   model and reasoning stay per Task, while Hardware keeps independent saved
   components.
   Saved configuration with failed or interrupted runtime reconciliation is a
   committed effect. Preserve its Source, report readiness as unverified and
   never replay configuration to hide that failure.
7. Reinspect the model. Verify the selected settings, compatible GPU layouts,
   latest benchmark, Source records, and restored Hardware state.
8. Complete with the measured layouts, rejected layouts, chosen settings,
   intended Task or interface role, and exact Source paths. Fail honestly if
   no fully resident safe configuration exists.


When a useful nonredundant observation should survive this activation, optionally retain one bounded unverified note in this Agent's own Hindsight bank. Do not record hidden reasoning or create a note merely to narrate routine work.
