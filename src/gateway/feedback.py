"""``POST /api/chat/feedback``: a thumbs up or down on an answer, with what the answer cited.

These rows are the raw material of a better evaluation set: a thumbs-up on an answer with sources says "this question is answered
by those chunks", a thumbs-down says "look at this one" (``python -m scripts.export_feedback_eval``). Scoped to the caller's tenant
and user like every other row of theirs; the text fields are cut to a sensible size, nothing here is executed or shown to others.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.config import settings
from src.shared.auth import Principal, authenticate
from src.shared.logger import get_logger
from src.shared.messages import msg
from src.shared.rate_limit import enforce

logger: logging.Logger = get_logger(__name__)

router = APIRouter(prefix="/api/chat", tags=["feedback"])


class CitedSource(BaseModel):
    file: str = Field(default="", max_length=300)
    section: str = Field(default="", max_length=300)
    page: Optional[int] = Field(default=None, ge=1, le=100000)
    snippet: str = Field(default="", max_length=400)


class FeedbackIn(BaseModel):
    rating: Literal[-1, 1] = Field(..., description="1 = helpful, -1 = not helpful")
    query: str = Field(default="", max_length=2000, description="the question the answer replied to")
    message_id: str = Field(default="", max_length=100)
    session_id: str = Field(default="", max_length=200)
    comment: str = Field(default="", max_length=1000)
    cited: list[CitedSource] = Field(default_factory=list, max_length=10)


@router.post("/feedback", status_code=204, summary="Thumbs up or down on an answer")
async def submit_feedback(body: FeedbackIn, request: Request, principal: Principal = Depends(authenticate)) -> None:
    pg: Any = getattr(request.app.state, "pg_client", None)
    if pg is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    await enforce(getattr(request.app.state, "redis_client", None), principal, request, "feedback", settings.RATE_LIMIT_FEEDBACK_PER_MINUTE)
    await pg.execute(
        "INSERT INTO rag_feedback (tenant_id, user_id, session_id, message_id, query, rating, comment, cited) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)",
        principal.tenant_id, principal.user_id, body.session_id, body.message_id, body.query, body.rating, body.comment,
        json.dumps([c.model_dump() for c in body.cited], ensure_ascii=False),
    )
    logger.info("Feedback %+d from user=%s on message=%s (%d source(s))", body.rating, principal.user_id, body.message_id, len(body.cited))
