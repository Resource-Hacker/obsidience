"""The installation's Executive loop: `executive_loop = "deepseek" | "adk"` in obsidience.toml.

Both loops provide the same two contracts: ``run_session`` (the activation
runner, signature of ``deepseek.runner.run_native_session``) and a ``sessions``
module that owns the conversation log (start/stop/close, view/refresh/reconcile,
context, measure_context, rebase_window, compaction and prefill messages).
Exactly one loop owns the Executive conversation in a Harness lifetime.
"""
from __future__ import annotations

from ..config import CONFIG

LOOPS = ("deepseek", "adk")


def selected() -> str:
    value = str(CONFIG.extras.get("executive_loop", "deepseek"))
    if value not in LOOPS:
        raise ValueError(f"executive_loop must be one of {', '.join(LOOPS)}")
    return value


def sessions():
    """The selected loop's conversation-log owner."""
    if selected() == "adk":
        from .adk import sessions
        return sessions
    from .deepseek import sessions
    return sessions


def run_session():
    """The selected loop's Executive activation runner."""
    if selected() == "adk":
        from .adk.runner import run_adk_session
        return run_adk_session
    from .deepseek.runner import run_native_session
    return run_native_session
