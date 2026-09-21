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
from rupsaa.personality.system_prompt import build_system_prompt


@dataclass
class ChatResult:
    text: str
    blocked: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0


class RupsaaEngine:
    def __init__(self, loaded: LoadedModel):
        self.loaded = loaded

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
        generation_overrides: dict | None = None,
    ) -> ChatResult:
        boundary = check_text(user_message)
        if not boundary.allowed:
            return ChatResult(text=REFUSAL_MESSAGE, blocked=True)

        system_prompt = build_system_prompt(retrieved_context=retrieved_context)
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
