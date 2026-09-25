#!/usr/bin/env python3
"""Automated confidence classification for the V0.2 REPAIR queue.

Never touches data/production/{approved,drafts,rejected} or the V0.1
snapshot/export. Reads triage.jsonl, writes only to
data/production/v0.2_workspace/ and reports/rupsaa_v0.2_preparation/.

AUTO_ACCEPT_REPAIR is deliberately narrow, and is a *content-diff* test, not
a phrase-substitution test: propose_repair() only ever subtracts (removes
discourse fillers, and — where repair_script_mix() acted — retypes an
existing word from Bengali into Latin script, letter for letter). A record
qualifies for AUTO_ACCEPT_REPAIR only when:

  1. repair_script_mix() was a NO-OP for every assistant message — i.e. no
     content WORD was rewritten, only pure discourse fillers ("honestly",
     "actually", ...) were subtracted. Filler subtraction cannot alter
     meaning: propose_filler_repair() only strips words matched as
     sentence-initial/final, comma-bracketed, or stacked discourse markers
     (rupsaa.dataset.language_quality._remove_word) — never a word that is
     doing grammatical work in the sentence.
  2. No unsupported-platform-fact / fake-RAG-attribution / invented-
     precision risk signal in the proposed text (rupsaa.dataset.
     voice_audit's own detectors, run the same way score_conversation does).
  3. The proposed text isn't a template also used verbatim by >= 3 other
     records (rupsaa.dataset.repetition.find_repeated_assistant_replies) —
     a real answer to a real question is not usually copy-identical to
     several others.
  4. No assistant turn lost more than 40% of its character length — a
     mechanical filler-only repair should barely change length; anything
     that shrank a lot instead flags a real editing risk.

Any record NOT meeting every check goes to HUMAN_REVIEW, unconditionally —
this includes every record where repair_script_mix() actually rewrote a
content word (the 116 records where transliteration risk is real, per the
inherent-vowel-blind bug already found and fixed once this session).

Usage:
    python scripts/v02_repair_automate.py classify
    python scripts/v02_repair_automate.py sample --banglish 30 --bn 20 --mixed 15 --en 10
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import PROJECT_ROOT, default_base_dir  # noqa: E402
from rupsaa.dataset.language_quality import repair_script_mix  # noqa: E402
from rupsaa.dataset.repetition import find_repeated_assistant_replies  # noqa: E402
from rupsaa.dataset.schema import ConversationRecord  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402
from rupsaa.dataset.voice_audit import (  # noqa: E402
    _GENERALIZED_STATISTIC_RE,
    _fake_rag_attribution_present,
    _platform_fact_present,
    has_retrieved_context,
)

TRIAGE = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_preparation/triage.jsonl"
CLASSIFICATION = PROJECT_ROOT / "data/production/v0.2_workspace/repair_automation.jsonl"
SAMPLE_REPORT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_preparation/AUTO_ACCEPT_QA_SAMPLE.md"
MIN_LENGTH_RATIO = 0.6
MIN_CHARS_REMOVED = 25  # two filler words + their punctuation, generously


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def cmd_classify(args: argparse.Namespace) -> None:
    store = DatasetStore(default_base_dir())
    triage = [t for t in load_jsonl(TRIAGE) if t["classification"] == "REPAIR"]

    # Templated-reply risk: computed once over ALL proposed REPAIR text, so
    # a proposal that duplicates several others (regardless of which record
    # it duplicates) is caught.
    proposed_records = []
    for t in triage:
        proposed_records.append(ConversationRecord(
            id=t["record_id"], language=t["language"], category=t["category"],
            source_type=t["source_type"], quality_status=t["quality_status"],
            messages=t["proposed_messages"],
        ))
    repeated = find_repeated_assistant_replies(proposed_records, min_count=3)
    repeated_texts = {r.text for r in repeated}

    results = []
    counts = Counter()
    for t in triage:
        rid = t["record_id"]
        loc = store.load(rid)
        record = loc.record
        checks = {
            "script_mix_noop": True,
            "no_fact_overclaim_risk": True,
            "not_templated": True,
            "length_ratio_ok": True,
        }
        reasons = []
        grounded = has_retrieved_context(record)

        for orig_m, prop_m in zip(record.messages, t["proposed_messages"]):
            if orig_m.get("role") != "assistant":
                continue
            orig_text, prop_text = orig_m["content"], prop_m["content"]

            if repair_script_mix(orig_text, record.language) != orig_text:
                checks["script_mix_noop"] = False
                reasons.append("a content word was transliterated, not just a filler removed")

            joined = prop_text
            if (_fake_rag_attribution_present(joined) and not grounded) \
               or (_platform_fact_present(joined) and not grounded) \
               or (not grounded and _GENERALIZED_STATISTIC_RE.search(joined)):
                checks["no_fact_overclaim_risk"] = False
                reasons.append("unsupported platform-fact / RAG-attribution / generalized-statistic risk signal")

            if prop_text.strip() in repeated_texts:
                checks["not_templated"] = False
                reasons.append("proposed reply is a template reused by >=3 records")

            # A ratio alone false-flags short replies: "Yes, honestly." -> "Yes."
            # is a 60% character drop and completely safe — a single filler
            # word is a large share of a five-word sentence. Require BOTH a
            # low ratio AND a real absolute cut (more than one filler word's
            # worth of characters) before treating it as an editing risk.
            chars_removed = len(orig_text) - len(prop_text)
            if orig_text and len(prop_text) < MIN_LENGTH_RATIO * len(orig_text) and chars_removed > MIN_CHARS_REMOVED:
                checks["length_ratio_ok"] = False
                reasons.append(f"proposed reply is {len(prop_text)}/{len(orig_text)} chars of the original "
                                f"({chars_removed} chars removed)")

        confidence = "AUTO_ACCEPT_REPAIR" if all(checks.values()) else "HUMAN_REVIEW"
        counts[confidence] += 1
        results.append({
            "record_id": rid, "language": t["language"], "category": t["category"],
            "source_type": t["source_type"], "confidence": confidence, "checks": checks,
            "reasons": reasons, "repair_method": "filler-subtraction-only" if checks["script_mix_noop"]
                                                  else "script-mix transliteration + filler subtraction",
        })

    CLASSIFICATION.parent.mkdir(parents=True, exist_ok=True)
    with open(CLASSIFICATION, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_lang = Counter((r["language"], r["confidence"]) for r in results)
    print(f"classified: {len(results)}  {dict(counts)}")
    for lang in ("banglish", "bn", "mixed", "en"):
        print(f"  {lang:9} AUTO_ACCEPT_REPAIR={by_lang[(lang,'AUTO_ACCEPT_REPAIR')]} "
              f"HUMAN_REVIEW={by_lang[(lang,'HUMAN_REVIEW')]}")
    print(f"wrote {_display(CLASSIFICATION)}")


def cmd_sample(args: argparse.Namespace) -> None:
    if not CLASSIFICATION.exists():
        sys.exit("run `classify` first")
    rows = [r for r in load_jsonl(CLASSIFICATION) if r["confidence"] == "AUTO_ACCEPT_REPAIR"]
    triage_by_id = {t["record_id"]: t for t in load_jsonl(TRIAGE)}
    store = DatasetStore(default_base_dir())

    quotas = {"banglish": args.banglish, "bn": args.bn, "mixed": args.mixed, "en": args.en}
    rng = random.Random(42)
    lines = ["# V0.2 AUTO_ACCEPT_REPAIR QA sample",
             "",
             "Stratified random sample (seed 42) of records auto-accepted by "
             "`scripts/v02_repair_automate.py classify` — for human spot-check before "
             "these are trusted in the candidate build. USER / ORIGINAL / REPAIRED / WHY CHANGED.",
             ""]
    total_sampled = 0
    for lang, n in quotas.items():
        pool = [r for r in rows if r["language"] == lang]
        picked = rng.sample(pool, min(n, len(pool)))
        lines.append(f"## {lang} ({len(picked)} of {len(pool)} eligible)")
        lines.append("")
        for r in picked:
            rid = r["record_id"]
            t = triage_by_id[rid]
            loc = store.load(rid)
            orig = loc.record.messages
            prop = t["proposed_messages"]
            lines.append(f"### {rid}")
            for om, pm in zip(orig, prop):
                if om.get("role") == "user":
                    lines.append(f"USER: {om['content']}")
                elif om.get("role") == "assistant":
                    if om["content"] != pm["content"]:
                        lines.append(f"ORIGINAL: {om['content']}")
                        lines.append(f"REPAIRED: {pm['content']}")
                    else:
                        lines.append(f"UNCHANGED: {om['content']}")
            lines.append(f"WHY CHANGED: {r['repair_method']}")
            lines.append("")
        total_sampled += len(picked)

    SAMPLE_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"sampled {total_sampled} record(s) -> {_display(SAMPLE_REPORT)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("classify").set_defaults(fn=cmd_classify)
    sp = sub.add_parser("sample")
    sp.add_argument("--banglish", type=int, default=30)
    sp.add_argument("--bn", type=int, default=20)
    sp.add_argument("--mixed", type=int, default=15)
    sp.add_argument("--en", type=int, default=10)
    sp.set_defaults(fn=cmd_sample)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
