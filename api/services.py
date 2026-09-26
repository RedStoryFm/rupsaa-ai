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

from rupsaa.conversation.language_control import directive_for
from rupsaa.conversation.manager import ConversationManager
from rupsaa.guardrails.essential_boundaries import check_text
from rupsaa.model.inference import RupsaaEngine
from rupsaa.personality.language import detect_language
from rupsaa.rag.context_builder import build_turn_knowledge
from rupsaa.rag.pipeline import RagPipeline
from rupsaa.rag.terminology import TerminologyStore

logger = logging.getLogger("rupsaa.api.services")


def _trace_turn(*, conversation_id, message, language, knowledge, history, result) -> None:
    """Opt-in per-turn trace (RUPSAA_TRACE_FILE=<path.jsonl>): exactly what the model
    received. Off by default; contains conversation text, never credentials."""
    import json
    import os
    from datetime import datetime, timezone

    path = os.getenv("RUPSAA_TRACE_FILE")
    if not path:
        return
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "user": message,
        "detected_language": language,
        "route": knowledge.route,
        "route_reason": knowledge.decision.reason,
        "term_candidate": knowledge.decision.term_candidate,
        "terms_used": knowledge.terms_used,
        "rag_sources": [s.get("source_filename") for s in knowledge.sources],
        "rag_context_attached": knowledge.retrieved_context is not None,
        "requested_language": knowledge.language,
        "history_passed": history,
        "system_prompt": getattr(result, "system_prompt", None),
        "generation": getattr(result, "generation_params", None),
        "reply": result.text,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("could not write trace to %s", path)


class RupsaaService:
    def __init__(self):
        self._engine: RupsaaEngine | None = None
        self._rag_pipeline: RagPipeline | None = None
        self.conversation_manager = ConversationManager()
        self._terminology: TerminologyStore | None = None
        # conversation_id -> term ids used on the previous turn (for follow-ups
        # like "এটা বাংলায় বুঝিয়ে বলো").
        self._last_terms: dict[str, list[str]] = {}
        # conversation_id -> explicit reply-language choice ("banglay bolo" etc.)
        self._language: dict[str, dict] = {}

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

    @property
    def terminology(self) -> TerminologyStore:
        if self._terminology is None:
            from rupsaa.config import PROJECT_ROOT, get_settings

            self._terminology = TerminologyStore(PROJECT_ROOT / get_settings().knowledge_terminology_dir)
        return self._terminology

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

        knowledge = build_turn_knowledge(
            message,
            use_rag=use_rag,
            rag_query=lambda q, strict=False: self.rag_pipeline.query(q, strict=strict),
            terminology=self.terminology,
            previous_terms=self._last_terms.get(conversation.conversation_id),
            history_messages=len(conversation.messages),
            history_truncated=conversation.dropped_messages > 0,
            history=conversation.messages,
            language_state=self._language.get(conversation.conversation_id),
        )
        logger.info("route=%s terms=%s docs=%d lang=%s", knowledge.route, knowledge.terms_used,
                    len(knowledge.sources), knowledge.language)
        retrieved_context, sources = knowledge.retrieved_context, knowledge.sources

        history_before = [{"role": m.role, "content": m.content} for m in conversation.messages]
        result = self.engine.chat(
            history=conversation.messages,
            user_message=message,
            retrieved_context=retrieved_context,
            terminology_context=knowledge.terminology_context,
            conversation_note=knowledge.conversation_note,
            language_directive=directive_for(knowledge.language_state if knowledge.language else None),
            generation_overrides={
                "temperature": temperature,
                "top_p": top_p,
                "max_new_tokens": max_new_tokens,
            },
        )

        if not result.blocked:
            self.conversation_manager.append_turn(conversation, message, result.text)
            if knowledge.terms_used:
                self._last_terms[conversation.conversation_id] = knowledge.terms_used
            elif knowledge.route not in ("followup", "memory"):
                self._last_terms.pop(conversation.conversation_id, None)
            if knowledge.language_state:
                self._language[conversation.conversation_id] = knowledge.language_state
            else:
                self._language.pop(conversation.conversation_id, None)

        _trace_turn(
            conversation_id=conversation.conversation_id, message=message, language=language,
            knowledge=knowledge, history=history_before, result=result,
        )
        return {
            "response": result.text,
            "conversation_id": conversation.conversation_id,
            "language": language,
            "rag_used": retrieved_context is not None,
            "sources": sources,
            "blocked": result.blocked,
            "route": knowledge.route,
            "terms_used": knowledge.terms_used,
            "response_language": knowledge.language,
        }

    def reindex(self) -> int:
        self._rag_pipeline = RagPipeline()
        return self._rag_pipeline.ingest()

    def reset_conversation(self, conversation_id: str) -> None:
        self.conversation_manager.reset(conversation_id)
        self._last_terms.pop(conversation_id, None)
        self._language.pop(conversation_id, None)

    def model_info(self) -> dict:
        from rupsaa.config import get_settings

        settings = get_settings()
        configured = settings.resolve_path(settings.adapter_path)
        from rupsaa.personality.system_prompt import resolve_prompt_version

        adapter_info = {
            "configured_adapter_path": str(configured),
            "configured_adapter_exists": (configured / "adapter_config.json").is_file(),
        }
        if self._engine is None:
            from rupsaa.config import load_model_config

            return {
                "base_model_id": load_model_config()["base_model_id"],
                "adapter_path": None,
                "quantized": False,
                "device": "not loaded yet",
                "adapter_loaded": False,
                "prompt_version": resolve_prompt_version(str(configured), settings.prompt_version),
                **adapter_info,
            }
        loaded = self._engine.loaded
        return {
            "base_model_id": loaded.base_model_id,
            "adapter_path": loaded.adapter_path,
            "quantized": loaded.quantized,
            "device": str(next(loaded.model.parameters()).device),
            "adapter_loaded": loaded.adapter_path is not None,
            "prompt_version": self._engine.prompt_version,
            **adapter_info,
        }


@lru_cache
def get_service() -> RupsaaService:
    return RupsaaService()
