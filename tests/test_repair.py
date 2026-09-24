import pytest

from rupsaa.dataset.repair import RepairEdit, RepairError, apply_repair
from rupsaa.dataset.schema import ConversationRecord
from rupsaa.dataset.store import DatasetStore


def make_record(id="rup-000001", messages=None) -> ConversationRecord:
    return ConversationRecord(
        id=id,
        messages=messages or [
            {"role": "system", "content": "You are Rupsaa."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello there"},
        ],
        language="en",
        category="casual_friendly",
        source_type="imported",
        quality_status="draft",
    )


@pytest.fixture
def store(tmp_path):
    return DatasetStore(tmp_path / "production")


def test_apply_repair_patches_assistant_message(store):
    record = make_record()
    path = store.save_new(record)
    edit = RepairEdit(conversation_id="rup-000001", message_index=2, new_content="hey, what's up", reason="add warmth")
    log = apply_repair(store, edit, audit_index={})
    assert log.before == ["hello there"]
    assert log.after == ["hey, what's up"]
    assert log.changed_message_indices == [2]

    reloaded = store.load("rup-000001").record
    assert reloaded.messages[2]["content"] == "hey, what's up"
    assert reloaded.quality_status == "draft"  # unchanged


def test_apply_repair_refuses_to_edit_user_message(store):
    record = make_record()
    store.save_new(record)
    edit = RepairEdit(conversation_id="rup-000001", message_index=1, new_content="edited user text", reason="x")
    with pytest.raises(RepairError, match="refusing to edit"):
        apply_repair(store, edit, audit_index={})
    # confirm nothing was actually changed on disk
    reloaded = store.load("rup-000001").record
    assert reloaded.messages[1]["content"] == "hi"


def test_apply_repair_refuses_to_edit_system_message(store):
    record = make_record()
    store.save_new(record)
    edit = RepairEdit(conversation_id="rup-000001", message_index=0, new_content="You are someone else.", reason="x")
    with pytest.raises(RepairError, match="refusing to edit"):
        apply_repair(store, edit, audit_index={})


def test_apply_repair_rejects_empty_content(store):
    record = make_record()
    store.save_new(record)
    edit = RepairEdit(conversation_id="rup-000001", message_index=2, new_content="   ", reason="x")
    with pytest.raises(RepairError, match="empty"):
        apply_repair(store, edit, audit_index={})


def test_apply_repair_rejects_noop_edit(store):
    record = make_record()
    store.save_new(record)
    edit = RepairEdit(conversation_id="rup-000001", message_index=2, new_content="hello there", reason="x")
    with pytest.raises(RepairError, match="identical"):
        apply_repair(store, edit, audit_index={})


def test_apply_repair_missing_conversation_raises(store):
    edit = RepairEdit(conversation_id="rup-999999", message_index=0, new_content="x", reason="x")
    with pytest.raises(RepairError, match="no conversation found"):
        apply_repair(store, edit, audit_index={})


def test_apply_repair_out_of_range_index_raises(store):
    record = make_record()
    store.save_new(record)
    edit = RepairEdit(conversation_id="rup-000001", message_index=99, new_content="x", reason="x")
    with pytest.raises(RepairError, match="out of range"):
        apply_repair(store, edit, audit_index={})


def test_apply_repair_captures_original_scores_from_audit_index(store):
    record = make_record()
    store.save_new(record)
    audit_index = {"rup-000001": {"scores": {"total_score": 24}, "flags": ["LOW_PERSONALITY"]}}
    edit = RepairEdit(conversation_id="rup-000001", message_index=2, new_content="hey!", reason="x")
    log = apply_repair(store, edit, audit_index)
    assert log.original_scores == {"total_score": 24}
    assert log.original_flags == ["LOW_PERSONALITY"]


def test_apply_repair_does_not_change_other_messages(store):
    record = make_record(messages=[
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ])
    store.save_new(record)
    edit = RepairEdit(conversation_id="rup-000001", message_index=4, new_content="a2 edited", reason="x")
    apply_repair(store, edit, audit_index={})
    reloaded = store.load("rup-000001").record
    assert reloaded.messages[1]["content"] == "q1"
    assert reloaded.messages[2]["content"] == "a1"
    assert reloaded.messages[3]["content"] == "q2"
    assert reloaded.messages[4]["content"] == "a2 edited"
