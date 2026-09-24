"""Tests for the voice/personality audit (rupsaa/dataset/voice_audit.py,
scripts/dataset_voice_audit.py).

Several of these are regression tests for real false positives found while
building the audit against the actual 508-conversation corpus — see the
module docstring and scripts/dataset_voice_audit.py for the narrative.
"""

from collections import Counter

from rupsaa.dataset.schema import ConversationRecord
from rupsaa.dataset.voice_audit import (
    _count_word_occurrences,
    _fake_rag_attribution_present,
    _platform_fact_present,
    _word_present,
    build_opener_counter,
    extract_signals,
    score_conversation,
)

PET_NAMES = ["baby", "babe", "jaan", "jaanu", "sona", "sweetheart", "cutie"]


def make_record(id="rup-1", category="casual_friendly", messages=None, language="en") -> ConversationRecord:
    return ConversationRecord(
        id=id,
        messages=messages or [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hey there"},
        ],
        language=language,
        category=category,
        source_type="imported",
        quality_status="draft",
    )


# --- word-boundary matching (the Bengali \b bug) ---

def test_word_present_does_not_false_match_substring():
    # "দিন" (day) must not match inside "দিনচর্যা" (daily routine).
    text = "কাজ, দিনচর্যা, নাকি চারপাশের মানুষ?"
    assert _word_present(["দিন"], text) is False


def test_word_present_matches_whole_bengali_word_ending_in_matra():
    # Regression: Python's \b does not fire correctly after Bengali vowel
    # signs (matras), which are Unicode combining marks, not \w. "না" ends
    # in a matra ("া") and was missed by a naive \b-based check.
    text = "একদমই না, বরং জিনিসটা ঘটার আগে।"
    assert _word_present(["একদমই না"], text) is True


def test_count_word_occurrences_counts_multiple_hits():
    text = "আসলে eta thik na, আসলে ami sure na."
    assert _count_word_occurrences(["আসলে"], text) == 2


def test_word_present_english_word_still_works():
    assert _word_present(["honestly"], "Honestly, I think so.") is True
    assert _word_present(["sona"], "This is about your persona.") is False


# --- platform-fact / RAG-attribution windowing ---

def test_platform_fact_not_flagged_for_unrelated_number():
    # "take 24 hours before deciding" in relationship advice is not a
    # platform fact — no platform/business context word nearby.
    text = 'a simple rule like "never decide anything important, take 24 hours" can protect you'
    assert _platform_fact_present(text) is False


def test_platform_fact_flagged_when_context_present():
    text = "the minimum withdrawal is $50 and payouts take 5 business days"
    assert _platform_fact_present(text) is True


def test_fake_rag_attribution_not_flagged_when_hedged():
    # "depends on the platform's policy, which platform?" is correct
    # uncertainty-handling, not a fabricated attribution.
    text = "That really depends on the specific platform's policy. Which platform are you asking about?"
    assert _fake_rag_attribution_present(text) is False


def test_fake_rag_attribution_flagged_when_asserted():
    text = "According to the platform's policy, payouts happen weekly."
    assert _fake_rag_attribution_present(text) is True


# --- extract_signals / score_conversation integration ---

def test_generic_ai_opener_anchored_to_message_start():
    # "absolutely" used mid-sentence as an intensifier must NOT be flagged.
    record = make_record(messages=[
        {"role": "user", "content": "does that make sense?"},
        {"role": "assistant", "content": "Watching that can absolutely shape how you feel about it."},
    ])
    sig = extract_signals(record, PET_NAMES)
    assert sig.generic_ai_opener is False


def test_generic_ai_opener_detected_at_actual_start():
    record = make_record(messages=[
        {"role": "user", "content": "can you help?"},
        {"role": "assistant", "content": "Certainly! I'd be happy to help you with that."},
    ])
    sig = extract_signals(record, PET_NAMES)
    assert sig.generic_ai_opener is True


def test_uncontextual_flirting_not_flagged_when_user_initiates():
    record = make_record(
        category="code_switch_bn_en",
        messages=[
            {"role": "user", "content": "are you flirting with me right now?"},
            {"role": "assistant", "content": "Hmm, caught. Maybe a little bit 😏"},
        ],
    )
    sig = extract_signals(record, PET_NAMES)
    assert sig.uncontextual_flirting is False


def test_uncontextual_flirting_flagged_when_unprompted():
    record = make_record(
        category="creator_platform_terminology",
        messages=[
            {"role": "user", "content": "What does PPV mean?"},
            {"role": "assistant", "content": "Careful, statements like that make me smug 😏"},
        ],
    )
    sig = extract_signals(record, PET_NAMES)
    assert sig.uncontextual_flirting is True


def test_formality_mismatch_detected():
    record = make_record(messages=[
        {"role": "user", "content": "তুমি কি ব্যস্ত?"},
        {"role": "assistant", "content": "না, আপনি বলুন আপনার কী প্রয়োজন।"},
    ])
    sig = extract_signals(record, PET_NAMES)
    assert sig.formality_mismatch is True


def test_formality_mismatch_not_flagged_for_casual_reply():
    record = make_record(messages=[
        {"role": "user", "content": "তুমি কি ব্যস্ত?"},
        {"role": "assistant", "content": "না রে, বল কী দরকার।"},
    ])
    sig = extract_signals(record, PET_NAMES)
    assert sig.formality_mismatch is False


def test_textbook_definition_flagged_for_generic_terminology_answer():
    record = make_record(
        category="creator_platform_terminology",
        messages=[
            {"role": "user", "content": 'What\'s a "custom request"?'},
            {"role": "assistant", "content": "It's personalized content a fan pays extra for, made to their specific ask."},
        ],
    )
    sig = extract_signals(record, PET_NAMES)
    assert sig.textbook_definition_only is True


def test_textbook_definition_not_flagged_outside_definitional_category():
    # Regression: a generic "starts with X is/means Y" regex previously
    # applied outside the definitional-category gate matched "is" inside
    # "this" ("Always ready for this...") and flagged good, witty replies
    # as textbook-flat. The check is now category-gated only.
    record = make_record(
        category="short_answers",
        messages=[
            {"role": "user", "content": "Worth fighting for or worth walking away from?"},
            {"role": "assistant", "content": 'Depends what "it" is, but you already know the answer if you\'re asking this way.'},
        ],
    )
    sig = extract_signals(record, PET_NAMES)
    assert sig.textbook_definition_only is False


def test_textbook_definition_not_flagged_with_personality_marker():
    record = make_record(
        category="creator_platform_terminology",
        messages=[
            {"role": "user", "content": 'What\'s a "custom request"?'},
            {"role": "assistant", "content": "Honestly, it's just personalized content a fan pays extra for."},
        ],
    )
    sig = extract_signals(record, PET_NAMES)
    assert sig.textbook_definition_only is False


def test_short_reaction_opener_followed_by_more_text_recognized():
    # Regression: the old pattern (\bfair\b$) required the ENTIRE message
    # to be just "fair" — missing the much more common "Fair. <rest>" case.
    record = make_record(messages=[
        {"role": "user", "content": "I already feel bad enough about it."},
        {"role": "assistant", "content": "Fair. A direct apology usually lands better than a vague one."},
    ])
    sig = extract_signals(record, PET_NAMES)
    assert sig.has_personality_marker is True


def test_basically_recognized_as_personality_marker():
    # "Basically" is the Voice Bible's own example of personality-carrying
    # phrasing for terminology answers — the marker list must recognize it.
    record = make_record(
        category="creator_platform_terminology",
        messages=[
            {"role": "user", "content": 'What\'s a "custom request"?'},
            {"role": "assistant", "content": "Basically it's personalized content a fan pays extra for."},
        ],
    )
    sig = extract_signals(record, PET_NAMES)
    assert sig.has_personality_marker is True
    assert sig.textbook_definition_only is False


def test_score_conversation_scores_within_bounds():
    record = make_record()
    counter = build_opener_counter([record])
    sig = extract_signals(record, PET_NAMES)
    result = score_conversation(record, sig, counter)
    for dim in (
        result.scores.naturalness, result.scores.language_quality,
        result.scores.rupsaa_identity, result.scores.contextual_appropriateness,
        result.scores.non_repetition, result.scores.factual_grounding,
    ):
        assert 1 <= dim <= 5
    assert result.recommendation in {"STRONG", "NEEDS_EDIT", "WEAK"}


def test_score_conversation_never_changes_quality_status():
    record = make_record()
    original_status = record.quality_status
    counter = build_opener_counter([record])
    sig = extract_signals(record, PET_NAMES)
    score_conversation(record, sig, counter)
    assert record.quality_status == original_status


def test_strong_recommendation_reachable_for_non_gated_category():
    # Regression: STRONG must not be structurally impossible for categories
    # outside a fixed "personality-forward" allowlist.
    record = make_record(
        category="correcting_misunderstandings",
        messages=[
            {"role": "user", "content": "So more followers always means more money, right?"},
            {"role": "assistant", "content": "Not really — a smaller, highly engaged audience often converts better. Honestly, reach and revenue aren't the same metric."},
        ],
    )
    counter = build_opener_counter([record])
    sig = extract_signals(record, PET_NAMES)
    result = score_conversation(record, sig, counter)
    assert result.scores.rupsaa_identity >= 4


def test_repetitive_opening_flagged_across_corpus():
    records = [
        make_record(id=f"rup-{i}", messages=[
            {"role": "user", "content": f"question {i}"},
            {"role": "assistant", "content": "Honestly not sure, but let's figure it out together."},
        ])
        for i in range(9)
    ]
    counter = build_opener_counter(records)
    sig = extract_signals(records[0], PET_NAMES)
    result = score_conversation(records[0], sig, counter)
    assert "REPETITIVE_OPENING" in result.flags


def test_build_opener_counter_counts_first_four_words():
    records = [
        make_record(id="a", messages=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "not sure honestly but ok"}]),
        make_record(id="b", messages=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "not sure honestly but wait"}]),
    ]
    counter = build_opener_counter(records)
    assert counter["not sure honestly but"] == 2
