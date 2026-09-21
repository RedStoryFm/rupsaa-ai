"""The extended Rupsaa production conversation schema.

A ConversationRecord wraps the exact same `messages` structure the QLoRA
pipeline consumes (role/content dicts — see scripts/validate_dataset.py's
VALID_ROLES) plus dataset-production metadata used for curation, review,
and reporting. `strip_for_training()` is the only function that matters for
compatibility with the existing pipeline: it must always produce exactly
`{"messages": [...]}`, nothing more, nothing less.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from rupsaa.dataset.taxonomy import (
    CONVERSATION_LENGTHS,
    LANGUAGES,
    QUALITY_STATUSES,
    SOURCE_TYPES,
    is_valid_category,
)
from rupsaa.dataset.unicode_checks import check_messages_unicode

VALID_ROLES = {"system", "user", "assistant"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def derive_conversation_length(messages: list[dict], bins: dict) -> str:
    turns = sum(1 for m in messages if m.get("role") == "user")
    if turns <= bins.get("short_max_turns", 1):
        return "short"
    if turns <= bins.get("medium_max_turns", 3):
        return "medium"
    return "long"


@dataclass
class ConversationRecord:
    id: str
    messages: list[dict] = field(default_factory=list)
    language: str = "en"
    language_mix: str | None = None
    category: str = "casual_friendly"
    subcategory: str | None = None
    tone: str | None = None
    conversation_length: str | None = None
    source_type: str = "imported"
    quality_status: str = "draft"
    notes: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationRecord":
        known_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)

    def strip_for_training(self) -> dict:
        """The ONLY thing that reaches the QLoRA pipeline: the canonical
        {"messages": [...]} shape, with no production metadata attached."""
        return {"messages": [{"role": m["role"], "content": m["content"]} for m in self.messages]}

    def touch(self) -> None:
        self.updated_at = now_iso()


def validate_record(record: ConversationRecord) -> list[str]:
    """Schema-level + unicode validation. Does not do dedup/repetition
    checks — those are dataset-wide checks living in dedup.py/repetition.py
    and run separately by scripts/dataset_audit.py."""
    errors: list[str] = []

    if not record.id or not record.id.strip():
        errors.append("missing id")

    if record.language not in LANGUAGES:
        errors.append(f"invalid language '{record.language}' (allowed: {sorted(LANGUAGES)})")

    if not is_valid_category(record.category):
        errors.append(f"unknown category '{record.category}' — see rupsaa.dataset.taxonomy.CATEGORIES")

    if record.source_type not in SOURCE_TYPES:
        errors.append(f"invalid source_type '{record.source_type}' (allowed: {sorted(SOURCE_TYPES)})")

    if record.quality_status not in QUALITY_STATUSES:
        errors.append(f"invalid quality_status '{record.quality_status}' (allowed: {sorted(QUALITY_STATUSES)})")

    if record.conversation_length and record.conversation_length not in CONVERSATION_LENGTHS:
        errors.append(f"invalid conversation_length '{record.conversation_length}' (allowed: {sorted(CONVERSATION_LENGTHS)})")

    if record.quality_status == "rejected" and not record.notes.strip():
        errors.append("rejected conversations must have a non-empty 'notes' explaining why")

    if not record.messages:
        errors.append("'messages' must be a non-empty list")
        return errors

    has_user, has_assistant = False, False
    for i, msg in enumerate(record.messages):
        if not isinstance(msg, dict):
            errors.append(f"message {i}: not an object")
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in VALID_ROLES:
            errors.append(f"message {i}: unsupported role '{role}'")
        if role == "user":
            has_user = True
        if role == "assistant":
            has_assistant = True
        if not isinstance(content, str) or not content.strip():
            errors.append(f"message {i}: empty or non-string content")

    if not has_user:
        errors.append("conversation has no 'user' message")
    if not has_assistant:
        errors.append("conversation has no 'assistant' message")

    errors.extend(check_messages_unicode(record.messages))

    return errors
