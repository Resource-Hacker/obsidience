"""Codex and Claude Code as cloud session models, through their unmodified CLIs.

The model catalog (``runtime``) owns model identity; this module discovers what
each installed CLI offers and runs one structured, tool-less session. Each CLI
keeps its own sign-in: the shared ChatGPT login for Codex, the owner's Claude
account for Claude Code. Nothing here reads, copies or forwards credentials.

A session answers one whole request with JSON matching a schema. The CLIs return
no client-side function calls, so they cannot drive Obsidience's native Tool
loop; they serve whole-request sessions such as Harness2 proposals.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

CODEX, CLAUDE = "codex", "claude"
PROVIDERS = (CODEX, CLAUDE)
CLI = {CODEX: Path.home() / ".local/bin/codex", CLAUDE: Path.home() / ".local/bin/claude"}
CODEX_CONFIG = Path.home() / ".codex/config.toml"
# `codex:default` follows the model the owner set for Codex itself.
DEFAULT = "default"
MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
# Claude Code resolves these aliases to the newest model of each family at run time.
CLAUDE_ALIASES = {
    "fable": ("Claude Fable (latest)", "Anthropic's most capable model family"),
    "opus": ("Claude Opus (latest)", "Frontier Opus family"),
    "sonnet": ("Claude Sonnet (latest)", "Balanced Sonnet family"),
    "haiku": ("Claude Haiku (latest)", "Fast Haiku family"),
}
# Obsidience reasoning levels -> CLI levels. The top Obsidience level asks for each
# provider's deepest reasoning without delegation: Codex `ultra` adds automatic
# sub-agent delegation, which a tool-less session cannot use.
EFFORT = {"none": "low", "low": "low", "medium": "medium", "high": "high", "xhigh": "max"}
# Context the session's own ModelSpec records (identity only; never a wire cap).
CONTEXT_TOKENS = {CODEX: 272_000, CLAUDE: 1_000_000}
# A cloud session at the deepest reasoning can take minutes; the caller's job budget
# still bounds the whole optimization.
SESSION_SECONDS = 600
# Claude Code enforces this client-side estimate per session (subscription or not).
CLAUDE_SESSION_BUDGET_USD = 5.0
SYSTEM_ARG_MAX = 100_000
DISCOVERY_TTL_SECONDS = 15 * 60
# Codex features that would give a session tools, extra context or a faster tier.
CODEX_DISABLED = ("shell_tool", "unified_exec", "multi_agent", "memories", "apps", "plugins",
                  "hooks", "browser_use", "computer_use", "image_generation", "view_image",
                  "fast_mode", "ultrafast_mode")
# Keep the plain-login route: API keys, gateways or another provider never redirect it.
DROP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
            "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
            "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "OPENAI_API_KEY", "OPENAI_BASE_URL",
            "CODEX_API_KEY")
# JSONL items that would mean the session acted instead of answering.
EFFECT_ITEMS = {"command_execution", "file_change", "mcp_tool_call", "web_search"}


class CloudSessionError(ValueError):
    """The CLI ran but returned no complete structured answer."""


@dataclass(frozen=True)
class CloudReply:
    content: str
    finish_reason: str
    completion_tokens: int | None
    prompt_tokens: int | None
    provider_metrics: dict


def split_id(model_id: str) -> tuple[str, str] | None:
    """``codex:<model>`` or ``claude:<alias>``; None for anything else."""
    provider, _, name = str(model_id).partition(":")
    if provider in PROVIDERS and MODEL_NAME.match(name):
        if provider == CLAUDE and name not in CLAUDE_ALIASES and not name.startswith("claude-"):
            return None
        return provider, name
    return None


def codex_default_model() -> str:
    """The `model` the owner set in Codex's own config, or "" when unset."""
    try:
        value = tomllib.loads(CODEX_CONFIG.read_text()).get("model")
    except (OSError, ValueError):
        return ""
    return value if isinstance(value, str) and MODEL_NAME.match(value) else ""


def _label(provider: str, name: str) -> str:
    if provider == CLAUDE:
        return CLAUDE_ALIASES.get(name, (name, ""))[0]
    return "-".join(part.upper() if index == 0 else part.capitalize()
                    for index, part in enumerate(name.split("-")))


def describe(model_id: str) -> dict:
    """Deterministic identity for a cloud model id (no CLI call)."""
    parsed = split_id(model_id)
    if parsed is None:
        raise ValueError(f"unknown cloud model: {model_id}")
    provider, name = parsed
    cli_model = codex_default_model() if provider == CODEX and name == DEFAULT else name
    label = _label(provider, cli_model) if cli_model else "Codex default"
    return {"provider": provider, "cli_model": cli_model,
            "label": label + (" · Codex" if provider == CODEX else " · Claude Code"),
            "context_tokens": CONTEXT_TOKENS[provider]}


_DISCOVERY: dict[str, tuple[float, dict]] = {}
_DISCOVERY_LOCK = threading.Lock()


def _run(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False,
                          stdin=subprocess.DEVNULL, env=_env(), cwd=tempfile.gettempdir())


def _discover(provider: str) -> dict:
    cli = CLI[provider]
    if not cli.exists():
        return {"available": False, "error": f"{cli} is not installed", "version": "", "models": []}
    version = _run([str(cli), "--version"], 15).stdout.strip()
    if provider == CLAUDE:
        models = [{"name": name, "label": label, "description": description,
                   "context_tokens": CONTEXT_TOKENS[CLAUDE]}
                  for name, (label, description) in CLAUDE_ALIASES.items()]
        return {"available": True, "error": "", "version": version, "models": models}
    # The account's refreshed catalog (the CLI falls back to its cached copy).
    result = _run([str(cli), "debug", "models"], 30)
    try:
        rows = json.loads(result.stdout)["models"]
    except (ValueError, KeyError, TypeError):
        return {"available": False, "error": "codex debug models returned no catalog",
                "version": version, "models": []}
    models = []
    for row in sorted((r for r in rows if isinstance(r, dict) and r.get("visibility") == "list"),
                      key=lambda r: r.get("priority", 999)):
        name = str(row.get("slug", ""))
        if MODEL_NAME.match(name):
            models.append({"name": name, "label": str(row.get("display_name") or _label(CODEX, name)),
                           "description": str(row.get("description") or ""),
                           "context_tokens": int(row.get("context_window") or CONTEXT_TOKENS[CODEX]),
                           "reasoning_levels": [level.get("effort") for level in
                                                row.get("supported_reasoning_levels", [])
                                                if isinstance(level, dict)]})
    return {"available": bool(models), "error": "" if models else "no listed Codex models",
            "version": version, "models": models, "default": codex_default_model()}


def discover(provider: str) -> dict:
    """What one CLI offers now; cached so catalog reads stay cheap."""
    with _DISCOVERY_LOCK:
        cached = _DISCOVERY.get(provider)
        if cached and time.monotonic() - cached[0] < DISCOVERY_TTL_SECONDS:
            return cached[1]
        try:
            found = _discover(provider)
        except (OSError, subprocess.TimeoutExpired) as exc:
            found = {"available": False, "error": f"{type(exc).__name__}: {exc}", "version": "", "models": []}
        _DISCOVERY[provider] = (time.monotonic(), found)
        return found


def _env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in DROP_ENV}


def _codex_argv(cli_model: str, effort: str, system: str, workdir: Path) -> list[str]:
    argv = [str(CLI[CODEX]), "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
            "--skip-git-repo-check", "--sandbox", "read-only", "--cd", str(workdir),
            "--json", "--color", "never",
            "--output-schema", str(workdir / "schema.json"),
            "--output-last-message", str(workdir / "last-message.json"),
            "-c", f'model_reasoning_effort="{EFFORT[effort]}"',
            # Standard tier only: never fast, priority or ultrafast.
            "-c", 'service_tier="default"', "-c", 'web_search="disabled"',
            # A JSON string literal is a valid TOML basic string.
            "-c", "developer_instructions=" + json.dumps(system)]
    if cli_model:
        argv += ["--model", cli_model]
    for feature in CODEX_DISABLED:
        argv += ["--disable", feature]
    return argv + ["-"]


def _claude_argv(cli_model: str, effort: str, system: str, schema: dict) -> list[str]:
    return [str(CLI[CLAUDE]), "-p", f"--model={cli_model}", f"--effort={EFFORT[effort]}",
            "--output-format=json", "--json-schema=" + json.dumps(schema),
            # No tools, hooks, MCP servers, CLAUDE.md or saved session; the login still works.
            "--tools=", "--safe-mode", "--no-session-persistence",
            f"--max-budget-usd={CLAUDE_SESSION_BUDGET_USD}", "--system-prompt=" + system]


async def _communicate(argv: list[str], stdin: bytes, workdir: Path) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, cwd=workdir, env=_env(), start_new_session=True)
    try:
        stdout, stderr = await process.communicate(stdin)
    except BaseException:
        # Cancellation or the caller's deadline: stop and join the whole CLI process group.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.shield(asyncio.wait_for(process.wait(), 5))
        except (TimeoutError, asyncio.CancelledError):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await asyncio.shield(process.wait())
        raise
    return process.returncode, stdout, stderr


def _tail(data: bytes) -> str:
    return data.decode(errors="replace").strip()[-500:]


def _codex_reply(code: int, stdout: bytes, stderr: bytes, workdir: Path) -> CloudReply:
    usage, errors, tools = {}, [], []
    for line in stdout.decode(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
        elif kind in {"turn.failed", "error"}:
            detail = event.get("error") if isinstance(event.get("error"), dict) else event
            errors.append(str(detail.get("message") or detail)[:500])
        elif kind == "item.completed" and isinstance(event.get("item"), dict):
            if event["item"].get("type") in EFFECT_ITEMS:
                tools.append(str(event["item"].get("type")))
    try:
        content = (workdir / "last-message.json").read_text()
    except OSError:
        content = ""
    if errors or tools or code != 0 or not content.strip():
        raise CloudSessionError("Codex session failed: " + ("; ".join(errors) or
            (f"unexpected items {tools}" if tools else f"exit {code}: {_tail(stderr)}")))
    return CloudReply(content=content.strip(), finish_reason="stop",
                      completion_tokens=usage.get("output_tokens"), prompt_tokens=usage.get("input_tokens"),
                      provider_metrics={"cached_input_tokens": usage.get("cached_input_tokens", 0),
                                        "reasoning_tokens": usage.get("reasoning_output_tokens", 0)})


def _claude_reply(code: int, stdout: bytes, stderr: bytes) -> CloudReply:
    text = stdout.decode(errors="replace")
    try:
        payload = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        raise CloudSessionError(f"Claude Code returned no JSON result (exit {code}): {_tail(stderr)}") from None
    if payload.get("is_error") or payload.get("subtype") not in (None, "success"):
        raise CloudSessionError(f"Claude Code session failed: {payload.get('subtype')} "
                                f"{str(payload.get('result') or '')[:300]}")
    structured = payload.get("structured_output")
    if not isinstance(structured, dict):
        raise CloudSessionError("Claude Code returned no structured output")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    models = payload.get("modelUsage") if isinstance(payload.get("modelUsage"), dict) else {}
    return CloudReply(content=json.dumps(structured), finish_reason="stop",
                      completion_tokens=usage.get("output_tokens"),
                      prompt_tokens=sum(int(usage.get(key) or 0) for key in (
                          "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
                      provider_metrics={"cached_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
                                        "cost_usd": float(payload.get("total_cost_usd") or 0.0),
                                        "resolved_models": sorted(models)})


async def complete(provider: str, cli_model: str, system: str, prompt: str, schema: dict,
                   effort: str) -> CloudReply:
    """One structured session; the caller owns the deadline and cancellation."""
    if effort not in EFFORT:
        raise ValueError(f"reasoning effort must be one of: {', '.join(EFFORT)}")
    if provider == CLAUDE and not cli_model:
        raise ValueError("a Claude session needs a model alias")
    if len(system.encode()) > SYSTEM_ARG_MAX:
        prompt = f"# SYSTEM INSTRUCTIONS\n\n{system}\n\n# END\n\n{prompt}"
        system = "Follow the SYSTEM INSTRUCTIONS block at the top of the message."
    started = time.monotonic()
    # An empty private working directory: no project instructions or files to read.
    with tempfile.TemporaryDirectory(prefix="obsidience-cloud-") as directory:
        workdir = Path(directory)
        if provider == CODEX:
            (workdir / "schema.json").write_text(json.dumps(schema))
            argv = _codex_argv(cli_model, effort, system, workdir)
        else:
            argv = _claude_argv(cli_model, effort, system, schema)
        code, stdout, stderr = await _communicate(argv, prompt.encode(), workdir)
        reply = (_codex_reply(code, stdout, stderr, workdir) if provider == CODEX
                 else _claude_reply(code, stdout, stderr))
    reply.provider_metrics.update(provider=provider, cli_model=cli_model or DEFAULT,
                                  effort=EFFORT[effort], generation_ms=round((time.monotonic() - started) * 1000))
    return reply
