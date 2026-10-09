# ADK model/Tool loop

Google ADK 2.11.0 runs the model/Tool loop of the Executive and of every
specialist Task. The model route is ADK's official `LiteLlm` (LiteLLM 1.101.0,
hash-pinned in `requirements.lock.txt`) to the local llama.cpp server under the
neutral served model id, so Tool results keep the template's native `tool`
role. LiteLLM is imported at startup with `LITELLM_LOCAL_MODEL_COST_MAP=True`.
Reasoning effort maps to the template thinking switch and reasoning budget;
reasoning stays private. ADK's LiteLLM client is replaced by one that fails
closed unless llama.cpp acknowledges the exact `input_token_limit`
(`X-LLAMA-Input-Token-Limit`/`X-LLAMA-Input-Tokens`) on every model step and
records the admitted count with the step's metrics.

- `sessions.py` owns the Executive conversation log: one ADK
  `SqliteSessionService` on `state/adk-sessions.sqlite3`. Events carry
  Obsidience producer kinds in `Part.part_metadata`; a conversation without a
  session is seeded from the public `conversation_turns` ledger. The provider
  sees the conversation window (`execution/native.py`, `conversation_window`);
  Hindsight recall and `observations.recall` carry what precedes it. There is
  no summary compaction. Specialist Tasks and evaluation trials keep an
  in-memory session for their run only.
- `plugin.py` (one `AgentPlugin` per activation, for any accountable Agent)
  carries the loop policy: the model lease per step, the shared native
  projection rewriting `LlmRequest` contents in `before_model_callback`,
  budgets, owner steering, argument validation with three strikes and the
  narrowing dispatch policy. The Executive's conversation adds the
  finite-choice lane, early speech and plain-text completion. A specialist
  Task advertises per step only the Tools its controller state allows, with
  the active proposal/completion contract schemas, and requires a Tool call
  (`tool_choice: required`); its Tool results carry the
  remaining decision budget, a third identical call is refused before
  dispatch, and only `task.complete` finishes.
- `tools.py` advertises one `BaseTool` per granted capability with the native
  schemas; `run_async` is one call of `execution/capability_core.py`
  (receipts, no-replay, completion authority, observation witnesses).
- `runner.py` starts one ADK `Runner` per activation, runs HassIL commands
  without a model, continues an activation only for owner clarifications or
  controller feedback, cancels only unfinished inference on foreground
  demand, and records settlement and interrupted calls in the log.
- `optimization.py` is the AutoSaddler V2 scenario port for `harness.optimize`.
  Trials run `run_adk_session` with an evaluation handler: isolated in-memory
  session, no Hindsight recall or writeback, every admitted call answered by
  frozen results or the contract validator (no dispatch or receipt), and a
  captured prompt replacing the history in contract mode. Specialist captures
  from the retired JSON action loop are converted to native Tool calls.

Restart only the Harness after changing this loop.
