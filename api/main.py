"""Rupsaa FastAPI backend.

Run with:
    uvicorn api.main:app --host $API_HOST --port $API_PORT

The model is loaded lazily on the first /chat request (see api/services.py)
rather than blocking server startup — this keeps `uvicorn api.main:app`
fast to boot and lets /health respond immediately even before the model has
loaded, which matters for container/orchestrator health checks.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    ModelInfo,
    ReindexResponse,
    ResetRequest,
    ResetResponse,
)
from api.services import RupsaaService, get_service
from rupsaa.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("rupsaa.api")

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Rupsaa API starting. Model will load lazily on first /chat call.")
    logger.info("CORS origins: %s", settings.cors_origin_list())
    yield


app = FastAPI(
    title="Rupsaa AI API",
    description="Bengali/Banglish/English multilingual conversational AI backend.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    # Never leak internal tracebacks/chain-of-thought to clients.
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.get("/health", response_model=HealthResponse)
async def health(service: RupsaaService = Depends(get_service)) -> HealthResponse:
    return HealthResponse(status="ok", model_loaded=service.is_model_loaded())


@app.get("/model/info", response_model=ModelInfo)
async def model_info(service: RupsaaService = Depends(get_service)) -> ModelInfo:
    return ModelInfo(**service.model_info())


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, service: RupsaaService = Depends(get_service)) -> ChatResponse:
    try:
        result = service.chat(
            message=request.message,
            conversation_id=request.conversation_id,
            use_rag=request.use_rag,
            temperature=request.temperature,
            top_p=request.top_p,
            max_new_tokens=request.max_new_tokens,
        )
    except Exception:
        logger.exception("Chat generation failed")
        raise HTTPException(status_code=500, detail="Generation failed. See server logs.")
    return ChatResponse(**result)


@app.post("/rag/reindex", response_model=ReindexResponse)
async def rag_reindex(service: RupsaaService = Depends(get_service)) -> ReindexResponse:
    try:
        chunks_indexed = service.reindex()
    except Exception:
        logger.exception("RAG reindex failed")
        raise HTTPException(status_code=500, detail="Reindexing failed. See server logs.")
    return ReindexResponse(chunks_indexed=chunks_indexed)


@app.post("/conversation/reset", response_model=ResetResponse)
async def conversation_reset(request: ResetRequest, service: RupsaaService = Depends(get_service)) -> ResetResponse:
    service.reset_conversation(request.conversation_id)
    return ResetResponse(conversation_id=request.conversation_id, reset=True)
