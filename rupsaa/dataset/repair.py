"""Minimal-edit repair application for DRAFT conversations flagged
NEEDS_EDIT by the voice audit (rupsaa/dataset/voice_audit.py).

This module only ever patches the `content` of a single existing
`assistant`-role message in place — it never touches `user` or `system`
messages, never changes `category`/`language`/`quality_status`, and never
adds or removes messages. That's a deliberate, narrow contract: repair is
supposed to be the smallest edit that materially improves a conversation,
not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from rupsaa.dataset.schema import ConversationRecord
from rupsaa.dataset.store import DatasetStore


class RepairError(ValueError):
    pass


@dataclass
class RepairEdit:
    conversation_id: str
    message_index: int
    new_content: str
    reason: str
    repair_notes: str = ""


@dataclass
class RepairLogEntry:
    conversation_id: str
    original_scores: dict
    original_flags: list[str]
    changed_message_indices: list[int]
    reason_for_change: str
    before: list[str]
    after: list[str]
    repair_notes: str


def apply_repair(
    store: DatasetStore,
    edit: RepairEdit,
    audit_index: dict[str, dict],
) -> RepairLogEntry:
    """Applies a single targeted content edit to one assistant message.

    audit_index maps conversation_id -> the original VOICE_AUDIT_V1.jsonl
    record (scores/flags), so the repair log always captures the BEFORE
    state honestly rather than re-deriving it after the fact.

    Raises RepairError (without touching anything) if:
      - the conversation doesn't exist
      - message_index is out of range or not an assistant message
      - new_content is empty or identical to the existing content
    """
    loc = store.load(edit.conversation_id)
    if loc is None:
        raise RepairError(f"no conversation found with id {edit.conversation_id}")
    record = loc.record

    if edit.message_index < 0 or edit.message_index >= len(record.messages):
        raise RepairError(f"{edit.conversation_id}: message_index {edit.message_index} out of range")

    message = record.messages[edit.message_index]
    if message.get("role") != "assistant":
        raise RepairError(
            f"{edit.conversation_id}: refusing to edit a '{message.get('role')}' message "
            f"at index {edit.message_index} — repair only ever touches assistant messages"
        )

    old_content = message["content"]
    new_content = edit.new_content.strip()
    if not new_content:
        raise RepairError(f"{edit.conversation_id}: new_content is empty")
    if new_content == old_content:
        raise RepairError(f"{edit.conversation_id}: new_content is identical to existing content, nothing to do")

    audit_entry = audit_index.get(edit.conversation_id, {})
    original_scores = audit_entry.get("scores", {})
    original_flags = audit_entry.get("flags", [])

    message["content"] = new_content
    record.updated_at = datetime.now(timezone.utc).isoformat()
    # quality_status stays "draft" — repair never approves/rejects.
    store.save(record, loc.path)

    return RepairLogEntry(
        conversation_id=edit.conversation_id,
        original_scores=original_scores,
        original_flags=original_flags,
        changed_message_indices=[edit.message_index],
        reason_for_change=edit.reason,
        before=[old_content],
        after=[new_content],
        repair_notes=edit.repair_notes,
    )


def build_audit_index(audit_records: list[dict]) -> dict[str, dict]:
    return {r["conversation_id"]: r for r in audit_records}
