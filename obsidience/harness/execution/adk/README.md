# ADK Executive loop

Google ADK 2.11.0 runs the Executive's model/Tool loop. The model route is
ADK's official `LiteLlm` (LiteLLM 1.101.0, hash-pinned in
`requirements.lock.txt`) to the local llama.cpp server under the neutral served
model id, so Tool results keep the template's native `tool` role. LiteLLM is
imported at startup with `LITELLM_LOCAL_MODEL_COST_MAP=True`.

- `sessions.py` owns the conversation log: one ADK `SqliteSessionService` on
  `state/adk-sessions.sqlite3`. Events carry Obsidience producer kinds in
  `Part.part_metadata`; a conversation without a session is seeded from the
  public `conversation_turns` ledger. The provider sees the conversation window
  (`execution/native.py`, `conversation_window`); Hindsight recall and
  `observations.recall` carry what precedes it. There is no summary compaction.
- `plugin.py` (one `BasePlugin` per activation) carries the loop policy: the
  model lease per step, the shared native projection rewriting `LlmRequest`
  contents in `before_model_callback`, budgets, owner steering, the
  finite-choice lane, early speech, argument validation with three strikes,
  the narrowing dispatch policy and plain-text completion.
- `tools.py` advertises one `BaseTool` per granted capability with the native
  schemas; `run_async` is one call of `execution/capability_core.py`
  (receipts, no-replay, completion authority, observation witnesses).
- `runner.py` starts one ADK `Runner` per activation, runs HassIL commands
  without a model, continues a turn only for owner clarifications or
  controller feedback, and records settlement and interrupted calls in the log.
  A run without a conversation keeps an in-memory session for that run only.
- `optimization.py` is the AutoSaddler V2 scenario port for `harness.optimize`.
  Executive trials run `run_adk_session` with an evaluation handler: isolated
  in-memory session, no Hindsight recall or writeback, every admitted call
  answered by frozen results or the contract validator (no dispatch or
  receipt), and a captured `native_wire` prompt replacing the history in
  contract mode.

Restart only the Harness after changing this loop.
