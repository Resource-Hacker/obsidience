"""Native Connections pane controller over the single Harness collector."""

from __future__ import annotations

import asyncio
import threading
from copy import deepcopy

import httpx
from fastapi import APIRouter, HTTPException, Request

from ...config import CONFIG
from ...connections.check import check_connection
from ...connections.catalog import PROVIDERS
from ...connections.credentials import CredentialError, CredentialStore
from ...connections.runtime import ConnectionsError, ConnectionsManager, RevisionConflict


router = APIRouter()


def create_manager() -> tuple[ConnectionsManager, CredentialStore]:
    credentials = CredentialStore()

    def headers(connection_id, mode):
        connection = manager.connection(connection_id)
        return credentials.headers(connection_id, connection["url"], mode)

    def ready(connection_id):
        connection = manager.connection(connection_id)
        return credentials.configured(connection_id, connection["url"])

    manager = ConnectionsManager(auth_headers=headers, credential_ready=ready)
    return manager, credentials


def _owners(request: Request):
    if request.method != "GET":
        # The native shell sends no Origin. Browser writes may come only from
        # our own loopback UI, never a third-party page or an opaque web origin.
        allowed = {f"http://127.0.0.1:{CONFIG.port}", f"http://localhost:{CONFIG.port}"}
        if request.headers.get("origin") not in {None, *allowed}:
            raise HTTPException(403, "Connections can be changed only from the local Obsidience interface")
    return request.app.state.connections, request.app.state.connection_credentials


def _snapshot(manager: ConnectionsManager, result: dict | None = None) -> dict:
    snapshot = result if result is not None else manager.snapshot()
    # Keep credential readiness as a boolean, never materialize a token to list
    # connections. None means no credential is needed, not that one is stored.
    for connection in snapshot["connections"]:
        connection["credential_set"] = connection["auth_mode"] != "none" and bool(connection.get("credential_ready"))
    return {**snapshot, "providers": deepcopy(PROVIDERS)}


def _revision(payload: dict) -> int:
    value = payload.get("revision")
    if type(value) is not int or value < 0:
        raise HTTPException(400, "A current configuration revision is required")
    return value


def _error(exc: ValueError):
    raise HTTPException(409 if isinstance(exc, RevisionConflict) else 400, str(exc)) from exc


@router.get("/api/connections")
def connections_snapshot(request: Request):
    manager, _ = _owners(request)
    return _snapshot(manager)


@router.post("/api/connections")
def add_connection(request: Request, payload: dict):
    manager, _ = _owners(request)
    revision = _revision(payload)
    if "id" in payload:
        raise HTTPException(400, "New connection identities are assigned by the Harness")
    try:
        with manager.revision_guard(revision):
            before = {item["id"] for item in manager.snapshot()["connections"]}
            result = manager.save_connection({k: v for k, v in payload.items() if k != "revision"}, expected_revision=revision)
            snapshot = _snapshot(manager, result)
            snapshot["created_id"] = next(item["id"] for item in snapshot["connections"] if item["id"] not in before)
            return snapshot
    except (ConnectionsError, CredentialError) as exc:
        _error(exc)


@router.patch("/api/connections/{connection_id}")
def update_connection(request: Request, connection_id: str, payload: dict):
    manager, _ = _owners(request)
    revision = _revision(payload)
    try:
        with manager.revision_guard(revision):
            prior = manager.connection(connection_id)
            fields = {k: v for k, v in payload.items() if k != "revision"}
            fields["id"] = connection_id
            return _snapshot(manager, manager.save_connection({**prior, **fields}, expected_revision=revision))
    except (ConnectionsError, CredentialError) as exc:
        _error(exc)


@router.delete("/api/connections/{connection_id}")
def delete_connection(request: Request, connection_id: str, revision: int):
    manager, credentials = _owners(request)
    try:
        with manager.revision_guard(revision):
            result = manager.delete_connection(connection_id, expected_revision=revision)
            credentials.delete_connection(connection_id)
            return _snapshot(manager, result)
    except (ConnectionsError, CredentialError) as exc:
        _error(exc)


@router.post("/api/feeds")
def add_feed(request: Request, payload: dict):
    manager, _ = _owners(request)
    revision = _revision(payload)
    if "id" in payload:
        raise HTTPException(400, "New feed identities are assigned by the Harness")
    try:
        with manager.revision_guard(revision):
            before = {item["id"] for item in manager.snapshot()["feeds"]}
            result = manager.save_feed({k: v for k, v in payload.items() if k != "revision"}, expected_revision=revision)
            snapshot = _snapshot(manager, result)
            snapshot["created_id"] = next(item["id"] for item in snapshot["feeds"] if item["id"] not in before)
            return snapshot
    except ConnectionsError as exc:
        _error(exc)


@router.get("/api/feeds/items")
def feed_items(request: Request, feed_id: str | None = None, limit: int = 100):
    manager, _ = _owners(request)
    try:
        return manager.items(feed_id=feed_id or None, limit=limit)
    except ConnectionsError as exc:
        _error(exc)


@router.get("/api/feeds/items/{source_id}")
def feed_item(request: Request, source_id: str):
    manager, _ = _owners(request)
    try:
        return manager.item(source_id)
    except ConnectionsError as exc:
        _error(exc)


@router.post("/api/feeds/preview")
async def preview_feed(request: Request, payload: dict):
    manager, _ = _owners(request)
    revision = _revision(payload)
    cancelled = threading.Event()
    try:
        return await asyncio.to_thread(manager.preview_feed,
            {key: value for key, value in payload.items() if key != "revision"},
            expected_revision=revision, cancel_event=cancelled)
    except asyncio.CancelledError:
        cancelled.set()
        raise
    except ConnectionsError as exc:
        _error(exc)


@router.patch("/api/feeds/{feed_id}")
def update_feed(request: Request, feed_id: str, payload: dict):
    manager, _ = _owners(request)
    revision = _revision(payload)
    try:
        with manager.revision_guard(revision):
            fields = {k: v for k, v in payload.items() if k != "revision"}
            fields["id"] = feed_id
            return _snapshot(manager, manager.save_feed(fields, expected_revision=revision))
    except ConnectionsError as exc:
        _error(exc)


@router.delete("/api/feeds/{feed_id}")
def delete_feed(request: Request, feed_id: str, revision: int):
    manager, _ = _owners(request)
    try:
        return _snapshot(manager, manager.delete_feed(feed_id, expected_revision=revision))
    except ConnectionsError as exc:
        _error(exc)


@router.post("/api/feeds/{feed_id}/check")
async def check_feed(request: Request, feed_id: str):
    manager, _ = _owners(request)
    try:
        return _snapshot(manager, await manager.check_feed(feed_id))
    except ConnectionsError as exc:
        _error(exc)


@router.post("/api/connections/{connection_id}/check")
async def test_connection(request: Request, connection_id: str):
    manager, credentials = _owners(request)
    def prepare():
        revision = manager.snapshot()["revision"]
        return revision, manager.connection(connection_id, expected_revision=revision)
    try:
        revision, connection = await asyncio.to_thread(prepare)
    except ConnectionsError as exc:
        _error(exc)
    cancelled = threading.Event()
    def perform_check():
        try:
            headers = credentials.headers(connection_id, connection["url"], connection["auth_mode"])
            check_connection(connection, headers, cancelled)
            return "ready", ""
        except (CredentialError, ValueError) as exc:
            return "error", str(exc)
        except httpx.HTTPError:
            return "error", "The endpoint could not be reached within its connection deadline"
    try:
        status, error = await asyncio.to_thread(perform_check)
    except asyncio.CancelledError:
        cancelled.set()
        raise
    result = await asyncio.to_thread(manager.record_connection_check, connection_id, revision, status, error)
    return _snapshot(manager, result)


@router.put("/api/connections/{connection_id}/credential")
def save_credential(request: Request, connection_id: str, payload: dict):
    manager, credentials = _owners(request)
    revision = _revision(payload)
    try:
        with manager.revision_guard(revision):
            connection = manager.connection(connection_id)
            if connection["auth_mode"] == "none":
                raise CredentialError("Choose Bearer or Bot authentication before adding a credential")
            # Invalidate in-flight checks and pre-credential conditional state.
            # Persist invalidation first: a crash can cost a refetch, never pair
            # another account's token with the previous account's validators.
            manager.credentials_changed(connection_id, expected_revision=revision)
            credentials.save(connection_id, connection["url"], payload.get("secret"))
            return _snapshot(manager)
    except (ConnectionsError, CredentialError) as exc:
        _error(exc)


@router.delete("/api/connections/{connection_id}/credential")
def delete_credential(request: Request, connection_id: str, revision: int):
    manager, credentials = _owners(request)
    try:
        with manager.revision_guard(revision):
            connection = manager.connection(connection_id)
            manager.credentials_changed(connection_id, expected_revision=revision)
            credentials.delete(connection_id, connection["url"])
            return _snapshot(manager)
    except (ConnectionsError, CredentialError) as exc:
        _error(exc)
