import json
from pathlib import Path

from rupsaa.dataset.dedup import group_near_duplicates
from rupsaa.dataset.schema import ConversationRecord
from scripts.prepare_dataset import split_id_groups, split_records
from scripts.validate_dataset import validate_file, validate_record


def write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


VALID_RECORD = {
    "messages": [
        {"role": "system", "content": "You are Rupsaa."},
        {"role": "user", "content": "Tumi ke?"},
        {"role": "assistant", "content": "Ami Rupsaa 💕"},
    ]
}


def test_validate_record_accepts_valid_conversation():
    errors = validate_record(VALID_RECORD, line_no=1)
    assert errors == []


def test_validate_record_rejects_missing_messages():
    errors = validate_record({}, line_no=1)
    assert any("messages" in e for e in errors)


def test_validate_record_rejects_unsupported_role():
    bad = {"messages": [{"role": "bot", "content": "hi"}, {"role": "user", "content": "hi"}]}
    errors = validate_record(bad, line_no=2)
    assert any("unsupported role" in e for e in errors)


def test_validate_record_rejects_empty_content():
    bad = {"messages": [{"role": "user", "content": "   "}, {"role": "assistant", "content": "hi"}]}
    errors = validate_record(bad, line_no=3)
    assert any("empty" in e for e in errors)


def test_validate_record_requires_user_and_assistant():
    only_user = {"messages": [{"role": "user", "content": "hi"}]}
    errors = validate_record(only_user, line_no=4)
    assert any("no 'assistant'" in e for e in errors)


def test_validate_file_detects_invalid_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"messages": [}\n', encoding="utf-8")
    report = validate_file(path)
    assert not report.is_valid
    assert any("invalid JSON" in e for e in report.errors)


def test_validate_file_reports_stats_for_valid_data(tmp_path):
    path = tmp_path / "good.jsonl"
    write_jsonl(path, [VALID_RECORD, VALID_RECORD])
    report = validate_file(path)
    assert report.is_valid
    assert report.valid_conversations == 2
    assert report.message_count == 6
    assert report.approx_token_count > 0


def test_validate_file_flags_exact_duplicates(tmp_path):
    path = tmp_path / "dupes.jsonl"
    write_jsonl(path, [VALID_RECORD, VALID_RECORD])
    report = validate_file(path)
    assert any("duplicate" in w for w in report.warnings)


def test_validate_file_missing_file(tmp_path):
    report = validate_file(tmp_path / "does_not_exist.jsonl")
    assert not report.is_valid


def test_split_records_is_deterministic_with_seed():
    records = [
        {"messages": [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]}
        for i in range(20)
    ]
    train1, val1, test1 = split_records(records, seed=42, train_ratio=0.8, val_ratio=0.1)
    train2, val2, test2 = split_records(records, seed=42, train_ratio=0.8, val_ratio=0.1)
    assert train1 == train2
    assert val1 == val2
    assert test1 == test2


def test_split_records_covers_all_records_without_overlap():
    records = [
        {"messages": [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]}
        for i in range(15)
    ]
    train, val, test = split_records(records, seed=1, train_ratio=0.8, val_ratio=0.1)
    assert len(train) + len(val) + len(test) == len(records)
    all_content = [r["messages"][0]["content"] for r in (train + val + test)]
    assert len(set(all_content)) == len(records)


def _record(id, content):
    return ConversationRecord(
        id=id,
        messages=[{"role": "user", "content": content}, {"role": "assistant", "content": "reply " + content}],
        language="en",
        category="casual_friendly",
        source_type="imported",
        quality_status="approved",
    )


def test_group_near_duplicates_clusters_similar_records():
    reply = "That sounds like a genuinely long and eventful day, tell me more about it."
    records = [
        ConversationRecord(id="a", messages=[{"role": "assistant", "content": reply}],
                            language="en", category="casual_friendly", source_type="imported", quality_status="approved"),
        ConversationRecord(id="b", messages=[{"role": "assistant", "content": reply + "!"}],
                            language="en", category="casual_friendly", source_type="imported", quality_status="approved"),
        _record("c", "Zxqvw plork nbfjt ywiu gastro quibble ninefold thraxonomy scrimshaw."),
    ]
    groups = group_near_duplicates(records, ngram_size=5, threshold=0.85)
    ids_by_group = [sorted(g) for g in groups]
    assert ["a", "b"] in ids_by_group
    assert ["c"] in ids_by_group


def test_group_near_duplicates_all_singletons_when_records_are_distinct():
    distinct_texts = [
        "The mango tree in the garden finally bloomed this spring after years.",
        "Quarterly revenue projections need revising before the board meeting.",
        "কাল রাতে প্রচণ্ড বৃষ্টি হয়েছিল, রাস্তাঘাট সব ভেসে গেছে।",
        "Debugging the payment gateway took most of the afternoon today.",
        "সে বলল আগামীকাল সকালে রওনা দেবে, প্রস্তুতি প্রায় শেষ।",
        "Switching careers at thirty felt terrifying but oddly liberating.",
    ]
    records = [_record(f"r{i}", text) for i, text in enumerate(distinct_texts)]
    groups = group_near_duplicates(records, ngram_size=5, threshold=0.85)
    assert len(groups) == 6
    assert all(len(g) == 1 for g in groups)


def test_split_id_groups_keeps_clusters_together():
    groups = [["a", "b", "c"], ["d"], ["e"], ["f"], ["g"], ["h"], ["i"], ["j"]]
    train, val, test = split_id_groups(groups, seed=7, train_ratio=0.8, val_ratio=0.1)
    # The 3-member cluster must land entirely in one bucket, never split.
    for bucket in (train, val, test):
        overlap = bucket & {"a", "b", "c"}
        assert overlap == set() or overlap == {"a", "b", "c"}


def test_split_id_groups_covers_all_ids_without_overlap():
    groups = [[f"id{i}"] for i in range(30)]
    train, val, test = split_id_groups(groups, seed=3, train_ratio=0.8, val_ratio=0.1)
    assert train & val == set()
    assert train & test == set()
    assert val & test == set()
    assert train | val | test == {f"id{i}" for i in range(30)}
