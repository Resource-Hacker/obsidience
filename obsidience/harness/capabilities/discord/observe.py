"""Read one room-bound Discord camera through its existing client provider."""
from __future__ import annotations

import asyncio

from ...discord import vision
from ...discord.config import AGENT_REF, SNOWFLAKE, load_config


def unavailable(message: str) -> dict:
    return {"observation": {"status": "unavailable", "action_authorized": False,
            "failure": {"code": "discord_camera_unavailable", "message": message,
                        "retryable": False}}}


async def execute(args: dict, context: dict) -> dict:
    fields = {"cameras": set(), "observe": {"member_id", "query"}}
    if (not isinstance(args, dict) or args.get("action") not in fields
            or set(args) != {"action"} | fields[args["action"]]):
        raise ValueError("Invalid discord.observe arguments")
    if args["action"] == "observe":
        member = args["member_id"]
        query = args["query"]
        if (not isinstance(member, str) or member and not SNOWFLAKE.fullmatch(member)
                or not isinstance(query, str) or not query.strip()
                or not 1 <= len(query) <= 500 or not query.isprintable()):
            raise ValueError("Discord observation requires an exact member id or empty speaker selection and a bounded query")
    principal = context.get("_discord")
    if context.get("_agent_ref") != AGENT_REF or not isinstance(principal, dict):
        return unavailable("Observation requires an admitted Discord Agent member request")
    if (not all(SNOWFLAKE.fullmatch(str(principal.get(key, "")))
                for key in ("guild_id", "channel_id", "member_id"))
            or not isinstance(principal.get("request_id"), str) or not principal["request_id"]):
        return unavailable("An exact admitted Discord request is required")
    try:
        config = load_config()
    except (OSError, ValueError):
        return unavailable("Discord configuration is unavailable")
    if not config["enabled"] or principal["guild_id"] != config["guild_id"]:
        return unavailable("The admitted Discord server is unavailable")
    cancel = context.get("_capability_cancel_event")
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError
    return await vision.observe(args, context)
