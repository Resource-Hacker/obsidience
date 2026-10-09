---
type: knowledge
title: Executive model selection
sources:
- resource: obsidience/harness/models/runtime.py
- resource: obsidience/harness/conversation/runtime.py
- resource: obsidience/harness/execution/executor.py
---

Model and reasoning effort belong to the execution owner: the Executive identity
for conversation, or the selected Task for independently queueable work.
The default Articles select `auto`; configure installed models, endpoints and
hardware in this installation before starting inference. Live model catalogs,
saved residency settings and measured Source manifests supply device layouts,
context limits and availability. This Article does not attest any machine.

Chat and speech use the same Executive identity and ADK model/Tool loop. Its
model route is ADK's LiteLLM adapter (pinned LiteLLM) to the local llama.cpp
server under the neutral served model name. There is no preliminary model request to route conversational work.
A model lease owns the required resources and restores saved assignments after
release. Speech, vision sensors and model servers remain components, not Agents.

Model capacity cannot expand Tool grants or weaken argument validation,
receipts, cancellation, target verification or completion acceptance.
See [Cordis composition](/Architecture/Harness/cordis-composition.md)
and [Real-time Executive](/Architecture/Harness/real-time-executive.md).
