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

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
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
from api.owner_routes import require_owner
from api.owner_routes import router as owner_router
from api.security import BodySizeLimitMiddleware, RateLimiter, client_key, rate_limited_response
from api.services import RupsaaService, get_service
from rupsaa.config import get_settings

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("rupsaa.api")
chat_limiter = RateLimiter(*settings.effective_rate_limits())


@asynccontextmanager
async def lifespan(app_: FastAPI):
    env = "production" if settings.is_production else "development"
    logger.info("Rupsaa API starting (env=%s, adapter=%s, prompt_version=%s)", env,
                settings.resolve_path(settings.adapter_path).name, settings.prompt_version or "auto")
    if settings.is_production:
        problems = settings.production_problems()
        if problems:
            for p in problems:
                logger.error("PRODUCTION CONFIG: %s", p)
            raise RuntimeError("refusing to start in production: " + "; ".join(problems))
    logger.info("CORS origins: %s · chat rate limit per client/global: %s/min", settings.cors_origin_list(),
                "/".join(map(str, settings.effective_rate_limits())))
    if settings.effective_preload():
        logger.info("Preloading the model in the background; GET /ready turns 200 when it can answer.")
        app_.dependency_overrides.get(get_service, get_service)().start_preload()
    else:
        logger.info("Model will load lazily on the first /chat call.")
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
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Owner-Key"],
)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)

# Owner-only tools (Teach Rupsaa, Rupsaa Knowledge) — see api/owner_routes.py
# for the auth model. Mounted under /owner/*, separate from the public chat
# routes below.
app.include_router(owner_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    # Never leak internal tracebacks/chain-of-thought to clients.
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.get("/health", response_model=HealthResponse)
async def health(service: RupsaaService = Depends(get_service)) -> HealthResponse:
    """Liveness + component status. Always 200 while the process is up (use /ready for traffic)."""
    r = service.readiness()
    return HealthResponse(status="ok", model_loaded=service.is_model_loaded(), ready=r["ready"],
                          model_loading=r["model_loading"], environment="production" if settings.is_production else "development",
                          **service.knowledge_status())


@app.get("/ready")
async def ready(service: RupsaaService = Depends(get_service)):
    """200 only when the model is loaded and chat can answer; 503 otherwise (for proxies/deploy checks)."""
    r = service.readiness()
    body = {"ready": r["ready"], "model_loading": r["model_loading"], "model_error": bool(r["model_error"])}
    if not settings.is_production:
        body["model_error_detail"] = r["model_error"]
    return JSONResponse(status_code=200 if r["ready"] else 503, content=body)


@app.get("/model/info", response_model=ModelInfo)
async def model_info(service: RupsaaService = Depends(get_service)) -> ModelInfo:
    return ModelInfo(**service.model_info())


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request, service: RupsaaService = Depends(get_service)) -> ChatResponse:
    if chat_limiter.enabled:
        retry = chat_limiter.check(client_key(http_request))
        if retry is not None:
            logger.warning("rate limited client on /chat")
            return rate_limited_response(retry)
    if settings.is_production and not service.is_model_loaded():
        r = service.readiness()
        if r["model_loading"] or r["model_error"]:
            raise HTTPException(status_code=503, detail="Rupsaa is starting up — please try again in a minute.")
    try:
        # Generation blocks for seconds: run it off the event loop so /health, /ready and other
        # requests stay responsive (the service serialises GPU generation itself).
        result = await run_in_threadpool(
            service.chat,
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
async def rag_reindex(service: RupsaaService = Depends(get_service),
                      x_owner_key: str | None = Header(default=None)) -> ReindexResponse:
    require_owner(x_owner_key)  # expensive + mutates the index: owner only (same as /owner/knowledge/reindex)
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
