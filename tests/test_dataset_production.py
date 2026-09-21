"""Tests for the dataset production pipeline (rupsaa/dataset/, scripts/dataset_*.py).

Every test uses an isolated tmp_path DatasetStore — none of these touch the
real data/production/ workspace or the existing data/train.jsonl pipeline.
"""

import pytest

from rupsaa.dataset.dedup import (
    char_ngrams,
    find_exact_duplicates,
    find_near_duplicates,
    fingerprint,
    jaccard_similarity,
)
from rupsaa.dataset.normalize import normalize_text
from rupsaa.dataset.repetition import (
    count_emojis,
    find_emoji_overuse,
    find_repeated_assistant_replies,
    find_watchlist_overuse,
)
from rupsaa.dataset.schema import ConversationRecord, derive_conversation_length, validate_record
from rupsaa.dataset.stats import build_stats
from rupsaa.dataset.store import DatasetStore
from rupsaa.dataset.taxonomy import CATEGORIES, is_valid_category
from rupsaa.dataset.unicode_checks import check_text_unicode


def make_record(id="rup-000001", category="casual_friendly", quality_status="draft", **overrides) -> ConversationRecord:
    defaults = dict(
        id=id,
        messages=[
            {"role": "user", "content": "hi there"},
            {"role": "assistant", "content": "hey! what's up?"},
        ],
        language="en",
        category=category,
        source_type="human_authored",
        quality_status=quality_status,
        notes="" if quality_status != "rejected" else "test rejection reason",
    )
    defaults.update(overrides)
    return ConversationRecord(**defaults)


# --- taxonomy ---

def test_taxonomy_has_all_20_required_categories():
    required = {
        "bengali_natural", "banglish_natural", "english_conversation",
        "code_switch_bn_en", "code_switch_banglish_en", "casual_friendly",
        "rupsaa_personality", "flirty_contextual_adult", "relationship_dating",
        "adult_terminology_education", "creator_platform_terminology",
        "creator_questions_workflows", "short_answers", "detailed_explanations",
        "follow_up_questions", "uncertainty_handling", "correcting_misunderstandings",
        "multi_turn", "rag_aware", "adversarial_difficult_language",
    }
    assert required.issubset(set(CATEGORIES))


def test_is_valid_category():
    assert is_valid_category("bengali_natural")
    assert not is_valid_category("not_a_real_category")


# --- normalize ---

def test_normalize_text_applies_nfc_and_strips_bom():
    text = "﻿hello   world"
    result = normalize_text(text)
    assert result == "hello world"


def test_normalize_text_preserves_zwj_zwnj():
    # ZWNJ (U+200C) is meaningful in Bengali typography — must survive normalization.
    text = "ক‌খ"
    assert "‌" in normalize_text(text)


def test_normalize_text_collapses_excess_blank_lines():
    text = "para one\n\n\n\n\npara two"
    assert normalize_text(text) == "para one\n\npara two"


# --- unicode checks ---

def test_check_text_unicode_flags_replacement_char():
    issues = check_text_unicode("hello � world")
    assert any("replacement" in i for i in issues)


def test_check_text_unicode_clean_bengali_text_has_no_issues():
    assert check_text_unicode("আমি ভালো আছি") == []


def test_check_text_unicode_flags_control_char():
    issues = check_text_unicode("hello\x07world")
    assert any("control character" in i for i in issues)


# --- schema ---

def test_derive_conversation_length_short_medium_long():
    bins = {"short_max_turns": 1, "medium_max_turns": 3}
    one_turn = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hi"}]
    three_turn = one_turn * 3
    five_turn = one_turn * 5
    assert derive_conversation_length(one_turn, bins) == "short"
    assert derive_conversation_length(three_turn, bins) == "medium"
    assert derive_conversation_length(five_turn, bins) == "long"


def test_validate_record_accepts_valid_record():
    record = make_record()
    assert validate_record(record) == []


def test_validate_record_rejects_unknown_category():
    record = make_record(category="not_a_real_category")
    errors = validate_record(record)
    assert any("unknown category" in e for e in errors)


def test_validate_record_rejects_missing_id():
    record = make_record(id="")
    errors = validate_record(record)
    assert any("missing id" in e for e in errors)


def test_validate_record_requires_notes_when_rejected():
    record = make_record(quality_status="rejected", notes="")
    errors = validate_record(record)
    assert any("rejected conversations must have" in e for e in errors)


def test_validate_record_rejects_empty_messages():
    record = make_record(messages=[])
    errors = validate_record(record)
    assert any("non-empty list" in e for e in errors)


def test_validate_record_rejects_bad_unicode_in_message():
    record = make_record(messages=[
        {"role": "user", "content": "hi �"},
        {"role": "assistant", "content": "hello"},
    ])
    errors = validate_record(record)
    assert any("replacement" in e for e in errors)


def test_strip_for_training_only_has_messages_key():
    record = make_record()
    stripped = record.strip_for_training()
    assert set(stripped.keys()) == {"messages"}
    assert stripped["messages"] == [
        {"role": "user", "content": "hi there"},
        {"role": "assistant", "content": "hey! what's up?"},
    ]


def test_to_dict_and_from_dict_roundtrip():
    record = make_record()
    restored = ConversationRecord.from_dict(record.to_dict())
    assert restored == record


# --- store ---

@pytest.fixture
def store(tmp_path):
    return DatasetStore(tmp_path / "production")


def test_store_creates_directory_layout(store):
    assert store.drafts_dir.exists()
    assert store.approved_dir.exists()
    assert store.rejected_dir.exists()
    assert store.exports_dir.exists()
    assert store.reports_dir.exists()


def test_store_generate_id_increments(store):
    first = store.generate_id("rup", 6)
    assert first == "rup-000001"
    store.save_new(make_record(id=first))
    second = store.generate_id("rup", 6)
    assert second == "rup-000002"


def test_store_save_new_writes_to_correct_status_dir(store):
    draft = make_record(id="rup-000001", quality_status="draft")
    store.save_new(draft)
    assert (store.drafts_dir / "rup-000001.json").exists()

    approved = make_record(id="rup-000002", quality_status="approved")
    store.save_new(approved)
    assert (store.approved_dir / "rup-000002.json").exists()


def test_store_save_new_refuses_to_overwrite(store):
    record = make_record(id="rup-000001")
    store.save_new(record)
    with pytest.raises(FileExistsError):
        store.save_new(record)


def test_store_load_finds_record_across_status_dirs(store):
    record = make_record(id="rup-000001", quality_status="approved")
    store.save_new(record)
    loc = store.load("rup-000001")
    assert loc is not None
    assert loc.record.id == "rup-000001"


def test_store_load_missing_id_returns_none(store):
    assert store.load("does-not-exist") is None


def test_store_move_transitions_status_and_relocates_file(store):
    record = make_record(id="rup-000001", quality_status="draft")
    path = store.save_new(record)
    new_path = store.move(record, path, "approved")
    assert not path.exists()
    assert new_path.exists()
    assert record.quality_status == "approved"
    loc = store.load("rup-000001")
    assert loc.record.quality_status == "approved"


def test_store_needs_edit_stays_in_drafts_dir(store):
    record = make_record(id="rup-000001", quality_status="draft")
    path = store.save_new(record)
    new_path = store.move(record, path, "needs_edit")
    assert new_path.parent == store.drafts_dir
    assert record.quality_status == "needs_edit"


def test_store_list_all_filters_by_status(store):
    store.save_new(make_record(id="rup-000001", quality_status="draft"))
    store.save_new(make_record(id="rup-000002", quality_status="approved"))
    store.save_new(make_record(id="rup-000003", quality_status="rejected", notes="bad"))

    approved_only = store.list_all({"approved"})
    assert [loc.record.id for loc in approved_only] == ["rup-000002"]

    all_records = store.list_all(None)
    assert len(all_records) == 3


# --- dedup ---

def test_fingerprint_identical_for_identical_records():
    a = make_record(id="a")
    b = make_record(id="b")  # different id, same messages
    assert fingerprint(a) == fingerprint(b)


def test_find_exact_duplicates():
    a = make_record(id="rup-a")
    b = make_record(id="rup-b")
    c = make_record(id="rup-c", messages=[{"role": "user", "content": "different"}, {"role": "assistant", "content": "totally different"}])
    dupes = find_exact_duplicates([a, b, c])
    assert dupes == [("rup-b", "rup-a")]


def test_char_ngrams_basic():
    grams = char_ngrams("hello", 3)
    assert "hel" in grams
    assert "ell" in grams
    assert "llo" in grams


def test_jaccard_similarity_identical_sets():
    a = {"abc", "bcd"}
    assert jaccard_similarity(a, a) == 1.0


def test_jaccard_similarity_disjoint_sets():
    assert jaccard_similarity({"abc"}, {"xyz"}) == 0.0


def test_find_near_duplicates_detects_similar_text():
    a = make_record(id="rup-a", messages=[
        {"role": "user", "content": "how are you doing today my friend"},
        {"role": "assistant", "content": "I'm doing pretty well thanks for asking"},
    ])
    b = make_record(id="rup-b", messages=[
        {"role": "user", "content": "how are you doing today my friend!"},
        {"role": "assistant", "content": "I'm doing pretty well thanks for asking!"},
    ])
    c = make_record(id="rup-c", messages=[
        {"role": "user", "content": "what's the capital of France"},
        {"role": "assistant", "content": "Paris is the capital of France"},
    ])
    pairs = find_near_duplicates([a, b, c], ngram_size=5, threshold=0.85)
    ids_found = {(p.id_a, p.id_b) for p in pairs}
    assert ("rup-a", "rup-b") in ids_found
    assert not any("rup-c" in pair for pair in ids_found)


def test_find_near_duplicates_raises_above_max_records():
    records = [make_record(id=f"rup-{i}") for i in range(5)]
    with pytest.raises(ValueError):
        find_near_duplicates(records, max_records=2)


# --- repetition ---

def test_count_emojis():
    assert count_emojis("hello 💕 world 😘") == 2
    assert count_emojis("no emoji here") == 0


def test_find_watchlist_overuse_flags_frequent_phrase():
    records = [
        make_record(id=f"rup-{i}", messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hey baby, what's up"},
        ])
        for i in range(5)
    ]
    flagged = find_watchlist_overuse(records, ["baby", "jaan"], max_ratio=0.15)
    phrases = {u.phrase for u in flagged}
    assert "baby" in phrases
    assert "jaan" not in phrases


def test_find_watchlist_overuse_no_flag_below_threshold():
    records = [make_record(id="rup-1", messages=[
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey baby"},
    ])] + [
        make_record(id=f"rup-{i}", messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello there, no pet names here"},
        ])
        for i in range(2, 10)
    ]
    flagged = find_watchlist_overuse(records, ["baby"], max_ratio=0.5)
    assert flagged == []


def test_find_repeated_assistant_replies():
    records = [
        make_record(id=f"rup-{i}", messages=[
            {"role": "user", "content": f"question {i}"},
            {"role": "assistant", "content": "I'm doing great, thanks!"},
        ])
        for i in range(4)
    ]
    repeated = find_repeated_assistant_replies(records, min_count=3)
    assert len(repeated) == 1
    assert repeated[0].count == 4


def test_find_emoji_overuse_flags_high_ratio():
    records = [
        make_record(id=f"rup-{i}", messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hey 💕😘🥰"},
        ])
        for i in range(5)
    ]
    report = find_emoji_overuse(records, max_per_message=2, max_message_ratio=0.5)
    assert report.exceeds_message_ratio_threshold is True
    assert len(report.messages_with_excess_emoji) == 5  # 3 emoji > max_per_message=2


def test_find_emoji_overuse_boundary_not_exceeded():
    records = [make_record(id="rup-1", messages=[
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey 💕"},
    ])]
    report = find_emoji_overuse(records, max_per_message=2, max_message_ratio=0.5)
    assert report.messages_with_excess_emoji == []


# --- stats ---

def test_build_stats_counts_records_correctly():
    records = [
        make_record(id="rup-1", category="bengali_natural", language="bn"),
        make_record(id="rup-2", category="english_conversation", language="en"),
    ]
    stats = build_stats(records)
    assert stats.total == 2
    assert stats.by_category["bengali_natural"] == 1
    assert stats.by_language["en"] == 1
    assert stats.message_count == 4


# --- import script logic ---

def test_dataset_import_build_record_and_validate(tmp_path):
    from scripts.dataset_import import build_record
    import argparse

    store = DatasetStore(tmp_path / "production")
    cfg = {
        "ids": {"prefix": "rup", "padding": 6},
        "conversation_length_bins": {"short_max_turns": 1, "medium_max_turns": 3},
    }
    args = argparse.Namespace(
        category="casual_friendly", subcategory=None, language="en", language_mix=None,
        tone=None, source_type="imported", status="draft", notes="",
    )
    raw = {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello!"}]}
    record = build_record(raw, store, cfg, args)
    assert record.id == "rup-000001"
    assert record.category == "casual_friendly"
    assert record.conversation_length == "short"
    assert validate_record(record) == []


def test_dataset_import_rejects_record_without_category(tmp_path):
    from scripts.dataset_import import build_record
    import argparse

    store = DatasetStore(tmp_path / "production")
    cfg = {
        "ids": {"prefix": "rup", "padding": 6},
        "conversation_length_bins": {"short_max_turns": 1, "medium_max_turns": 3},
    }
    args = argparse.Namespace(
        category=None, subcategory=None, language="en", language_mix=None,
        tone=None, source_type="imported", status="draft", notes="",
    )
    raw = {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello!"}]}
    with pytest.raises(ValueError):
        build_record(raw, store, cfg, args)


# --- export compatibility with the existing QLoRA pipeline ---

def test_exported_records_pass_existing_pipeline_validator(tmp_path):
    from scripts.validate_dataset import validate_record as pipeline_validate_record

    record = make_record(id="rup-000001", quality_status="approved", notes="")
    stripped = record.strip_for_training()
    errors = pipeline_validate_record(stripped, line_no=1)
    assert errors == []
