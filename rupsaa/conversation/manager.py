"""Conversation state management.

Storage is behind a small interface (ConversationStore) so the default
in-memory backend can be swapped for Redis or PostgreSQL later without
touching ConversationManager or any caller (api/services.py, scripts/chat.py).
History length is capped (configs/inference.yaml conversation.max_history_messages)
so a conversation cannot grow the prompt unbounded.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from rupsaa.config import load_inference_config
from rupsaa.model.generation import ChatMessage


@dataclass
class Conversation:
    conversation_id: str
    messages: list[ChatMessage] = field(default_factory=list)

    def approx_token_count(self) -> int:
        # Rough heuristic (chars/4) used only for logging/observability, not
        # for truncation decisions — history truncation uses message count.
        return sum(len(m.content) for m in self.messages) // 4


class ConversationStore(ABC):
    @abstractmethod
    def get(self, conversation_id: str) -> Conversation | None: ...

    @abstractmethod
    def save(self, conversation: Conversation) -> None: ...

    @abstractmethod
    def delete(self, conversation_id: str) -> None: ...


class InMemoryConversationStore(ConversationStore):
    """Default development backend. Not persisted across process restarts —
    swap for a Redis- or PostgreSQL-backed ConversationStore in production
    by implementing this same interface."""

    def __init__(self):
        self._conversations: dict[str, Conversation] = {}

    def get(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)

    def save(self, conversation: Conversation) -> None:
        self._conversations[conversation.conversation_id] = conversation

    def delete(self, conversation_id: str) -> None:
        self._conversations.pop(conversation_id, None)


class ConversationManager:
    def __init__(self, store: ConversationStore | None = None, max_history_messages: int | None = None):
        self.store = store or InMemoryConversationStore()
        self.max_history_messages = max_history_messages or load_inference_config()["conversation"]["max_history_messages"]

    def get_or_create(self, conversation_id: str | None) -> Conversation:
        if conversation_id:
            existing = self.store.get(conversation_id)
            if existing:
                return existing
        new_id = conversation_id or str(uuid.uuid4())
        conversation = Conversation(conversation_id=new_id)
        self.store.save(conversation)
        return conversation

    def append_turn(self, conversation: Conversation, user_message: str, assistant_message: str) -> Conversation:
        conversation.messages.append(ChatMessage(role="user", content=user_message))
        conversation.messages.append(ChatMessage(role="assistant", content=assistant_message))
        if len(conversation.messages) > self.max_history_messages:
            conversation.messages = conversation.messages[-self.max_history_messages:]
        self.store.save(conversation)
        return conversation

    def reset(self, conversation_id: str) -> None:
        self.store.delete(conversation_id)
