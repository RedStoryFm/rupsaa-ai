"""Conversation state management.

Storage is behind a small interface (ConversationStore) so the default
in-memory backend can be swapped for Redis or PostgreSQL later without
touching ConversationManager or any caller (api/services.py, scripts/chat.py).
History length is capped (configs/inference.yaml conversation.max_history_messages)
so a conversation cannot grow the prompt unbounded.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field

from rupsaa.config import load_inference_config
from rupsaa.model.generation import ChatMessage

_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


@dataclass
class Conversation:
    conversation_id: str
    messages: list[ChatMessage] = field(default_factory=list)
    # How many of the oldest messages were dropped by the history cap, so a
    # "what did I say first?" question can be answered honestly.
    dropped_messages: int = 0

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
    """Default backend: process memory. Not persisted across restarts (documented in
    docs/PRODUCTION_DEPLOYMENT.md) — swap for Redis/PostgreSQL by implementing this interface.

    Bounded so a public server can't grow without limit: at most `max_conversations`
    (least-recently-used dropped first) and conversations idle for `idle_seconds` expire."""

    def __init__(self, max_conversations: int = 5000, idle_seconds: float = 6 * 3600, clock=time.monotonic):
        self._conversations: OrderedDict[str, tuple[float, Conversation]] = OrderedDict()
        self.max_conversations = max(1, max_conversations)
        self.idle_seconds = idle_seconds
        self._clock = clock
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        while self._conversations:
            cid, (seen, _) = next(iter(self._conversations.items()))
            if now - seen <= self.idle_seconds and len(self._conversations) <= self.max_conversations:
                break
            del self._conversations[cid]

    def get(self, conversation_id: str) -> Conversation | None:
        with self._lock:
            now = self._clock()
            self._expire(now)
            item = self._conversations.get(conversation_id)
            if item is None:
                return None
            self._conversations[conversation_id] = (now, item[1])
            self._conversations.move_to_end(conversation_id)
            return item[1]

    def save(self, conversation: Conversation) -> None:
        with self._lock:
            now = self._clock()
            self._conversations[conversation.conversation_id] = (now, conversation)
            self._conversations.move_to_end(conversation.conversation_id)
            self._expire(now)

    def delete(self, conversation_id: str) -> None:
        with self._lock:
            self._conversations.pop(conversation_id, None)

    def __len__(self) -> int:
        return len(self._conversations)


class ConversationManager:
    def __init__(self, store: ConversationStore | None = None, max_history_messages: int | None = None):
        if store is None:
            from rupsaa.config import get_settings
            settings = get_settings()
            store = InMemoryConversationStore(settings.max_conversations, settings.conversation_idle_minutes * 60)
        self.store = store
        self.max_history_messages = max_history_messages or load_inference_config()["conversation"]["max_history_messages"]

    def get_or_create(self, conversation_id: str | None) -> Conversation:
        """Existing conversation, or a NEW one with a fresh server-issued id.

        A client-chosen id is never adopted: otherwise two users sending the same
        guessable id ("1", "test") would share one history, and a recall question
        would read out the other person's messages."""
        if conversation_id and _ID_RE.match(conversation_id):
            existing = self.store.get(conversation_id)
            if existing:
                return existing
        new_id = str(uuid.uuid4())
        conversation = Conversation(conversation_id=new_id)
        self.store.save(conversation)
        return conversation

    def append_turn(self, conversation: Conversation, user_message: str, assistant_message: str) -> Conversation:
        conversation.messages.append(ChatMessage(role="user", content=user_message))
        conversation.messages.append(ChatMessage(role="assistant", content=assistant_message))
        if len(conversation.messages) > self.max_history_messages:
            overflow = len(conversation.messages) - self.max_history_messages
            conversation.dropped_messages += overflow
            conversation.messages = conversation.messages[-self.max_history_messages:]
        self.store.save(conversation)
        return conversation

    def reset(self, conversation_id: str) -> None:
        self.store.delete(conversation_id)
