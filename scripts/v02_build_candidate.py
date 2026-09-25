#!/usr/bin/env python3
"""Assemble the V0.2 CANDIDATE dataset from decisions made so far.

Never touches data/production/{approved,drafts,rejected} (the V0.1 store),
the frozen V0.1 snapshot/export, or quality_status on any record. Writes
only to data/production/v0.2_workspace/ and reports/rupsaa_v0.2_preparation/.

Included, per record's V0.2 triage classification
(reports/rupsaa_v0.2_preparation/triage.jsonl):
  KEEP           -> original messages, unchanged
  HUMAN_REVIEW   -> only if a decision was recorded (v02_repair_review.py):
                    accept -> proposed messages
                    edit   -> proposed messages with the reviewer's edits applied
                    keep-original -> original messages
                    reject -> excluded
  REPAIR         -> AUTO_ACCEPT_REPAIR (scripts/v02_repair_automate.py): proposed
                    messages, included directly — filler-subtraction-only,
                    with no fact/overclaim/template/length risk signal.
                    Otherwise treated exactly like HUMAN_REVIEW above: only
                    included if a decision was recorded.
  REJECT         -> excluded

Plus every new draft record with notes containing "V0.2 new-coverage batch"
(the curated new-coverage examples — casual variety, language switching,
follow-ups, memory, terminology, typo tolerance), which aren't in the
triage at all since they didn't exist during the original diagnosis run.

This is a CANDIDATE only: not approved, not exported, not training-ready
until the REPAIR queue is also reviewed and the whole set passes
scripts/dataset_audit.py.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import Counter  # noqa: E402

from rupsaa.dataset.config import PROJECT_ROOT, default_base_dir, load_dataset_config  # noqa: E402
from rupsaa.dataset.diversity import analyze_with_config, collect_replies, opening, tokenize  # noqa: E402
from rupsaa.dataset.language_quality import analyze_record  # noqa: E402
from rupsaa.dataset.repetition import find_watchlist_overuse  # noqa: E402
from rupsaa.dataset.schema import ConversationRecord  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402

TRIAGE = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_preparation/triage.jsonl"
DECISIONS = PROJECT_ROOT / "data/production/v0.2_workspace/review_decisions.jsonl"
REPAIR_AUTOMATION = PROJECT_ROOT / "data/production/v0.2_workspace/repair_automation.jsonl"
KEEP_REWRITES = PROJECT_ROOT / "data/production/v0.2_workspace/keep_rewrites.jsonl"
OUT_DIR = PROJECT_ROOT / "data/production/v0.2_workspace"
REPORT_DIR = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_preparation"
NEW_BATCH_MARKERS = ("V0.2 new-coverage batch", "V0.2 terminology-grounded batch")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def apply_edits(messages: list[dict], edits: dict[str, str]) -> list[dict]:
    a_indices = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    out = [dict(m) for m in messages]
    for reply_no_str, text in edits.items():
        idx = a_indices[int(reply_no_str) - 1]
        out[idx] = {**out[idx], "content": text}
    return out


def apply_decision(record: ConversationRecord, t: dict, d: dict) -> ConversationRecord | None:
    """Applies one HUMAN_REVIEW-style decision (accept/edit/keep-original/reject)
    against a triage entry's proposal. Returns None for reject."""
    if d["action"] == "reject":
        return None
    if d["action"] == "keep-original":
        messages = record.messages
    elif d["action"] == "accept":
        messages = t["proposed_messages"]
    elif d["action"] == "edit":
        base = t["proposed_messages"] or record.messages
        messages = apply_edits(base, d["edits"])
    else:
        raise ValueError(f"unknown decision action {d['action']!r} for {record.id}")
    return ConversationRecord(**{**record.to_dict(), "messages": messages})


def main() -> None:
    store = DatasetStore(default_base_dir())
    triage = {t["record_id"]: t for t in load_jsonl(TRIAGE)}
    decisions = {}
    if DECISIONS.exists():
        for d in load_jsonl(DECISIONS):
            decisions[d["record_id"]] = d  # latest wins
    automation = {}
    if REPAIR_AUTOMATION.exists():
        for a in load_jsonl(REPAIR_AUTOMATION):
            automation[a["record_id"]] = a
    keep_rewrites = {}
    if KEEP_REWRITES.exists():
        for k in load_jsonl(KEEP_REWRITES):
            keep_rewrites[k["record_id"]] = k

    included: list[ConversationRecord] = []
    excluded_reject = excluded_undecided_human_review = 0
    excluded_repair_auto_accept = excluded_repair_needs_review_undecided = 0
    new_batch = 0
    decision_counts: dict[str, int] = {}

    for loc in store.list_all():
        record = loc.record
        t = triage.get(record.id)
        if t is None:
            if any(marker in (record.notes or "") for marker in NEW_BATCH_MARKERS):
                included.append(record)
                new_batch += 1
                decision_counts["NEW_COVERAGE"] = decision_counts.get("NEW_COVERAGE", 0) + 1
            continue

        cls = t["classification"]
        if cls == "KEEP":
            k = keep_rewrites.get(record.id)
            if k is not None:
                record = ConversationRecord(**{**record.to_dict(), "messages": apply_edits(record.messages, k["edits"])})
                decision_counts["KEEP_REWRITTEN"] = decision_counts.get("KEEP_REWRITTEN", 0) + 1
            else:
                decision_counts["KEEP"] = decision_counts.get("KEEP", 0) + 1
            included.append(record)
        elif cls == "REJECT":
            excluded_reject += 1
        elif cls == "REPAIR":
            conf = automation.get(record.id, {}).get("confidence")
            if conf == "AUTO_ACCEPT_REPAIR":
                included.append(ConversationRecord(**{**record.to_dict(), "messages": t["proposed_messages"]}))
                decision_counts["AUTO_ACCEPT_REPAIR"] = decision_counts.get("AUTO_ACCEPT_REPAIR", 0) + 1
            else:
                # Not yet auto-classified, or automation flagged it HUMAN_REVIEW:
                # treat exactly like the HUMAN_REVIEW pipeline below.
                d = decisions.get(record.id)
                if d is None:
                    excluded_repair_needs_review_undecided += 1
                    continue
                out = apply_decision(record, t, d)
                if out is None:
                    excluded_reject += 1
                    continue
                included.append(out)
                decision_counts[f"REPAIR_HUMAN_REVIEWED_{d['action']}"] = \
                    decision_counts.get(f"REPAIR_HUMAN_REVIEWED_{d['action']}", 0) + 1
        elif cls == "HUMAN_REVIEW":
            d = decisions.get(record.id)
            if d is None:
                excluded_undecided_human_review += 1
                continue
            out = apply_decision(record, t, d)
            if out is None:
                excluded_reject += 1
                continue
            included.append(out)
            decision_counts[f"HUMAN_REVIEWED_{d['action']}"] = decision_counts.get(f"HUMAN_REVIEWED_{d['action']}", 0) + 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candidate_path = OUT_DIR / "candidate_set.jsonl"
    with open(candidate_path, "w", encoding="utf-8") as f:
        for r in included:
            f.write(json.dumps({"id": r.id, **r.strip_for_training()}, ensure_ascii=False) + "\n")

    # Re-analyze the ACTUAL candidate content (post-edit) for language-quality
    # issues and catchphrase/diversity concentration — not the pre-repair
    # triage numbers, which describe the old corpus, not this one.
    lq_issue_records = 0
    lq_issue_counts: dict[str, int] = {}
    for r in included:
        res = analyze_record(r)
        if res.issues:
            lq_issue_records += 1
        for issue in res.issues:
            lq_issue_counts[issue.code] = lq_issue_counts.get(issue.code, 0) + 1

    cfg = load_dataset_config()
    watchlist = cfg["style_watchlist"]
    all_watchlist_terms = watchlist["pet_names"] + watchlist["filler_words"] + watchlist["emojis"]
    overuse = find_watchlist_overuse(included, all_watchlist_terms, cfg["thresholds"]["max_phrase_frequency_ratio"])
    diversity = analyze_with_config(included)

    by_lang: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for r in included:
        by_lang[r.language] = by_lang.get(r.language, 0) + 1
        by_source[r.source_type] = by_source.get(r.source_type, 0) + 1

    summary = {
        "total_candidate_records": len(included),
        "by_language": by_lang,
        "by_source_type": by_source,
        "new_coverage_batch_records": new_batch,
        "by_decision": decision_counts,
        "excluded": {
            "REPAIR_needs_review_undecided": excluded_repair_needs_review_undecided,
            "REJECT": excluded_reject,
            "HUMAN_REVIEW_undecided": excluded_undecided_human_review,
        },
        "language_quality": {
            "records_with_any_issue": lq_issue_records,
            "issue_counts": lq_issue_counts,
        },
        "style_watchlist_overuse": [
            {"phrase": o.phrase, "message_count": o.message_count,
             "total_assistant_messages": o.total_assistant_messages, "ratio": round(o.ratio, 4)}
            for o in overuse
        ],
        "diversity_gate": {
            "training_ready": diversity.training_ready,
            "block_count": len(diversity.blocking),
            "warn_count": len(diversity.warnings),
            "issues": [
                {"severity": i.severity, "kind": i.kind, "scope": i.scope, "key": i.key,
                 "count": i.count, "total": i.total, "ratio": i.ratio, "threshold": i.threshold}
                for i in diversity.issues
            ],
        },
    }

    # --- Full audit: catchphrase frequencies, top-N openings/n-grams,
    # response-length distribution, source breakdown. All computed on the
    # ACTUAL candidate content (post-repair/post-edit).
    replies = collect_replies(included)
    texts = [r.text for r in replies]
    n_replies = len(texts)

    catchphrase_freq = {}
    for phrase in ("honestly", "actually", "fair call", "fair enough", "heyy", "bindaas", "baby", "babe"):
        pat = re.compile(r"(?<![A-Za-z])" + re.escape(phrase) + r"(?![A-Za-z])", re.IGNORECASE)
        count = sum(1 for t in texts if pat.search(t))
        catchphrase_freq[phrase] = {"count": count, "ratio": round(count / n_replies, 4) if n_replies else 0.0}
    emoji_re = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
    emoji_count = sum(1 for t in texts if emoji_re.search(t))
    catchphrase_freq["emoji"] = {"count": emoji_count, "ratio": round(emoji_count / n_replies, 4) if n_replies else 0.0}

    def top_ngrams(n: int, limit: int = 25) -> list[tuple[str, int]]:
        counter: Counter[str] = Counter()
        for t in texts:
            toks = tokenize(t)
            for i in range(len(toks) - n + 1):
                counter[" ".join(toks[i:i + n])] += 1
        return counter.most_common(limit)

    top_openings = Counter(opening(t, 1) for t in texts if t.strip()).most_common(25)

    lengths = sorted(len(t) for t in texts)

    def pct(p: float) -> int:
        if not lengths:
            return 0
        idx = min(len(lengths) - 1, int(p * len(lengths)))
        return lengths[idx]

    by_source_lang: dict[str, dict[str, int]] = {}
    for r in included:
        by_source_lang.setdefault(r.source_type, {}).setdefault(r.language, 0)
        by_source_lang[r.source_type][r.language] += 1

    audit = {
        "total_conversations": len(included),
        "total_assistant_replies": n_replies,
        "by_language": by_lang,
        "by_source_type": by_source,
        "by_source_and_language": by_source_lang,
        "catchphrase_frequency": catchphrase_freq,
        "top_25_openings": top_openings,
        "top_25_bigrams": top_ngrams(2),
        "top_25_trigrams": top_ngrams(3),
        "top_25_4grams": top_ngrams(4),
        "response_length_chars": {
            "min": lengths[0] if lengths else 0, "p25": pct(0.25), "median": pct(0.5),
            "p75": pct(0.75), "p90": pct(0.9), "max": lengths[-1] if lengths else 0,
        },
        "mixed_script_corruption_records": lq_issue_counts.get("INTRAWORD_SCRIPT_MIX", 0)
        + lq_issue_counts.get("SCRIPT_INCONSISTENT", 0) + lq_issue_counts.get("FOREIGN_SCRIPT", 0),
        "diversity_gate": summary["diversity_gate"],
    }
    audit_path = REPORT_DIR / "candidate_full_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = REPORT_DIR / "candidate_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"candidate records: {len(included)} (new-coverage batch: {new_batch})")
    print(f"by_language: {by_lang}")
    print(f"by_decision: {decision_counts}")
    print(f"excluded: REPAIR needing review (undecided)={excluded_repair_needs_review_undecided}  "
          f"REJECT={excluded_reject}  HUMAN_REVIEW undecided={excluded_undecided_human_review}")
    print(f"language-quality: {lq_issue_records} record(s) with a residual issue: {lq_issue_counts}")
    print(f"diversity gate: training_ready={diversity.training_ready} "
          f"block={summary['diversity_gate']['block_count']} warn={summary['diversity_gate']['warn_count']}")
    for i in diversity.issues:
        if i.severity == "block":
            print(f"    {i.describe()}")
    def _display(path: Path) -> str:
        try:
            return str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(path)

    print(f"\nwrote {_display(candidate_path)}")
    print(f"wrote {_display(summary_path)}")
    print(f"wrote {_display(audit_path)}")


if __name__ == "__main__":
    main()
