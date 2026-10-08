"""Local Hindsight callbacks and its preemptible use of the resident model."""
from __future__ import annotations

import asyncio
import hmac
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .hindsight import MEMORY, token
from ..models import llm, runtime
from ..models.context import TaskContext, PROMPT_SAFETY_TOKENS

router = APIRouter(prefix="/api/memory")


def authenticate(request):
    if not MEMORY.enabled or not hmac.compare_digest(
            request.headers.get("authorization", ""), "Bearer " + token()):
        raise HTTPException(403, "Private memory provider port")


@router.get("/status")
async def status():
    await MEMORY.check_health()
    return MEMORY.status()


@router.post("/events")
async def events(request: Request):
    authenticate(request)
    try:
        await MEMORY.event(await request.json())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"accepted": True}


@router.post("/model/v1/chat/completions")
async def model(request: Request):
    authenticate(request)
    if MEMORY.delivery_paused:
        # Native jobs survive reboot independently of the delivery outbox.
        # A lost one-off provider override must not resume local inference.
        raise HTTPException(503, "Memory inference is paused by the owner")
    body = await request.body()
    if len(body) > 512_000:
        raise HTTPException(413, "Memory request exceeds the bounded model input")
    incoming = json.loads(body)
    if incoming.get("stream") or incoming.get("tools"):
        raise HTTPException(400, "The memory provider may extract text, not execute Tools")
    spec = runtime.configured_spec(runtime.EXECUTIVE_MODEL)
    if incoming.get("model") != spec.id:
        raise HTTPException(400, "Memory uses the existing Executive model")
    payload = {k: incoming[k] for k in ("messages", "response_format", "temperature", "top_p", "seed", "stop") if k in incoming}
    payload.update(model=spec.id, stream=False,
        max_tokens=min(int(incoming.get("max_completion_tokens", incoming.get("max_tokens", spec.max_output_tokens))), spec.max_output_tokens),
        chat_template_kwargs={"enable_thinking": False})
    owner = runtime.RUNTIME
    ready = asyncio.Event()
    def activity(busy):
        if not busy:
            ready.set()
    unsubscribe = owner.subscribe_activity(activity)
    borrowed = False
    try:
        async with asyncio.timeout(540):
            # Wait only on the existing owner's activity/lock edges. This is a
            # background provider request, never an additional agent scheduler.
            while owner.work_requested or owner.lock.locked():
                ready.clear()
                if owner.work_requested:
                    await ready.wait()
                else:
                    async with owner.lock:
                        pass
                if await request.is_disconnected():
                    raise HTTPException(499, "Memory provider disconnected")
            async with owner.resident_prefill(spec) as admitted:
                if not admitted:
                    raise HTTPException(503, "Resident capacity is reserved", headers={"Retry-After": "1"})
                from ..conversation.runtime import RUNTIME as executive
                executive.invalidate_readiness()
                borrowed = True
                async with llm.provider_client() as client:
                    accounting = TaskContext()
                    await accounting.fit_payload(payload, spec, client,
                        spec.context_tokens - spec.max_output_tokens - PROMPT_SAFETY_TOKENS)
                    response = await client.post(spec.base_url + "/chat/completions", json=payload)
                    response.raise_for_status()
                    result = response.json()
                    for choice in result.get("choices", []):
                        choice.get("message", {}).pop("reasoning_content", None)
                    return JSONResponse(result)
    except asyncio.CancelledError:
        # resident_prefill is cancelled and joined before real work acquires
        # the model. Return promptly; upstream owns retrying this pure inference.
        return JSONResponse({"error": {"message": "Foreground command preempted background memory", "type": "capacity"}},
                            status_code=503, headers={"Retry-After": "1"})
    except TimeoutError as exc:
        raise HTTPException(503, "Waiting for idle model capacity timed out") from exc
    finally:
        unsubscribe()
        if borrowed:
            # Restore this same native conversation's prefix after background
            # extraction; do not leave a generic memory prompt marked warm.
            executive.prepare_idle()
