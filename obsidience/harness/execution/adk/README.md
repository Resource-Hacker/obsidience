# ADK Executive loop (stage 1)

`executive_loop = "adk"` in `obsidience/obsidience.toml` runs the Executive's
model/Tool loop on Google ADK 2.11.0 instead of the DeepSeek Harness child.
The default stays `"deepseek"`; `execution/loops.py` selects one owner of the
Executive conversation for the Harness lifetime.

- `sessions.py` owns the conversation log: one ADK `SqliteSessionService` on
  `state/adk-sessions.sqlite3`. Events carry Obsidience producer kinds in
  `Part.part_metadata`; a conversation without a session (or with turns taken
  under the other loop) is seeded from the public `conversation_turns` ledger.
  The model route is ADK's official `LiteLlm` to the served model id, so Tool
  results keep the template's native `tool` role. LiteLLM is imported at
  startup with `LITELLM_LOCAL_MODEL_COST_MAP=True`.
- `plugin.py` (one `BasePlugin` per activation) carries the loop policy: the
  model lease per step, the shared native projection (`execution/native.py`)
  rewriting `LlmRequest` contents in `before_model_callback`, budgets, owner
  steering, the finite-choice lane, early speech, argument validation with
  three strikes, the narrowing dispatch policy and plain-text completion.
- `tools.py` advertises one `BaseTool` per granted capability with the native
  schemas; `run_async` is one call of `execution/capability_core.py`
  (receipts, uncertain effects, completion authority, observation witnesses).
- `runner.py` starts one ADK `Runner` per activation, runs HassIL commands
  without a model, continues a turn only for owner clarifications or
  controller feedback, and records settlement and interrupted calls in the log.

Not yet on this loop: summary compaction (the conversation window bounds the
prompt; manual Compact reports `unsupported`) and AutoSaddler evaluation
trials, which still run on DeepSeek. Rollback: set `executive_loop = "deepseek"`
(or remove it) and restart only the Harness.
