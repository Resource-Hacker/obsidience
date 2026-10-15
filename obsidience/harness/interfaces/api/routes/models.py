"""Inference targets: catalog, owner settings and benchmarks."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException

from ....models import runtime as model_runtime

router = APIRouter()


@router.get("/api/models")
def models():
    """Installed and live inference targets for the Models and Task editors."""
    return {"models": model_runtime.catalog()}


@router.patch("/api/models/{model_id}")
async def update_model(model_id: str, payload: dict):
    try:
        return await model_runtime.update_model(model_id, payload)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/models/{model_id}/benchmark")
async def benchmark_model(model_id: str, payload: dict):
    try:
        return await model_runtime.benchmark(model_id, payload.get("devices"))
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(400, str(exc)) from exc
