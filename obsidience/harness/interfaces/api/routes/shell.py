"""Shell command credential for pages served by this Harness."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from obsidience.shell import command_token as shell_command_token

router = APIRouter()


@router.get("/api/shell/command-token")
def shell_command_token_for_pages():
    """Give pages served above the Shell credential that browsers cannot read.

    LocalClientsOnly admits only this origin's pages and non-browser local
    clients, which can read the user-only runtime file anyway."""
    try:
        token = shell_command_token.read_token()
    except OSError as exc:
        raise HTTPException(503, "Shell command token unavailable") from exc
    return Response(json.dumps({"token": token}), media_type="application/json",
                    headers={"Cache-Control": "no-store"})
