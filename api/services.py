"""Service layer wiring the FastAPI routes to Rupsaa's core engine.

The heavy model is loaded lazily (on first chat request, or explicitly via
startup) rather than at import time, so importing this module — e.g. for
unit tests — never triggers a multi-GB model download. Tests that don't
want to load the real model should override `get_service` via FastAPI's
`app.dependency_overrides` with a fake/mocked RupsaaService instead of
monkeypatching internals.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from rupsaa.conversation.manager import ConversationManager
from rupsaa.guardrails.essential_boundaries import check_text
from rupsaa.model.inference import RupsaaEngine
from rupsaa.personality.language import detect_language
from rupsaa.rag.pipeline import RagPipeline

logger = logging.getLogger("rupsaa.api.services")


class RupsaaService:
    def __init__(self):
        self._engine: RupsaaEngine | None = None
        self._rag_pipeline: RagPipeline | None = None
        self.conversation_manager = ConversationManager()

    @property
    def engine(self) -> RupsaaEngine:
        if self._engine is None:
            logger.info("Lazily loading Rupsaa engine on first use...")
            self._engine = RupsaaEngine.load(use_adapter=True)
        return self._engine

    @property
    def rag_pipeline(self) -> RagPipeline:
        if self._rag_pipeline is None:
            self._rag_pipeline = RagPipeline()
        return self._rag_pipeline

    def is_model_loaded(self) -> bool:
        return self._engine is not None

    def chat(
        self,
        *,
        message: str,
        conversation_id: str | None,
        use_rag: bool,
        temperature: float | None,
        top_p: float | None,
        max_new_tokens: int | None,
    ) -> dict:
        boundary = check_text(message)
        language = detect_language(message)
        conversation = self.conversation_manager.get_or_create(conversation_id)

        if not boundary.allowed:
            from rupsaa.guardrails.essential_boundaries import REFUSAL_MESSAGE

            return {
                "response": REFUSAL_MESSAGE,
                "conversation_id": conversation.conversation_id,
                "language": language,
                "rag_used": False,
                "sources": [],
                "blocked": True,
            }

        retrieved_context = None
        sources: list[dict] = []
        if use_rag:
            retrieved_context, sources = self.rag_pipeline.query(message)

        result = self.engine.chat(
            history=conversation.messages,
            user_message=message,
            retrieved_context=retrieved_context,
            generation_overrides={
                "temperature": temperature,
                "top_p": top_p,
                "max_new_tokens": max_new_tokens,
            },
        )

        if not result.blocked:
            self.conversation_manager.append_turn(conversation, message, result.text)

        return {
            "response": result.text,
            "conversation_id": conversation.conversation_id,
            "language": language,
            "rag_used": retrieved_context is not None,
            "sources": sources,
            "blocked": result.blocked,
        }

    def reindex(self) -> int:
        self._rag_pipeline = RagPipeline()
        return self._rag_pipeline.ingest()

    def reset_conversation(self, conversation_id: str) -> None:
        self.conversation_manager.reset(conversation_id)

    def model_info(self) -> dict:
        if self._engine is None:
            from rupsaa.config import load_model_config

            return {
                "base_model_id": load_model_config()["base_model_id"],
                "adapter_path": None,
                "quantized": False,
                "device": "not loaded yet",
            }
        loaded = self._engine.loaded
        return {
            "base_model_id": loaded.base_model_id,
            "adapter_path": loaded.adapter_path,
            "quantized": loaded.quantized,
            "device": str(next(loaded.model.parameters()).device),
        }


@lru_cache
def get_service() -> RupsaaService:
    return RupsaaService()
