"""Pydantic request/response schemas for the Rupsaa API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    conversation_id: str | None = None
    use_rag: bool = False
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_new_tokens: int | None = Field(default=None, ge=1, le=2048)


class SourceInfo(BaseModel):
    source_filename: str
    chunk_id: int
    score: float


class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    language: str
    rag_used: bool
    sources: list[SourceInfo] = []
    blocked: bool = False
    # How the message was routed (memory / followup / terminology / knowledge
    # / casual / general) and which terminology entries informed the reply.
    route: str | None = None
    terms_used: list[str] = []


class ModelInfo(BaseModel):
    base_model_id: str
    adapter_path: str | None  # adapter actually attached (None = base model only / not loaded yet)
    quantized: bool
    device: str
    # True only once the model has loaded AND a LoRA adapter is attached.
    adapter_loaded: bool = False
    # Adapter the service will try to attach (RUPSAA_ADAPTER_PATH, resolved),
    # and whether it exists on disk — visible before the lazy model load.
    configured_adapter_path: str | None = None
    configured_adapter_exists: bool = False
    # System-prompt version the engine sends (v0.2 = the exact V0.2 training prompt).
    # Before the lazy load this is the version it *will* use for the configured adapter.
    prompt_version: str | None = None


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool


class ReindexResponse(BaseModel):
    chunks_indexed: int


class ResetRequest(BaseModel):
    conversation_id: str


class ResetResponse(BaseModel):
    conversation_id: str
    reset: bool


# --- Owner tools: Teach Rupsaa ---

class TeachTurnIn(BaseModel):
    user: str = Field(..., min_length=1, max_length=4000)
    rupsaa: str = Field(..., min_length=1, max_length=4000)


class TeachExampleRequest(BaseModel):
    turns: list[TeachTurnIn] = Field(..., min_length=1, max_length=20)
    language: str
    category: str
    subcategory: str | None = None
    tone: str | None = None
    notes: str | None = None
    # source_type is intentionally NOT accepted here — the server always
    # forces "human_authored" for anything submitted through Teach Rupsaa.


class TeachExampleResponse(BaseModel):
    success: bool
    conversation_id: str | None = None
    errors: list[str] = []
    warnings: list[str] = []


# --- Owner tools: Rupsaa Knowledge ---

class KnowledgeDocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    category: str
    content: str = Field(..., min_length=1, max_length=50000)
    source_notes: str | None = None


class KnowledgeDocumentUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    content: str | None = Field(default=None, max_length=50000)
    source_notes: str | None = None


class KnowledgeDocumentOut(BaseModel):
    filename: str
    title: str
    category: str
    source_notes: str = ""
    owner_created: bool
    created_at: str
    updated_at: str


# --- Owner tools: Rupsaa Knowledge → Terminology ---

class TerminologyCreate(BaseModel):
    term: str = Field(..., min_length=1, max_length=120)
    definition: str = Field(..., min_length=1, max_length=2000)
    category: str = "general"
    aliases: list[str] = []
    details: str = Field(default="", max_length=6000)
    answer_guidance: str = Field(default="", max_length=2000)
    languages: list[str] = ["en", "bn", "banglish"]
    example_queries: list[str] = []
    tags: list[str] = []
    enabled: bool = True


class TerminologyUpdate(BaseModel):
    term: str | None = Field(default=None, max_length=120)
    definition: str | None = Field(default=None, max_length=2000)
    category: str | None = None
    aliases: list[str] | None = None
    details: str | None = Field(default=None, max_length=6000)
    answer_guidance: str | None = Field(default=None, max_length=2000)
    languages: list[str] | None = None
    example_queries: list[str] | None = None
    tags: list[str] | None = None
    enabled: bool | None = None


class TerminologyOut(BaseModel):
    id: str
    term: str
    definition: str
    category: str
    aliases: list[str]
    details: str
    answer_guidance: str
    languages: list[str]
    example_queries: list[str]
    tags: list[str]
    enabled: bool
    created_at: str
    updated_at: str
