"""Request / response schemas of the gateway's HTTP API (kept apart from the routes in main.py)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    """Citation source item schema.

    Attributes:
        file: Source document filename.
        section: Section title.
        category: Document category (e.g. nda, msa, sow).
    """

    file: str
    section: str = ""
    category: str | None = None
    cite: int | None = None      # the [n] the answer uses for this source
    page: int | None = None
    snippet: str | None = None


class ChatRequest(BaseModel):
    """Payload schema for ``POST /api/chat``.

    Attributes:
        query: The user's natural-language question.
        session_id: A unique session identifier for conversation tracking.
    """

    query: str = Field(..., min_length=1, description="User query text")
    session_id: str = Field(
        ..., min_length=1, description="Session correlation ID"
    )
    agent_mode: str | None = Field(
        default=None, description="Optional forced agent mode (e.g. search_agent)"
    )
    target_agent: str | None = Field(
        default=None, description="Optional forced target agent (e.g. rag_agent, data_agent, search_agent, db_agent)"
    )


class ChatResponse(BaseModel):
    """Response schema for ``POST /api/chat``.

    Attributes:
        session_id: Echo of the request session ID.
        response: The agent's textual response.
        sources: List of document citations used to generate the answer.
        pev_trace: LangGraph PEV trace metadata.
    """

    session_id: str
    response: str
    sources: list[SourceItem] = Field(default_factory=list)
    pev_trace: dict[str, Any] | None = None


class AnalyzeResponse(BaseModel):
    """Response schema for ``POST /api/analyze``.

    Attributes:
        session_id: Echo of the request session ID.
        explanation: Natural-language explanation of the analysis.
        generated_code: Executable Python code (legacy/fallback).
        dashboard_spec: Standardized JSON Spec for dynamic dashboard rendering.
        pev_trace: LangGraph PEV trace metadata.
    """

    session_id: str
    explanation: str
    generated_code: str = ""
    dashboard_spec: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    pev_trace: dict[str, Any] | None = None


class FilterRequest(BaseModel):
    """Payload schema for ``POST /api/analyze/filter``: recompute a dashboard for the rows matching ``filters``."""

    session_id: str = Field(..., min_length=1)
    chart_specs: list[dict[str, Any]] = Field(default_factory=list, max_length=12, description="Each chart's ``spec`` from the dashboard")
    filters: dict[str, list[str]] = Field(default_factory=dict, description="{column id: [selected values]}")
    language: str = Field(default="en", pattern="^(en|vi)$")
    focus: str | None = Field(default=None, description="The dashboard's lead measure, so KPI cards keep their layout")


class TitleRequest(BaseModel):
    """Payload schema for ``POST /api/chat/title``."""

    query: str = Field(..., min_length=1, description="User query text")
    session_id: str | None = Field(
        default=None, description="Optional session correlation ID"
    )


class TitleResponse(BaseModel):
    """Response schema for ``POST /api/chat/title``."""

    title: str


class ApprovalDecisionRequest(BaseModel):
    """Payload schema for ``POST /api/chat/approve``."""

    session_id: str = Field(..., description="Session correlation ID")
    action_id: str = Field(..., description="Action ID requiring approval")
    decision: Literal["approve", "reject"] = Field(..., description="Decision: 'approve' or 'reject'")
    feedback: Optional[str] = Field(default=None, description="Optional operator rejection reason")


class ApprovalDecisionResponse(BaseModel):
    """Response schema for ``POST /api/chat/approve``."""

    status: str
    action_id: str
    decision: str
    message: Optional[str] = None
    response: Optional[str] = None
    data: Optional[Any] = None


class LoginRequest(BaseModel):
    """Payload schema for ``POST /api/auth/login``."""

    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)


class LoginResponse(BaseModel):
    """Response schema for ``POST /api/auth/login``: a bearer token and who it belongs to."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: dict[str, Any]


class KnowledgeUploadResponse(BaseModel):
    """Response schema for ``POST /api/knowledge/upload``: what was stored, in numbers and in words."""

    session_id: str
    status: Literal["added", "updated", "unchanged"]
    filename: str
    category: str
    sections: int = 0
    chunks: int = 0                 # chunks now stored for this document
    merged: int = 0                 # sections shorter than 200 characters folded into the next one
    split: int = 0                  # sections over 600 characters that became several chunks (nothing is lost)
    dropped: int = 0
    duplicates_removed: int = 0
    replaced_chunks: int = 0        # chunks of the previous version that were replaced
    saved_to_dataset: bool = False
    message: str
