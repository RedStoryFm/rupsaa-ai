#!/usr/bin/env python3
"""Audit the production dataset: schema, Unicode, duplicates, near-duplicates,
repeated replies, and style-watchlist overuse.

Usage:
    python scripts/dataset_audit.py                        # audit draft + approved
    python scripts/dataset_audit.py --status all
    python scripts/dataset_audit.py --category relationship_dating
    python scripts/dataset_audit.py --skip-near-duplicates  # for very large datasets

Writes a Markdown + JSON report to data/production/reports/. Schema/Unicode
errors are hard failures (non-zero exit); duplicates, near-duplicates, and
style overuse are warnings for a human to act on — never auto-rejected.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import default_base_dir, load_dataset_config  # noqa: E402
from rupsaa.dataset.dedup import find_exact_duplicates, find_near_duplicates  # noqa: E402
from rupsaa.dataset.repetition import find_emoji_overuse, find_repeated_assistant_replies, find_watchlist_overuse  # noqa: E402
from rupsaa.dataset.diversity import analyze_with_config  # noqa: E402
from rupsaa.dataset.schema import validate_record  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", default="draft,approved", help="Comma-separated statuses to audit, or 'all'.")
    parser.add_argument("--category", default=None)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--skip-near-duplicates", action="store_true")
    parser.add_argument("--allow-slow-near-dup", action="store_true", help="Proceed with near-dup scan even above the configured record-count cap.")
    parser.add_argument("--allow-diversity-failures", action="store_true",
                        help="Report corpus-diversity BLOCK issues without failing (diagnosis runs only; never for a training candidate).")
    args = parser.parse_args()

    cfg = load_dataset_config()
    base_dir = Path(args.base_dir) if args.base_dir else default_base_dir()
    store = DatasetStore(base_dir)

    statuses = None if args.status == "all" else set(args.status.split(","))
    locations = store.list_all(statuses)
    if args.category:
        locations = [loc for loc in locations if loc.record.category == args.category]
    records = [loc.record for loc in locations]

    print(f"Auditing {len(records)} record(s) (status filter: {args.status}, category filter: {args.category or 'none'})")

    report: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "status_filter": args.status,
        "category_filter": args.category,
    }

    # 1. Schema / Unicode validation (hard errors)
    schema_errors = {}
    for r in records:
        errs = validate_record(r)
        if errs:
            schema_errors[r.id] = errs
    report["schema_errors"] = schema_errors

    # 2. Exact duplicates
    exact_dupes = find_exact_duplicates(records)
    report["exact_duplicates"] = [{"duplicate_id": a, "original_id": b} for a, b in exact_dupes]

    # 3. Near duplicates
    near_dupes_cfg = cfg["near_duplicate"]
    near_dupes: list[dict] = []
    near_dup_skipped_reason = None
    if args.skip_near_duplicates:
        near_dup_skipped_reason = "skipped via --skip-near-duplicates"
    else:
        max_records = near_dupes_cfg["max_records_for_full_scan"]
        if len(records) > max_records and not args.allow_slow_near_dup:
            near_dup_skipped_reason = (
                f"{len(records)} records exceeds max_records_for_full_scan={max_records}; "
                "narrow with --category or pass --allow-slow-near-dup"
            )
        else:
            pairs = find_near_duplicates(
                records,
                ngram_size=near_dupes_cfg["ngram_size"],
                threshold=near_dupes_cfg["similarity_threshold"],
                max_records=max(max_records, len(records) if args.allow_slow_near_dup else max_records),
            )
            near_dupes = [asdict(p) for p in pairs]
    report["near_duplicates"] = near_dupes
    report["near_duplicates_skipped_reason"] = near_dup_skipped_reason

    # 4. Repeated assistant replies
    thresholds = cfg["thresholds"]
    repeated = find_repeated_assistant_replies(records, min_count=thresholds["repeated_reply_min_count"])
    report["repeated_assistant_replies"] = [asdict(r) for r in repeated]

    # 5. Style watchlist overuse
    watchlist = cfg["style_watchlist"]
    all_watchlist_terms = watchlist["pet_names"] + watchlist["filler_words"] + watchlist["emojis"]
    overuse = find_watchlist_overuse(records, all_watchlist_terms, thresholds["max_phrase_frequency_ratio"])
    report["style_watchlist_overuse"] = [asdict(u) for u in overuse]

    # 6. Emoji overuse
    emoji_report = find_emoji_overuse(records, thresholds["max_emojis_per_message"], thresholds["max_emoji_message_ratio"])
    report["emoji_overuse"] = asdict(emoji_report)

    # 7. Corpus-level diversity / catchphrase concentration (training gate).
    diversity = analyze_with_config(records)
    report["diversity"] = diversity.to_dict()

    # --- Print summary ---
    print(f"\nSchema/Unicode errors: {len(schema_errors)}")
    for rid, errs in list(schema_errors.items())[:10]:
        print(f"  - {rid}: {errs}")

    print(f"Exact duplicates: {len(exact_dupes)}")
    print(f"Near duplicates: {len(near_dupes)}" + (f" ({near_dup_skipped_reason})" if near_dup_skipped_reason else ""))
    print(f"Repeated assistant replies (>= {thresholds['repeated_reply_min_count']}x): {len(repeated)}")
    print(f"Style watchlist overuse (> {thresholds['max_phrase_frequency_ratio']:.0%} of assistant messages): {len(overuse)}")
    for u in overuse:
        print(f"  - '{u.phrase}': {u.message_count}/{u.total_assistant_messages} messages ({u.ratio:.1%})")
    print(f"Emoji-containing assistant messages: {emoji_report.emoji_message_ratio:.1%} "
          f"(threshold {thresholds['max_emoji_message_ratio']:.0%}, exceeded={emoji_report.exceeds_message_ratio_threshold})")
    print(f"Messages with > {thresholds['max_emojis_per_message']} emoji: {len(emoji_report.messages_with_excess_emoji)}")
    print(f"Corpus diversity: {len(diversity.blocking)} BLOCK / {len(diversity.warnings)} WARN "
          f"(training_ready={diversity.training_ready})")
    for issue in diversity.issues[:15]:
        print(f"  - {issue.describe()}")

    # --- Write report files ---
    store.reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = store.reports_dir / f"audit_{timestamp}.json"
    md_path = store.reports_dir / f"audit_{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [f"# Rupsaa Dataset Audit — {report['timestamp']}", ""]
    md_lines.append(f"Records audited: {len(records)} (status={args.status}, category={args.category or 'all'})")
    md_lines.append(f"\n## Schema/Unicode errors: {len(schema_errors)}")
    for rid, errs in schema_errors.items():
        md_lines.append(f"- **{rid}**: {'; '.join(errs)}")
    md_lines.append(f"\n## Exact duplicates: {len(exact_dupes)}")
    for a, b in exact_dupes:
        md_lines.append(f"- {a} duplicates {b}")
    md_lines.append(f"\n## Near duplicates: {len(near_dupes)}")
    if near_dup_skipped_reason:
        md_lines.append(f"(skipped: {near_dup_skipped_reason})")
    for p in near_dupes:
        md_lines.append(f"- {p['id_a']} ~ {p['id_b']} (similarity {p['similarity']})")
    md_lines.append(f"\n## Repeated assistant replies: {len(repeated)}")
    for r in repeated:
        md_lines.append(f"- \"{r.text}...\" used {r.count}x in {r.record_ids}")
    md_lines.append(f"\n## Style watchlist overuse: {len(overuse)}")
    for u in overuse:
        md_lines.append(f"- '{u.phrase}': {u.message_count}/{u.total_assistant_messages} ({u.ratio:.1%})")
    md_lines.append(f"\n## Corpus diversity: {len(diversity.blocking)} BLOCK / {len(diversity.warnings)} WARN "
                    f"(training_ready={diversity.training_ready})")
    for issue in diversity.issues:
        md_lines.append(f"- {issue.describe()}")
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\nReport written to:\n  {json_path}\n  {md_path}")

    if schema_errors:
        print("\nAudit FAILED — schema/Unicode errors must be fixed before approval.")
        sys.exit(1)
    if diversity.blocking and not args.allow_diversity_failures:
        print("\nAudit FAILED — corpus diversity BLOCK issues: this corpus is NOT training-ready "
              "(a catchphrase/opening/template dominates the assistant voice). See rupsaa/dataset/diversity.py.")
        sys.exit(1)
    print("\nAudit passed (no hard errors). Review warnings above before approving.")


if __name__ == "__main__":
    main()
