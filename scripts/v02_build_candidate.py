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
  REPAIR         -> NOT included yet. The mechanical proposal has zero
                    residual language-quality issues, but nobody has read
                    it for semantic correctness (see v02_repair_review.py
                    next --class REPAIR) — including it here would be
                    exactly the "fabricate a repair to preserve dataset
                    size" the V0.2 spec says not to do.
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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import PROJECT_ROOT, default_base_dir, load_dataset_config  # noqa: E402
from rupsaa.dataset.diversity import analyze_with_config  # noqa: E402
from rupsaa.dataset.language_quality import analyze_record  # noqa: E402
from rupsaa.dataset.repetition import find_watchlist_overuse  # noqa: E402
from rupsaa.dataset.schema import ConversationRecord  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402

TRIAGE = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_preparation/triage.jsonl"
DECISIONS = PROJECT_ROOT / "data/production/v0.2_workspace/review_decisions.jsonl"
OUT_DIR = PROJECT_ROOT / "data/production/v0.2_workspace"
REPORT_DIR = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_preparation"
NEW_BATCH_MARKER = "V0.2 new-coverage batch"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def apply_edits(messages: list[dict], edits: dict[str, str]) -> list[dict]:
    a_indices = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    out = [dict(m) for m in messages]
    for reply_no_str, text in edits.items():
        idx = a_indices[int(reply_no_str) - 1]
        out[idx] = {**out[idx], "content": text}
    return out


def main() -> None:
    store = DatasetStore(default_base_dir())
    triage = {t["record_id"]: t for t in load_jsonl(TRIAGE)}
    decisions = {}
    if DECISIONS.exists():
        for d in load_jsonl(DECISIONS):
            decisions[d["record_id"]] = d  # latest wins

    included: list[ConversationRecord] = []
    excluded_reject = excluded_undecided_human_review = excluded_repair = 0
    new_batch = 0

    for loc in store.list_all():
        record = loc.record
        t = triage.get(record.id)
        if t is None:
            if NEW_BATCH_MARKER in (record.notes or ""):
                included.append(record)
                new_batch += 1
            continue

        cls = t["classification"]
        if cls == "KEEP":
            included.append(record)
        elif cls == "REPAIR":
            excluded_repair += 1
        elif cls == "REJECT":
            excluded_reject += 1
        elif cls == "HUMAN_REVIEW":
            d = decisions.get(record.id)
            if d is None:
                excluded_undecided_human_review += 1
                continue
            if d["action"] == "reject":
                excluded_reject += 1
                continue
            if d["action"] == "keep-original":
                messages = record.messages
            elif d["action"] == "accept":
                messages = t["proposed_messages"]
            elif d["action"] == "edit":
                base = t["proposed_messages"] or record.messages
                messages = apply_edits(base, d["edits"])
            else:
                raise ValueError(f"unknown decision action {d['action']!r} for {record.id}")
            included.append(ConversationRecord(**{**record.to_dict(), "messages": messages}))

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
        "excluded": {
            "REPAIR_pending_review": excluded_repair,
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
    summary_path = REPORT_DIR / "candidate_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"candidate records: {len(included)} (new-coverage batch: {new_batch})")
    print(f"by_language: {by_lang}")
    print(f"excluded: REPAIR pending={excluded_repair}  REJECT={excluded_reject}  "
          f"HUMAN_REVIEW undecided={excluded_undecided_human_review}")
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


if __name__ == "__main__":
    main()
