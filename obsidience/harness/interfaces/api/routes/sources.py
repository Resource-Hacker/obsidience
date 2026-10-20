"""Source files and raw Sources: exact physical evidence, read-only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ....knowledge import source

router = APIRouter()


@router.get("/api/source-files")
def source_files(scope: str | None = None, after: str | None = None, limit: int = 2000):
    """Exact physical wiki, code, System, and raw-source paths in one view."""
    try:
        return source.list_source_files(scope=scope, after=after, limit=limit)
    except source.SourceError as cause:
        raise HTTPException(409, str(cause)) from cause


@router.get("/api/source-files/{key:path}")
def read_source_file(key: str, activity: bool = False):
    try:
        record = source.get_source_file(key)
    except source.SourceError as cause:
        raise HTTPException(404, str(cause)) from cause
    if activity and record.get("storage") == "code":
        from ....execution.activity import emit_operation
        from ....graphs.codebase import project_id
        emit_operation("read", "returned", ["file:" + key], label="Reading source",
                       graph_id="code:" + project_id())
    return record


@router.get("/api/sources/{source_id}")
def read_source(source_id: str):
    try:
        return source.get_source(source_id)
    except source.SourceError as cause:
        raise HTTPException(404, str(cause)) from cause
