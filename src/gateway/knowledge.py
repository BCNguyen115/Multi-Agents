"""Managing the knowledge base from the chat: list the stored documents, delete one, look at a cited page.

  * ``GET    /api/knowledge/documents``  every stored document (any signed-in user);
  * ``DELETE /api/knowledge/documents``  remove one (needs ``KNOWLEDGE_UPLOAD_ROLES``): its chunks AND the copy kept in the
    dataset folder, otherwise the next ``run_ingestion`` would put it straight back;
  * ``GET    /api/knowledge/page``       one page of a stored PDF as an image with the cited passage highlighted.

Replacing a document is an upload of the same file name (``POST /api/knowledge/upload``), see ``main.py``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from src.config import settings
from src.ingestion.preview import render_page
from src.shared.auth import Principal, authenticate
from src.shared.logger import get_logger
from src.shared.messages import msg

logger: logging.Logger = get_logger(__name__)

MAX_DOCUMENTS: int = 1000
MAX_SNIPPET_CHARS: int = 800
DOC_KEY = re.compile(r"^[A-Za-z0-9_\-]{1,40}/[^/\\\x00]{1,150}$")

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_SQL_KEY = "COALESCE(doc_key, category || '/' || filename)"  # rows written before doc_key existed are matched by category + filename


class KnowledgeDocument(BaseModel):
    doc_key: str
    filename: str
    category: str
    chunks: int
    pages: Optional[int] = None
    chars: int = 0
    updated_at: Optional[datetime] = None
    has_pdf: bool = False  # the original PDF is kept, so a cited page can be shown


class DeleteResult(BaseModel):
    doc_key: str
    deleted_chunks: int
    file_removed: bool


def describe_upload(result: dict[str, Any]) -> str:
    """The chat message for a finished upload (Markdown), in the request's language."""
    name, category = result["filename"], result["category"]
    if result["status"] == "unchanged":
        return msg("upload.unchanged", name=name, category=category)
    verb = msg("upload.verb_updated" if result["status"] == "updated" else "upload.verb_added")
    lines = [msg("upload.done", verb=verb, name=name, category=category, chunks=result["chunks"], sections=result["sections"])]
    if result["merged"]:
        lines.append(msg("upload.merged", n=result["merged"]))
    if result["split"]:
        lines.append(msg("upload.split", n=result["split"]))
    if result["duplicates_removed"]:
        lines.append(msg("upload.dupes", n=result["duplicates_removed"]))
    if result["replaced_chunks"]:
        lines.append(msg("upload.replaced", n=result["replaced_chunks"]))
    if result.get("ocr"):
        lines.append(msg("upload.ocr"))
    if not result["saved_to_dataset"]:
        lines.append(msg("upload.no_copy"))
    lines.append(msg("upload.ask_now"))
    return "\n".join(lines)


def _pg(request: Request) -> Any:
    pg = getattr(request.app.state, "pg_client", None)
    if pg is None:
        raise HTTPException(status_code=503, detail=msg("service.starting"))
    return pg


def _file_path(doc_key: str) -> Path:
    """``<KNOWLEDGE_DIR>/<category>/<filename>`` for a valid key, never outside ``KNOWLEDGE_DIR``."""
    if not DOC_KEY.match(doc_key) or ".." in doc_key.split("/")[1]:
        raise HTTPException(status_code=422, detail=msg("kb.bad_key"))
    root = Path(settings.KNOWLEDGE_DIR).resolve()
    path = (root / doc_key).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=422, detail=msg("kb.bad_key"))
    return path


@router.get("/documents", response_model=list[KnowledgeDocument], summary="Documents stored in the knowledge base")
async def list_documents(
    request: Request, category: Optional[str] = Query(default=None, max_length=40), principal: Principal = Depends(authenticate)
) -> list[dict[str, Any]]:
    rows = await _pg(request).fetch(
        f"""
        SELECT {_SQL_KEY} AS doc_key, max(filename) AS filename, max(category) AS category, count(*) AS chunks,
               max(page) AS pages, COALESCE(sum(length(raw_content)), 0) AS chars, max(created_at) AS updated_at
        FROM rag_chunks
        WHERE ($1::text IS NULL OR category = $1)
        GROUP BY 1 ORDER BY max(created_at) DESC LIMIT $2
        """,
        category, MAX_DOCUMENTS,
    )
    documents = []
    for row in rows:
        item = dict(row)
        try:
            item["has_pdf"] = item["filename"].lower().endswith(".pdf") and _file_path(item["doc_key"]).is_file()
        except HTTPException:
            item["has_pdf"] = False
        documents.append(item)
    return documents


@router.delete("/documents", response_model=DeleteResult, summary="Remove a document (its chunks and its kept copy)")
async def delete_document(
    request: Request, doc_key: str = Query(..., max_length=200), principal: Principal = Depends(authenticate)
) -> DeleteResult:
    if not principal.can_manage_knowledge:
        logger.warning("Knowledge delete refused: user=%s roles=%s", principal.user_id, settings.KNOWLEDGE_UPLOAD_ROLES)
        raise HTTPException(status_code=403, detail=msg("forbidden.knowledge"))
    path = _file_path(doc_key)  # validates the key before it is used in SQL or on disk
    status = await _pg(request).execute(f"DELETE FROM rag_chunks WHERE {_SQL_KEY} = $1", doc_key)
    deleted = int(status.split()[-1])
    if deleted == 0:
        raise HTTPException(status_code=404, detail=msg("kb.not_found"))
    removed = False
    try:
        path.unlink()
        removed = True
    except FileNotFoundError:
        pass
    except OSError as exc:  # read-only mount: the chunks are gone, the copy stays and a later run_ingestion would restore it
        logger.warning("Could not remove the kept copy of %s: %s", doc_key, exc)
    store = getattr(request.app.state, "knowledge_store", None)
    if store is not None:
        store.invalidate_categories()
    logger.info("Knowledge delete by user=%s tenant=%s: %s (%d chunks, file removed=%s)", principal.user_id, principal.tenant_id, doc_key, deleted, removed)
    return DeleteResult(doc_key=doc_key, deleted_chunks=deleted, file_removed=removed)


@router.get("/page", summary="One page of a stored PDF as an image, the cited passage highlighted")
async def page_image(
    doc_key: str = Query(..., max_length=200),
    page: int = Query(..., ge=1, le=5000),
    q: str = Query(default="", max_length=MAX_SNIPPET_CHARS),
    scale: float = Query(default=1.6, ge=0.5, le=3.0),
    principal: Principal = Depends(authenticate),
) -> Response:
    path = _file_path(doc_key)
    if path.suffix.lower() != ".pdf" or not path.is_file():
        raise HTTPException(status_code=404, detail=msg("kb.page_unavailable"))
    try:
        png, total, highlighted = await asyncio.to_thread(render_page, path, page, q or None, scale)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=png, media_type="image/png",
        headers={"Cache-Control": "private, max-age=300", "X-Page-Count": str(total), "X-Highlighted": "1" if highlighted else "0"},
    )
