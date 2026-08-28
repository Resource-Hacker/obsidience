---
title: Model research procedure
kind: runbook
owner_maintained: true
for_agent: '[[Agents/Darwin/Darwin]]'
task: '[[Tasks/research/model]]'
skills:
- '[[Skills/inspecting-a-model]]'
- '[[Skills/registering-model-source]]'
- '[[Skills/benchmarking-a-model]]'
- '[[Skills/configuring-a-model]]'
---

1. Read the ordinary `model.added` Task parameters and select only their exact
   `model_id`. Fail if the event lacks a registered model or artifact.
2. Apply [[Skills/inspecting-a-model]] to record its role, capabilities,
   artifact status, valid device sets, current settings, and free VRAM.
3. Apply [[Skills/registering-model-source]] and require the returned immutable
   manifest path and fingerprint.
4. Apply [[Skills/benchmarking-a-model]] once to each relevant valid device
   set. Preserve a failed fit or runtime test as evidence; never widen the set,
   offload model layers to CPU, or substitute a different model.
5. Compare only commensurate metrics. For Task models consider throughput,
   context, output reserve, complete GPU residency, and intended work. For
   real-time components consider frame deadline, first output, interruption
   acknowledgement, and late-output tail.
6. If measurements justify a change, apply [[Skills/configuring-a-model]] with
   the smallest coherent settings change. There is no global operating profile:
   model and reasoning stay per Task, while Hardware keeps independent saved
   components.
7. Reinspect the model. Verify the selected settings, compatible GPU layouts,
   latest benchmark, Source records, and restored Hardware state.
8. Complete with the measured layouts, rejected layouts, chosen settings,
   intended Task or interface role, and exact Source paths. Fail honestly if
   no fully resident safe configuration exists.
