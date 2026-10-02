"""Conversations kept on the server (``/api/conversations``), so a signed-in user's chats follow them across browsers and devices.

Each conversation belongs to ``(tenant, user)`` of the caller (``authenticate``): nobody can list, read, overwrite or delete
another user's. The browser keeps working from its own copy (localStorage) and syncs with these routes; ``PUT`` is
optimistic: the client says which version it started from (``base_updated_at``, the ``updated_at`` string it was given, sent
back as is) and gets 409 with the server's version when someone else (another tab, another device) saved in between, so a
newer chat is never silently overwritten.

Limits keep one user from filling the database: ``MAX_CONVERSATIONS_PER_USER`` chats, ``MAX_MESSAGES`` messages and
``MAX_BYTES`` of JSON per chat.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.shared.auth import Principal, authenticate
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)

MAX_CONVERSATIONS_PER_USER: int = 200
MAX_MESSAGES: int = 500
MAX_BYTES: int = 4 * 1024 * 1024
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationSummary(BaseModel):
    id: str
    title: str
    pinned: bool
    updated_at: datetime


class Conversation(ConversationSummary):
    messages: list[dict[str, Any]]


class ConversationIn(BaseModel):
    title: str = Field(default="", max_length=200)
    pinned: bool = False
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=MAX_MESSAGES)
    base_updated_at: Optional[datetime] = Field(
        default=None, description="updated_at of the version this edit started from, as received; omit for a conversation the server has not seen"
    )


def _pg(request: Request) -> Any:
    pg = getattr(request.app.state, "pg_client", None)
    if pg is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    return pg


def _check_id(conversation_id: str) -> None:
    if not ID_PATTERN.match(conversation_id):
        raise HTTPException(status_code=422, detail=msg("conv.bad_id"))


def _summary(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "title": row["title"], "pinned": row["pinned"], "updated_at": row["updated_at"]}


def _full(row: Any) -> dict[str, Any]:
    messages = row["messages"]
    return {**_summary(row), "messages": json.loads(messages) if isinstance(messages, str) else messages}


def _newer_than(saved: datetime, base: Optional[datetime]) -> bool:
    """Was ``saved`` written after the version the client started from? Compared to the millisecond: JavaScript dates cannot hold more."""
    if base is None:
        return True
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return saved.replace(microsecond=saved.microsecond // 1000 * 1000) > base.replace(microsecond=base.microsecond // 1000 * 1000)


@router.get("", response_model=list[ConversationSummary], summary="The caller's conversations, newest first (without messages)")
async def list_conversations(request: Request, principal: Principal = Depends(authenticate)) -> list[dict[str, Any]]:
    rows = await _pg(request).fetch(
        "SELECT id, title, pinned, updated_at FROM conversations WHERE tenant_id = $1 AND user_id = $2 ORDER BY updated_at DESC LIMIT $3",
        principal.tenant_id, principal.user_id, MAX_CONVERSATIONS_PER_USER,
    )
    return [_summary(r) for r in rows]


@router.get("/{conversation_id}", response_model=Conversation, summary="One conversation with its messages")
async def get_conversation(conversation_id: str, request: Request, principal: Principal = Depends(authenticate)) -> dict[str, Any]:
    _check_id(conversation_id)
    rows = await _pg(request).fetch(
        "SELECT id, title, pinned, messages, updated_at FROM conversations WHERE tenant_id = $1 AND user_id = $2 AND id = $3",
        principal.tenant_id, principal.user_id, conversation_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail=msg("conv.not_found"))
    return _full(rows[0])


@router.put("/{conversation_id}", response_model=ConversationSummary, summary="Create or update one conversation (optimistic concurrency)")
async def save_conversation(
    conversation_id: str, body: ConversationIn, request: Request, principal: Principal = Depends(authenticate)
) -> Any:
    _check_id(conversation_id)
    payload = json.dumps(body.messages, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=msg("conv.too_big", mb=MAX_BYTES // (1024 * 1024)))
    async with _pg(request).transaction() as conn:
        # serialise this user's saves, so two saves of the same chat (or the count check) cannot interleave
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"conversations:{principal.tenant_id}:{principal.user_id}")
        current = await conn.fetchrow(
            "SELECT id, title, pinned, messages, updated_at FROM conversations WHERE tenant_id = $1 AND user_id = $2 AND id = $3",
            principal.tenant_id, principal.user_id, conversation_id,
        )
        if current is not None and _newer_than(current["updated_at"], body.base_updated_at):
            # someone saved a newer version (or the client never saw this one): hand it back instead of overwriting
            return JSONResponse(status_code=409, content=json.loads(Conversation(**_full(current)).model_dump_json()))
        if current is None:
            count = await conn.fetchval("SELECT count(*) FROM conversations WHERE tenant_id = $1 AND user_id = $2", principal.tenant_id, principal.user_id)
            if count >= MAX_CONVERSATIONS_PER_USER:
                raise HTTPException(status_code=409, detail=msg("conv.too_many", limit=MAX_CONVERSATIONS_PER_USER))
        row = await conn.fetchrow(
            """
            INSERT INTO conversations (tenant_id, user_id, id, title, pinned, messages)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            ON CONFLICT (tenant_id, user_id, id) DO UPDATE
               SET title = EXCLUDED.title, pinned = EXCLUDED.pinned, messages = EXCLUDED.messages, updated_at = clock_timestamp()
            RETURNING id, title, pinned, updated_at
            """,
            principal.tenant_id, principal.user_id, conversation_id, body.title, body.pinned, payload,
        )
    return _summary(row)


@router.delete("/{conversation_id}", status_code=204, summary="Delete one conversation")
async def delete_conversation(conversation_id: str, request: Request, principal: Principal = Depends(authenticate)) -> None:
    _check_id(conversation_id)
    await _pg(request).execute(
        "DELETE FROM conversations WHERE tenant_id = $1 AND user_id = $2 AND id = $3", principal.tenant_id, principal.user_id, conversation_id
    )
