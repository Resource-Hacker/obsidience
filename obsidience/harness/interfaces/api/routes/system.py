"""System inventory publication: read the last one or refresh it."""

from __future__ import annotations

from fastapi import APIRouter

from ....knowledge import system as system_knowledge

router = APIRouter()


@router.get("/api/system/knowledge")
def system_knowledge_status():
    """Read the last System publication without collecting or changing files."""
    return system_knowledge.system_knowledge_status()


@router.post("/api/system/refresh")
def refresh_system_knowledge():
    """Owner refresh of immutable System evidence and its workstation Articles."""
    return system_knowledge.refresh_system_knowledge()
