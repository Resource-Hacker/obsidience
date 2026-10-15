"""Installed desktop applications and the native PackageKit catalog."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ....host import packagekit as application_packages

router = APIRouter()


@router.get("/api/applications")
def applications():
    """Installed desktop applications projected from the real local system."""
    return application_packages.installed_applications()


@router.get("/api/applications/search")
def search_applications(q: str):
    """Search the native PackageKit catalog without inventing an app database."""
    try:
        return application_packages.search_packages(q)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/applications/install")
async def install_application(payload: dict):
    """Install one exact PackageKit result through the system policy boundary."""
    try:
        return await asyncio.to_thread(application_packages.install_package, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/applications/remove")
async def remove_application(payload: dict):
    """Remove one installed desktop application without dependency autoremove."""
    try:
        return await asyncio.to_thread(application_packages.remove_application, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
