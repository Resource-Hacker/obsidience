"""Owner-registered Executive optimization cases."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/api/harness/optimizations")
def prepare_executive_optimization(payload: dict):
    """Local owner registration; model Tools cannot author evaluation criteria."""
    from ....execution.optimization import prepare
    try:
        return prepare(payload)
    except (ValueError, KeyError, OSError) as cause:
        raise HTTPException(400, str(cause)) from cause


@router.post("/api/harness/optimizations/{case_id}/run")
def queue_executive_optimization(case_id: str):
    from ....execution.optimization import queue
    try:
        return queue(case_id)
    except (ValueError, KeyError, OSError) as cause:
        raise HTTPException(409, str(cause)) from cause


@router.get("/api/harness/optimizations/{case_id}")
def executive_optimization_status(case_id: str):
    from ....execution.optimization import status
    try:
        return status(case_id)
    except (ValueError, KeyError, OSError) as cause:
        raise HTTPException(404, str(cause)) from cause
