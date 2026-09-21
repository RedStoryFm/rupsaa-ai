import json
from pathlib import Path

from scripts.prepare_dataset import split_records
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
