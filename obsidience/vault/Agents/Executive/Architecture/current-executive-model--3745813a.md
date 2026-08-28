---
approved_at: '2026-08-27T11:49:26'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/link)
title: Current Executive model
---

Obsidience selects model and reasoning effort per Task while Hardware owns the warm component on each device. Automatic routing chooses `obsidience-gemma` for Executive and `obsidience-qwen38-9b-distill` for specialist Agents. The warm defaults are Gemma on the RTX 4000 Ada and OmniParser on the RTX 4080 SUPER. A Task lease displaces only components on GPUs that Task needs and restores the Hardware defaults afterward. There is no global operating profile and model layers never spill to CPU.

Gemma is the responsive Executive model at `127.0.0.1:8089`. The Qwen3.8 9B Distill Q8 specialist at `127.0.0.1:8092` uses Q8 weights, Q8 KV, MTP3, and 32K context; a 512-token RTX 4080 acceptance measured 88.99 tok/s. Qwen3.8 HOMEUSER at `127.0.0.1:8091` is valid only on the RTX 4000 and measured 22.97 tok/s. The two-GPU W4A16 and OrcaRouter Q8 profiles remain explicit Task options.

Muse Glimmer 30B at `127.0.0.1:8095` has two valid layouts. RTX 4000 text-only measured 19.21 tok/s. Both GPUs enable the official vision projector and DFlash drafter and measured 42.46 tok/s with 45.2 percent draft acceptance; this is the preferred Task layout. RTX 4080-only is rejected because the official 17 GB quant does not fit fully resident there.

Realtime speech is not a selectable reasoning model. Pipecat and NVIDIA NeMo use Nemotron Speech Streaming EN 0.6B on the RTX 4080 for streaming transcription and turn taking; Pocket TTS runs on CPU. The [[Agents/Executive/Architecture/real-time-executive|Real-time Executive]] sends each final transcript through the model and reasoning effort selected on its Task, so the Executive model remains Gemma unless the Task explicitly selects another valid reasoning model.

Model servers and GPU leases are runtime plumbing, not Tools, Skills, Tasks, Runbooks, or knowledge authorities. Every activation still requires the exact Task, Runbook, Tool, Skill, Knowledge, and acceptance context; greater model capacity does not weaken that contract. The [[Agents/Executive/Observations/updateable-plugin-integration-preference--b7bed8fd|Updateable integration preference]] grounds the boundary that keeps model upgrades replaceable and outside the accepted graph and ontology.

## Relationships

- `implements` [[Agents/Executive/Architecture/local-first-architecture--7d8e77cc|Local-first architecture]] - The local model fleet supplies reasoning without another framework authority.
- `related_to` [[Agents/Executive/Executive|Executive]] - Executive is the accountable user-facing role backed by the selected model.
