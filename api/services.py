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
import threading
import time
from functools import lru_cache
from pathlib import Path

from rupsaa.conversation.language_control import directive_for
from rupsaa.conversation.manager import ConversationManager
from rupsaa.guardrails.essential_boundaries import check_text
from rupsaa.model.inference import RupsaaEngine
from rupsaa.personality.language import detect_language
from rupsaa.rag.context_builder import build_turn_knowledge
from rupsaa.rag.dance import DanceStore
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
        self._dance: DanceStore | None = None
        # conversation_id -> term ids used on the previous turn (for follow-ups
        # like "এটা বাংলায় বুঝিয়ে বলো").
        self._last_terms: dict[str, list[str]] = {}
        # conversation_id -> explicit reply-language choice ("banglay bolo" etc.)
        self._language: dict[str, dict] = {}
        # One model load at a time: two simultaneous first messages must not load the 7B model twice.
        self._load_lock = threading.Lock()
        self._generate_lock = threading.Lock()
        self._preload_thread: threading.Thread | None = None
        self.load_error: str | None = None

    @property
    def engine(self) -> RupsaaEngine:
        if self._engine is None:
            with self._load_lock:
                if self._engine is None:
                    self._engine = self._load_engine()
        return self._engine

    def _load_engine(self) -> RupsaaEngine:
        from rupsaa.config import get_settings

        settings = get_settings()
        adapter = settings.resolve_path(settings.adapter_path)
        if settings.is_production and not (adapter / "adapter_model.safetensors").is_file():
            # Production never silently falls back to the base model or another adapter.
            raise RuntimeError(f"configured adapter '{adapter.name}' not found — refusing to serve")
        started = time.monotonic()
        logger.info("Loading model: base=%s adapter=%s", settings.model_id or "configs/model.yaml", adapter.name)
        engine = RupsaaEngine.load(use_adapter=True)
        if settings.is_production and engine.loaded.adapter_path is None:
            raise RuntimeError(f"adapter '{adapter.name}' did not attach — refusing to serve the base model")
        logger.info("Model ready in %.0fs: adapter=%s prompt_version=%s", time.monotonic() - started,
                    Path(engine.loaded.adapter_path).name if engine.loaded.adapter_path else None, engine.prompt_version)
        return engine

    def start_preload(self) -> None:
        """Load the model in the background (production) so /ready turns green before real traffic."""
        if self._engine is not None or (self._preload_thread and self._preload_thread.is_alive()):
            return

        def _run() -> None:
            try:
                _ = self.engine
            except Exception as exc:  # surfaced via /ready and the logs
                self.load_error = type(exc).__name__ + ": " + str(exc)[:200]
                logger.exception("Model preload failed")

        self._preload_thread = threading.Thread(target=_run, name="rupsaa-model-preload", daemon=True)
        self._preload_thread.start()

    def readiness(self) -> dict:
        loading = bool(self._preload_thread and self._preload_thread.is_alive())
        return {"ready": self._engine is not None, "model_loading": loading, "model_error": self.load_error}

    def knowledge_status(self) -> dict:
        from rupsaa.config import get_settings

        settings = get_settings()
        index_dir = settings.resolve_path(settings.vector_store_dir)
        try:
            terms = len(self.terminology.list(include_disabled=False))
            dances = len(self.dance.list(include_disabled=False))
            ok = True
        except Exception:
            logger.exception("knowledge store unreadable")
            terms = dances = 0
            ok = False
        return {"knowledge_ok": ok, "terminology_entries": terms, "dance_entries": dances,
                "rag_index_present": index_dir.is_dir() and any(p.name != ".gitkeep" for p in index_dir.iterdir())}

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

    @property
    def dance(self) -> DanceStore:
        if self._dance is None:
            from rupsaa.config import PROJECT_ROOT, get_settings

            self._dance = DanceStore(PROJECT_ROOT / get_settings().knowledge_dance_dir)
        return self._dance

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
        started = time.monotonic()
        from rupsaa.config import get_settings

        cap = get_settings().max_new_tokens_cap
        if max_new_tokens is not None:
            max_new_tokens = min(max_new_tokens, cap)
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
            dance=self.dance,
        )
        logger.info("route=%s terms=%s docs=%d lang=%s", knowledge.route, knowledge.terms_used,
                    len(knowledge.sources), knowledge.language)
        retrieved_context, sources = knowledge.retrieved_context, knowledge.sources

        history_before = [{"role": m.role, "content": m.content} for m in conversation.messages]
        engine = self.engine
        with self._generate_lock:  # one generation at a time on the single GPU; others wait their turn
            result = engine.chat(
                history=conversation.messages,
                user_message=message,
                retrieved_context=retrieved_context,
                terminology_context=knowledge.terminology_context,
                conversation_note=knowledge.conversation_note,
                language_directive=directive_for(knowledge.language_state if knowledge.language else None),
                dance_context=knowledge.dance_context,
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
            self._prune_side_state()

        _trace_turn(
            conversation_id=conversation.conversation_id, message=message, language=language,
            knowledge=knowledge, history=history_before, result=result,
        )
        # Operational log line: no message text (verbose tracing is opt-in via RUPSAA_TRACE_FILE).
        logger.info("chat done route=%s lang=%s reply_lang=%s terms=%d docs=%d chars_in=%d tokens_out=%s latency_ms=%d",
                    knowledge.route, language, knowledge.language, len(knowledge.terms_used), len(sources), len(message),
                    getattr(result, "completion_tokens", None), (time.monotonic() - started) * 1000)
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

    def _prune_side_state(self) -> None:
        """Per-conversation follow-up/language state lives only as long as its conversation."""
        limit = getattr(self.conversation_manager.store, "max_conversations", 5000)
        if len(self._last_terms) + len(self._language) > 2 * limit:
            for side in (self._last_terms, self._language):
                for cid in [c for c in side if self.conversation_manager.store.get(c) is None]:
                    side.pop(cid, None)

    def reindex(self) -> int:
        self._rag_pipeline = RagPipeline()
        return self._rag_pipeline.ingest()

    def reset_conversation(self, conversation_id: str) -> None:
        self.conversation_manager.reset(conversation_id)
        self._last_terms.pop(conversation_id, None)
        self._language.pop(conversation_id, None)

    def model_info(self) -> dict:
        info = self._model_info()
        from rupsaa.config import get_settings

        if get_settings().is_production:
            # Never publish server filesystem layout: adapter NAMES only.
            for key in ("adapter_path", "configured_adapter_path"):
                if info.get(key):
                    info[key] = Path(info[key]).name
            if info.get("base_model_id") and Path(info["base_model_id"]).is_absolute():
                info["base_model_id"] = Path(info["base_model_id"]).name
        info["environment"] = "production" if get_settings().is_production else "development"
        info["adapter_name"] = Path(info["adapter_path"]).name if info.get("adapter_path") else None
        return info

    def _model_info(self) -> dict:
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
