"""High-level Rupsaa inference engine.

This is the single code path both scripts/chat.py (terminal) and
api/services.py (FastAPI) go through — neither implements its own model
stack. It wires together: model loading, the centralized personality system
prompt, essential hard-boundary checks, and generation.
"""

from __future__ import annotations

from dataclasses import dataclass

from rupsaa.guardrails.essential_boundaries import REFUSAL_MESSAGE, check_text
from rupsaa.model.generation import (
    ChatMessage,
    GenerationParams,
    generate_reply,
)
from rupsaa.model.loader import LoadedModel, load_model
import logging

from rupsaa.config import get_settings
from rupsaa.personality.system_prompt import build_system_prompt, resolve_prompt_version

logger = logging.getLogger(__name__)


@dataclass
class ChatResult:
    text: str
    blocked: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0


class RupsaaEngine:
    def __init__(self, loaded: LoadedModel, prompt_version: str | None = None):
        self.loaded = loaded
        self.prompt_version = resolve_prompt_version(
            loaded.adapter_path, prompt_version or get_settings().prompt_version
        )
        logger.info("system prompt version: %s (adapter: %s)", self.prompt_version, loaded.adapter_path)

    @classmethod
    def load(cls, **kwargs) -> "RupsaaEngine":
        return cls(load_model(**kwargs))

    @property
    def model(self):
        return self.loaded.model

    @property
    def tokenizer(self):
        return self.loaded.tokenizer

    def chat(
        self,
        *,
        history: list[ChatMessage],
        user_message: str,
        retrieved_context: str | None = None,
        terminology_context: str | None = None,
        conversation_note: str | None = None,
        generation_overrides: dict | None = None,
    ) -> ChatResult:
        boundary = check_text(user_message)
        if not boundary.allowed:
            return ChatResult(text=REFUSAL_MESSAGE, blocked=True)

        system_prompt = build_system_prompt(
            retrieved_context=retrieved_context,
            terminology_context=terminology_context,
            conversation_note=conversation_note,
            prompt_version=self.prompt_version,
        )
        messages = (
            [ChatMessage(role="system", content=system_prompt)]
            + history
            + [ChatMessage(role="user", content=user_message)]
        )
        params = GenerationParams.from_config(generation_overrides)
        result = generate_reply(self.model, self.tokenizer, messages, params)
        return ChatResult(
            text=result.text,
            blocked=False,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
