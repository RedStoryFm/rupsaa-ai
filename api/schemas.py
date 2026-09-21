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


class ModelInfo(BaseModel):
    base_model_id: str
    adapter_path: str | None
    quantized: bool
    device: str


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
