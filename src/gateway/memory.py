"""``/api/memory``: what the assistant remembers about the signed-in person, and the way to make it forget.

Long-term memory is keyed ``<tenant>:<user>`` (``auth.memory_user_id``), so each person sees and deletes only their own items; the id alone is
never enough to delete (``MemoryManager.delete_memory`` checks the item is theirs). A guest (no account) has no stable identity to list, so
the list is empty for them. mem0 is synchronous and slow: every call runs in a worker thread under a timeout.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from src.config import settings
from src.shared.auth import Principal, authenticate
from src.shared.logger import get_logger
from src.shared.messages import msg
from src.shared.rate_limit import enforce

logger: logging.Logger = get_logger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])

_TIMEOUT_SECONDS = 15.0


def _manager(request: Request) -> Any:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    manager = getattr(orchestrator, "memory_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    return manager


def _owner(principal: Principal) -> str:
    return f"{principal.tenant_id}:{principal.user_id}"


async def _run(fn: Any, *args: Any) -> Any:
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), _TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail=msg("memory.timeout")) from exc


@router.get("", summary="What is remembered about me")
async def list_my_memories(request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    if not principal.authenticated:
        return {"items": [], "signed_in": False}
    await enforce(getattr(request.app.state, "redis_client", None), principal, request, "memory", settings.RATE_LIMIT_FEEDBACK_PER_MINUTE)
    return {"items": await _run(_manager(request).list_memories, _owner(principal)), "signed_in": True}


@router.delete("/{memory_id}", status_code=204, summary="Forget one item")
async def forget_one(memory_id: str, request: Request, principal: Principal = Depends(authenticate)) -> None:
    if not principal.authenticated or not memory_id.strip():
        raise HTTPException(status_code=404, detail=msg("memory.not_found"))
    await enforce(getattr(request.app.state, "redis_client", None), principal, request, "memory", settings.RATE_LIMIT_FEEDBACK_PER_MINUTE)
    if not await _run(_manager(request).delete_memory, _owner(principal), memory_id):
        raise HTTPException(status_code=404, detail=msg("memory.not_found"))


@router.delete("", summary="Forget everything about me")
async def forget_all(request: Request, principal: Principal = Depends(authenticate)) -> dict[str, int]:
    if not principal.authenticated:
        return {"deleted": 0}
    await enforce(getattr(request.app.state, "redis_client", None), principal, request, "memory", settings.RATE_LIMIT_FEEDBACK_PER_MINUTE)
    return {"deleted": int(await _run(_manager(request).delete_all, _owner(principal)))}
