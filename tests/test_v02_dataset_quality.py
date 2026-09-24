"""V0.2 prep: corpus diversity gate, voice-audit catchphrase fix, language
quality triage, and the export gate. Synthetic in-memory corpora only — the
real dataset, the frozen V0.1 snapshot and its export are never touched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from rupsaa.dataset.diversity import analyze_corpus, analyze_with_config, skeleton
from rupsaa.dataset.language_quality import (
    analyze_record,
    propose_filler_repair,
    repair_script_mix,
    triage_record,
)
from rupsaa.dataset.schema import ConversationRecord
from rupsaa.dataset.store import DatasetStore
from rupsaa.dataset.voice_audit import build_opener_counter, extract_signals, score_conversation

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_VARIED = [
    "Blue is a calm pick — what drew you to it?",
    "Weekends are for sleeping in, at least for me.",
    "That sounds exhausting. Did anything help?",
    "Start small: one message, not a whole speech.",
    "Depends on the platform, which one are you on?",
    "Coffee first, decisions later.",
    "I'd keep it simple and ask directly.",
    "Maybe give it a week before deciding.",
    "Rain makes everything slower, doesn't it?",
    "Good question for a lazy Sunday.",
]


def rec(i: int, reply: str, *, language="en", source="synthetic_curated", user="hey", status="approved",
        category="casual_friendly") -> ConversationRecord:
    return ConversationRecord(
        id=f"rup-{i:06d}", language=language, category=category, source_type=source, quality_status=status,
        messages=[{"role": "user", "content": user}, {"role": "assistant", "content": reply}],
    )


def v01_like_corpus(n=1129, honestly=863):
    """Same shape as the V0.1 training set: 'honestly' in 863/1129 replies."""
    out = []
    for i in range(n):
        base = _VARIED[i % len(_VARIED)] + f" ({i})"
        reply = f"Honestly, {base[0].lower()}{base[1:]}" if i < honestly else base
        out.append(rec(i, reply))
    return out


_WORDS = ("river lamp garden ticket window pepper orbit velvet candle harbor meadow puzzle ribbon canyon "
          "biscuit lantern marble compass thunder saddle violet anchor cactus falcon glacier hammock igloo jasmine "
          "kettle lemon mango nectar oyster pebble quartz raven saffron tulip umbrella walnut yarrow zephyr").split()
_OPENERS = ("maybe", "sure", "yeah", "hmm", "well", "okay", "right", "nah", "ooh", "wait", "look", "see", "true",
            "fair", "yes", "no", "so", "oh", "aha", "hey")


def natural_corpus(n=400):
    """Varied replies (random words, openers and shapes); 'honestly' in 2.5% — a normal word, not a tic."""
    import random

    rng = random.Random(7)
    out = []
    for i in range(n):
        words = " ".join(rng.sample(_WORDS, rng.randint(3, 8)))
        shape = i % 4
        opener = rng.choice(_OPENERS).capitalize()
        reply = {0: f"{opener} {words}.", 1: f"{opener}, {words}?", 2: f"{opener} {words}. {rng.choice(_WORDS)} too.",
                 3: f"{opener} {words} - {rng.choice(_WORDS)}!"}[shape]
        if i % 40 == 0:
            reply = "Honestly, " + reply[0].lower() + reply[1:]
        out.append(rec(i, reply))
    return out


# --- corpus diversity gate --------------------------------------------------------------

def test_v01_style_catchphrase_concentration_is_never_training_ready():
    report = analyze_corpus(v01_like_corpus())
    assert not report.training_ready
    keys = {(i.kind, i.key) for i in report.blocking}
    assert ("catchphrase", "honestly") in keys
    assert "honestly" in report.overused_phrases()


def test_repetitive_openings_are_blocked():
    corpus = [rec(i, f"Sheta {w} ekta kotha ({i})") if i % 3 else rec(i, f"{_VARIED[i % 10]} ({i})")
              for i, w in enumerate(["bhalo", "moja", "notun"] * 60)]
    report = analyze_corpus(corpus, watchlist=["honestly"])
    assert ("opening", "sheta") in {(i.kind, i.key) for i in report.blocking}
    assert "sheta" in report.overused_openings()


def test_natural_occasional_use_is_allowed():
    report = analyze_corpus(natural_corpus())
    assert report.training_ready, [i.describe() for i in report.blocking]


def test_auto_detected_lexical_concentration_without_watchlist():
    corpus = [rec(i, f"{_VARIED[i % 10]} vibe-check {i}") for i in range(200)]
    report = analyze_corpus(corpus, watchlist=[])
    assert any(i.kind == "lexical_concentration" and i.key.startswith("vibe") for i in report.blocking)


def test_phrase_language_correlation_detected_per_language_group():
    corpus = [rec(i, f"{_VARIED[i % 10]} ({i})", language="en") for i in range(400)]
    corpus += [rec(1000 + i, f"এটা actually ভালো ({i})", language="bn") for i in range(60)]
    report = analyze_corpus(corpus, watchlist=["actually"])
    scopes = {i.scope for i in report.blocking if i.key == "actually"}
    assert "language:bn" in scopes


def test_small_corpus_only_warns():
    report = analyze_corpus(v01_like_corpus(n=20, honestly=20))
    assert report.training_ready and report.warnings and not report.gated


def test_skeleton_shapes():
    assert skeleton("Honestly X - Y. Why?", ["honestly"]) == "F-|SQ"
    assert skeleton("Plain answer.", ["honestly"]) == "S"


def test_config_thresholds_load_and_block_v01_shape():
    assert not analyze_with_config(v01_like_corpus()).training_ready


# --- voice audit no longer rewards the catchphrase ----------------------------------------

def test_voice_audit_gives_no_personality_credit_for_overused_phrase():
    corpus = v01_like_corpus(200, 180)
    record = rec(1, "Honestly, that's a genuinely good pick — actually I love it.")
    opener_counter = build_opener_counter(corpus)
    before = score_conversation(record, extract_signals(record, []), opener_counter)
    overused = analyze_corpus(corpus).overused_phrases()
    sig = extract_signals(record, [], overused, {"honestly"})
    after = score_conversation(record, sig, opener_counter)
    assert "CATCHPHRASE_OVERUSE" in after.flags and "REPETITIVE_OPENING" in after.flags
    assert after.recommendation != "STRONG"
    assert after.scores.rupsaa_identity <= before.scores.rupsaa_identity


def test_voice_audit_unchanged_without_corpus_context():
    record = rec(1, "Honestly I'd skip that one.")
    sig = extract_signals(record, [])
    assert sig.overused_phrase_hits == [] and sig.has_personality_marker


# --- Bengali / Banglish quality ---------------------------------------------------------------

def test_detects_intraword_script_mix_and_repairs_suffixes():
    r = rec(1, "Chhoto ekta goal set korার try korecho?", language="banglish", user="ki korbo?")
    assert "INTRAWORD_SCRIPT_MIX" in analyze_record(r).codes
    assert repair_script_mix("korার") == "korar"
    assert repair_script_mix("hঠাৎ সিদ্ধান্ত") == "হঠাৎ সিদ্ধান্ত"
    assert repair_script_mix("shobসময়") == "shobসময়"  # ambiguous → left for a human


def test_detects_english_filler_in_bengali_and_script_inconsistency():
    r = rec(1, "এটা honestly অনেকের কাছেই খুব পরিচিত একটা অনুভূতি, মানুষের পাশে থাকা আর সত্যিকারের সংযোগ থাকা এক জিনিস না, "
               "তাই ekta kotha bolo actually।", language="bn", user="আমি একা বোধ করি")
    codes = analyze_record(r).codes
    assert {"ENGLISH_FILLER_IN_BENGALI", "FILLER_STACK", "SCRIPT_INCONSISTENT"} <= codes


def test_detects_foreign_script_but_not_bengali_danda():
    assert "FOREIGN_SCRIPT" in analyze_record(rec(1, "prothom kичhu mash", language="banglish")).codes
    assert "FOREIGN_SCRIPT" not in analyze_record(rec(2, "ভালো আছি।", language="bn")).codes


def test_counter_question_without_answer_flagged_but_answer_then_question_ok():
    bare = rec(1, "Keno jante chao?", language="banglish", user="tumi ki khaicho?")
    answered = rec(2, "Khaisi, tui ki abar bhule geli khete?", language="banglish", user="tui ki khaili ajke?")
    assert "QUESTION_UNANSWERED" in analyze_record(bare).codes
    assert "QUESTION_UNANSWERED" not in analyze_record(answered).codes


def test_filler_repair_keeps_meaningful_actually_in_english():
    assert propose_filler_repair("Honestly, that's a nuanced point.", "en") == "That's a nuanced point."
    assert propose_filler_repair("Start with what you actually want.", "en") == "Start with what you actually want."
    assert propose_filler_repair("Sheta honestly worth track kora actually - pattern ta clear hobe।", "banglish") == \
        "Sheta worth track kora - pattern ta clear hobe।"


def test_triage_classes():
    overused = {"honestly", "actually"}
    clean = rec(1, "Bhalo achi! Tumi kemon acho?", language="banglish", user="kemon acho?")
    tic = rec(2, "Honestly bhalo achi actually, tumi?", language="banglish", user="kemon acho?")
    human = rec(3, "Honestly bhalo achi.", language="banglish", source="human_authored", user="kemon acho?")
    broken = rec(4, "I'm fine, thanks for asking kичhu!", language="bn", user="তুমি কেমন আছো?")
    assert triage_record(clean, overused).classification == "KEEP"
    t = triage_record(tic, overused)
    assert t.classification == "REPAIR" and "honestly" not in t.proposed_messages[1]["content"].lower()
    assert triage_record(human, overused).classification == "HUMAN_REVIEW"  # never auto-repaired
    assert triage_record(broken, overused).classification == "REJECT"
    assert tic.messages[1]["content"].startswith("Honestly")  # proposal never mutates the record


# --- export gate --------------------------------------------------------------------------------

def test_export_refuses_catchphrase_saturated_corpus(tmp_path):
    base = tmp_path / "production"
    store = DatasetStore(base)
    for r in v01_like_corpus(n=60, honestly=55):
        r.category = "casual_friendly"
        store.save_new(r)
    out = tmp_path / "exports"
    cmd = [sys.executable, str(PROJECT_ROOT / "scripts/dataset_export.py"), "--base-dir", str(base), "--output-dir", str(out)]
    refused = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert refused.returncode == 1 and "REFUSING" in refused.stdout
    assert not (out / "train.jsonl").exists()
    allowed = subprocess.run(cmd + ["--allow-diversity-failures"], capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    report = json.loads((out / "diversity_report.json").read_text(encoding="utf-8"))
    assert report["training_ready"] is False


# --- V0.1 baseline stays intact / compatible -------------------------------------------------------

V01_ADAPTER = PROJECT_ROOT / "adapters/rupsaa-v0.1"


@pytest.mark.skipif(not (V01_ADAPTER / "adapter_config.json").exists(), reason="V0.1 adapter not present")
def test_v01_adapter_config_compatible_with_loader_config():
    from rupsaa.config import load_model_config

    cfg = json.loads((V01_ADAPTER / "adapter_config.json").read_text(encoding="utf-8"))
    model_cfg = load_model_config()
    assert cfg["base_model_name_or_path"] == model_cfg["base_model_id"]
    assert set(cfg["target_modules"]) == set(model_cfg["lora_target_modules"])
    assert cfg["peft_type"] == "LORA" and (V01_ADAPTER / "adapter_model.safetensors").exists()


@pytest.mark.skipif(not (PROJECT_ROOT / "data/production/exports/rupsaa_v0.1/train.jsonl").exists(),
                    reason="V0.1 export not present")
def test_frozen_v01_export_unchanged_counts():
    counts = Counter()
    for split in ("train", "validation", "test"):
        counts[split] = sum(1 for _ in open(PROJECT_ROOT / f"data/production/exports/rupsaa_v0.1/{split}.jsonl", encoding="utf-8"))
    assert counts == {"train": 772, "validation": 43, "test": 43}
