"""Owner-only routes: Teach Rupsaa and Rupsaa Knowledge.

SECURITY MODEL — read before deploying anywhere beyond local dev:

These endpoints let the project owner write directly to the production
dataset and the RAG knowledge base. They are mounted under `/owner/*`,
separated from the public chat API in api/main.py, specifically so they
can be firewalled off or gated independently.

Auth is intentionally minimal but real: if the `OWNER_API_KEY` environment
variable is set, every request under `/owner/*` must include a matching
`X-Owner-Key` header or it gets a 401. If it is NOT set (the local-dev
default), requests are allowed through and a warning is logged once per
process — this keeps local development friction-free while making it
impossible to silently ship an unprotected owner API: the moment
OWNER_API_KEY is set in the environment (which any real deployment should
do), enforcement turns on automatically with no code change. This is not a
substitute for a real auth system (sessions, roles, rate limiting) in an
eventual multi-user production deployment — it's the minimum viable gate
for a single-owner tool, designed so a stronger mechanism can replace
`require_owner` later without touching the route handlers.

Never mount this router's prefix in a public-facing CORS origin list
without OWNER_API_KEY set.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response

from api.schemas import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentOut,
    KnowledgeDocumentUpdate,
    ReindexResponse,
    TeachExampleRequest,
    TerminologyCreate,
    TerminologyOut,
    DanceCreate,
    DanceOut,
    DanceUpdate,
    TerminologyUpdate,
    TeachExampleResponse,
)
from rupsaa.config import PROJECT_ROOT, get_settings
from rupsaa.dataset.config import default_base_dir
from rupsaa.dataset.store import DatasetStore
from rupsaa.dataset.taxonomy import CATEGORIES
from rupsaa.dataset.teach import LANGUAGE_OPTIONS, TeachSubmission, TeachTurn, submit_teach_example
from rupsaa.rag.document_manager import KNOWLEDGE_CATEGORIES, DocumentManager, DocumentManagerError
from rupsaa.rag.router import classify_message
from rupsaa.rag.terminology import TERM_CATEGORIES, TERM_LANGUAGES, TerminologyError, TerminologyStore
from rupsaa.rag import dance_import, terminology_import
from rupsaa.rag.dance import DanceError, DanceStore

logger = logging.getLogger("rupsaa.api.owner")
_warned_unprotected = False


def require_owner(x_owner_key: str | None = Header(default=None)) -> None:
    global _warned_unprotected
    settings = get_settings()
    if not settings.owner_api_key:
        if settings.is_production:
            # Fail closed: a production server without an owner key exposes NO owner operation.
            raise HTTPException(status_code=503, detail="owner tools are disabled: OWNER_API_KEY is not configured")
        if not _warned_unprotected:
            logger.warning(
                "OWNER_API_KEY is not set — /owner/* routes are UNPROTECTED. "
                "Set OWNER_API_KEY before exposing this server beyond local development."
            )
            _warned_unprotected = True
        return
    if not x_owner_key or not hmac.compare_digest(x_owner_key.encode(), settings.owner_api_key.encode()):
        raise HTTPException(status_code=401, detail="missing or invalid X-Owner-Key header")


router = APIRouter(prefix="/owner", tags=["owner"])


def _get_store() -> DatasetStore:
    return DatasetStore(default_base_dir())


def _get_terminology() -> TerminologyStore:
    # Shares the chat service's store instance (and cache) when available so
    # edits are visible to chat immediately; either way the store reads disk.
    from api.services import get_service

    return get_service().terminology


def _get_dance() -> DanceStore:
    from api.services import get_service

    return get_service().dance


def _get_doc_manager() -> DocumentManager:
    settings = get_settings()
    docs_dir = PROJECT_ROOT / settings.knowledge_docs_dir
    return DocumentManager(docs_dir)


# --- Teach Rupsaa ---

@router.get("/teach/taxonomy")
async def teach_taxonomy() -> dict:
    # Static taxonomy/category lists only — no dataset access, safe to
    # leave unauthenticated even when OWNER_API_KEY is set, so the UI can
    # populate its dropdowns before the owner has entered anything.
    return {
        "categories": [{"slug": slug, "description": desc} for slug, desc in CATEGORIES.items()],
        "languages": list(LANGUAGE_OPTIONS.keys()),
    }


@router.post("/teach/examples", response_model=TeachExampleResponse)
async def create_teach_example(request: TeachExampleRequest, x_owner_key: str | None = Header(default=None)) -> TeachExampleResponse:
    require_owner(x_owner_key)
    store = _get_store()
    submission = TeachSubmission(
        turns=[TeachTurn(user=t.user, rupsaa=t.rupsaa) for t in request.turns],
        language_label=request.language,
        category=request.category,
        subcategory=request.subcategory,
        tone=request.tone,
        notes=request.notes or "",
    )
    result = submit_teach_example(store, submission)
    return TeachExampleResponse(
        success=result.success,
        conversation_id=result.conversation_id,
        errors=result.errors,
        warnings=result.warnings,
    )


# --- Rupsaa Knowledge ---

@router.get("/knowledge/categories")
async def knowledge_categories() -> dict:
    return {"categories": KNOWLEDGE_CATEGORIES}


@router.get("/knowledge/documents")
async def list_knowledge_documents(x_owner_key: str | None = Header(default=None)) -> dict:
    require_owner(x_owner_key)
    dm = _get_doc_manager()
    return {"documents": [KnowledgeDocumentOut(**vars(m)) for m in dm.list_documents()]}


@router.get("/knowledge/documents/{filename}")
async def get_knowledge_document(filename: str, x_owner_key: str | None = Header(default=None)) -> dict:
    require_owner(x_owner_key)
    dm = _get_doc_manager()
    try:
        content = dm.read_content(filename)
    except DocumentManagerError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"filename": filename, "content": content}


@router.post("/knowledge/documents", response_model=KnowledgeDocumentOut)
async def create_knowledge_document(request: KnowledgeDocumentCreate, x_owner_key: str | None = Header(default=None)) -> KnowledgeDocumentOut:
    require_owner(x_owner_key)
    dm = _get_doc_manager()
    try:
        meta = dm.create_document(
            title=request.title, category=request.category, content=request.content,
            source_notes=request.source_notes or "",
        )
    except DocumentManagerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return KnowledgeDocumentOut(**vars(meta))


@router.put("/knowledge/documents/{filename}", response_model=KnowledgeDocumentOut)
async def update_knowledge_document(filename: str, request: KnowledgeDocumentUpdate, x_owner_key: str | None = Header(default=None)) -> KnowledgeDocumentOut:
    require_owner(x_owner_key)
    dm = _get_doc_manager()
    try:
        meta = dm.update_document(
            filename, content=request.content, title=request.title,
            category=request.category, source_notes=request.source_notes,
        )
    except DocumentManagerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return KnowledgeDocumentOut(**vars(meta))


@router.delete("/knowledge/documents/{filename}")
async def delete_knowledge_document(filename: str, confirm: bool = False, x_owner_key: str | None = Header(default=None)) -> dict:
    require_owner(x_owner_key)
    dm = _get_doc_manager()
    try:
        dm.delete_document(filename, confirm=confirm)
    except DocumentManagerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"deleted": filename}


@router.post("/knowledge/reindex", response_model=ReindexResponse)
async def reindex_knowledge(x_owner_key: str | None = Header(default=None)) -> ReindexResponse:
    require_owner(x_owner_key)
    # Reuses the exact same RagPipeline as scripts/ingest_knowledge.py and
    # POST /rag/reindex in api/main.py — no second RAG system.
    from rupsaa.rag.pipeline import RagPipeline

    try:
        pipeline = RagPipeline()
        chunks = pipeline.ingest()
    except Exception:
        logger.exception("Knowledge reindex failed")
        raise HTTPException(status_code=500, detail="Reindexing failed. See server logs.")
    return ReindexResponse(chunks_indexed=chunks)


# --- Rupsaa Knowledge → Terminology (structured entries; no reindex, no retraining) ---

@router.get("/terminology/meta")
async def terminology_meta() -> dict:
    return {"categories": TERM_CATEGORIES, "languages": TERM_LANGUAGES}


@router.get("/terminology")
async def list_terminology(q: str = "", x_owner_key: str | None = Header(default=None)) -> dict:
    require_owner(x_owner_key)
    store = _get_terminology()
    records = store.search(q) if q else store.list()
    return {"terms": [TerminologyOut(**vars(r)) for r in records]}


@router.get("/terminology/lookup")
async def lookup_terminology(message: str, x_owner_key: str | None = Header(default=None)) -> dict:
    """Owner test tool: how would this chat message be routed, and which
    terminology entries would it retrieve? (No model call.)"""
    require_owner(x_owner_key)
    decision = classify_message(message)
    matches = _get_terminology().lookup(message, decision.term_candidate) if decision.use_terminology else []
    return {
        "route": decision.route.value,
        "reason": decision.reason,
        "term_candidate": decision.term_candidate,
        "documents_eligible": decision.use_documents,
        "matches": [
            {"id": m.record.id, "term": m.record.term, "score": m.score, "matched": m.matched, "method": m.method}
            for m in matches
        ],
    }


# --- Terminology bulk import (CSV / XLSX) ---
# Registered before /terminology/{term_id} so "template.csv"/"import" aren't
# captured as term ids. Templates contain only a fixed example row, so they're
# public like /terminology/meta; preview and import require the owner key.

@router.get("/terminology/template.csv")
async def terminology_template_csv() -> Response:
    return Response(
        content=terminology_import.template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="terminology_template.csv"'},
    )


@router.get("/terminology/template.xlsx")
async def terminology_template_xlsx() -> Response:
    return Response(
        content=terminology_import.template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="terminology_template.xlsx"'},
    )


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    # Read at most limit+1 bytes: enough to detect "too large" without
    # buffering an arbitrarily big upload.
    content = await file.read(terminology_import.MAX_FILE_BYTES + 1)
    # Only the base name's extension is used; client paths are never echoed back.
    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    return name, content


def _parse_update_rows(update_rows: str) -> set[int]:
    rows = set()
    for part in (update_rows or "").split(","):
        part = part.strip()
        if part:
            if not part.isdigit():
                raise HTTPException(status_code=400, detail=f"update_rows must be row numbers, got {part!r}")
            rows.add(int(part))
    return rows


@router.post("/terminology/import/preview")
async def preview_terminology_import(file: UploadFile = File(...), x_owner_key: str | None = Header(default=None)) -> dict:
    """Parse + validate an uploaded CSV/XLSX and classify every row. Changes nothing."""
    require_owner(x_owner_key)
    name, content = await _read_upload(file)
    try:
        return terminology_import.preview(name, content, _get_terminology()).to_dict()
    except terminology_import.ImportFileError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/terminology/import")
async def commit_terminology_import(
    file: UploadFile = File(...),
    update_rows: str = Form(default=""),
    x_owner_key: str | None = Header(default=None),
) -> dict:
    """Import the valid rows of the same file the owner previewed. Rows that
    match an existing term are SKIPPED unless listed in `update_rows`
    (comma-separated row numbers the owner switched to UPDATE)."""
    require_owner(x_owner_key)
    name, content = await _read_upload(file)
    try:
        return terminology_import.commit(name, content, _get_terminology(), _parse_update_rows(update_rows)).to_dict()
    except terminology_import.ImportFileError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/terminology/{term_id}", response_model=TerminologyOut)
async def get_terminology(term_id: str, x_owner_key: str | None = Header(default=None)) -> TerminologyOut:
    require_owner(x_owner_key)
    try:
        return TerminologyOut(**vars(_get_terminology().get(term_id)))
    except TerminologyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/terminology", response_model=TerminologyOut)
async def create_terminology(request: TerminologyCreate, x_owner_key: str | None = Header(default=None)) -> TerminologyOut:
    require_owner(x_owner_key)
    try:
        return TerminologyOut(**vars(_get_terminology().create(request.model_dump())))
    except TerminologyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/terminology/{term_id}", response_model=TerminologyOut)
async def update_terminology(term_id: str, request: TerminologyUpdate, x_owner_key: str | None = Header(default=None)) -> TerminologyOut:
    require_owner(x_owner_key)
    try:
        return TerminologyOut(**vars(_get_terminology().update(term_id, request.model_dump(exclude_unset=True))))
    except TerminologyError as e:
        status = 404 if "no such term" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))


@router.delete("/terminology/{term_id}")
async def delete_terminology(term_id: str, confirm: bool = False, x_owner_key: str | None = Header(default=None)) -> dict:
    require_owner(x_owner_key)
    try:
        _get_terminology().delete(term_id, confirm=confirm)
    except TerminologyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"deleted": term_id}


# --- Rupsaa Knowledge → Dance (structured dance styles; RAG, no retraining) ---
# Static routes (lookup, templates, import) are registered before /dance/{dance_id}.

@router.get("/dance")
async def list_dance(q: str = "", x_owner_key: str | None = Header(default=None)) -> dict:
    require_owner(x_owner_key)
    store = _get_dance()
    records = store.search(q) if q else store.list()
    return {"dances": [DanceOut(**vars(r)) for r in records], "count": len(records)}


@router.get("/dance/lookup")
async def lookup_dance(message: str, x_owner_key: str | None = Header(default=None)) -> dict:
    """Owner test tool: how a chat message routes and which dance entries it would retrieve (no model call)."""
    require_owner(x_owner_key)
    decision = classify_message(message)
    matches = _get_dance().lookup(message, decision.term_candidate) if decision.use_terminology else []
    return {"route": decision.route.value, "reason": decision.reason, "term_candidate": decision.term_candidate,
            "matches": [{"id": m.record.id, "name": m.record.name, "score": m.score, "matched": m.matched, "method": m.method}
                        for m in matches]}


@router.get("/dance/template.csv")
async def dance_template_csv() -> Response:
    return Response(content=dance_import.template_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="dance_template.csv"'})


@router.get("/dance/template.xlsx")
async def dance_template_xlsx() -> Response:
    return Response(content=dance_import.template_xlsx(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="dance_template.xlsx"'})


@router.post("/dance/import/preview")
async def preview_dance_import(file: UploadFile = File(...), x_owner_key: str | None = Header(default=None)) -> dict:
    require_owner(x_owner_key)
    name, content = await _read_upload(file)
    try:
        return dance_import.preview(name, content, _get_dance()).to_dict()
    except terminology_import.ImportFileError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/dance/import")
async def commit_dance_import(file: UploadFile = File(...), update_rows: str = Form(default=""),
                              x_owner_key: str | None = Header(default=None)) -> dict:
    require_owner(x_owner_key)
    name, content = await _read_upload(file)
    try:
        return dance_import.commit(name, content, _get_dance(), _parse_update_rows(update_rows)).to_dict()
    except terminology_import.ImportFileError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dance/{dance_id}", response_model=DanceOut)
async def get_dance(dance_id: str, x_owner_key: str | None = Header(default=None)) -> DanceOut:
    require_owner(x_owner_key)
    try:
        return DanceOut(**vars(_get_dance().get(dance_id)))
    except DanceError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/dance", response_model=DanceOut)
async def create_dance(request: DanceCreate, x_owner_key: str | None = Header(default=None)) -> DanceOut:
    require_owner(x_owner_key)
    try:
        return DanceOut(**vars(_get_dance().create(request.model_dump(exclude_none=True))))
    except DanceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/dance/{dance_id}", response_model=DanceOut)
async def update_dance(dance_id: str, request: DanceUpdate, x_owner_key: str | None = Header(default=None)) -> DanceOut:
    require_owner(x_owner_key)
    try:
        return DanceOut(**vars(_get_dance().update(dance_id, request.model_dump(exclude_unset=True))))
    except DanceError as e:
        raise HTTPException(status_code=404 if "no such dance" in str(e) else 400, detail=str(e))


@router.delete("/dance/{dance_id}")
async def delete_dance(dance_id: str, confirm: bool = False, x_owner_key: str | None = Header(default=None)) -> dict:
    require_owner(x_owner_key)
    try:
        _get_dance().delete(dance_id, confirm=confirm)
    except DanceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"deleted": dance_id}
