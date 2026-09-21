#!/usr/bin/env python3
"""Generate distribution/coverage reports for the production dataset:
language, category, tone, conversation length, source type, and
token-length distributions.

Usage:
    python scripts/dataset_report.py                  # approved only (default)
    python scripts/dataset_report.py --status all
    python scripts/dataset_report.py --status draft

Writes a Markdown + JSON report to data/production/reports/. This is a
descriptive/coverage report, not a pass/fail gate — use
scripts/dataset_audit.py for validation and duplicate/repetition checks.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import default_base_dir  # noqa: E402
from rupsaa.dataset.stats import build_stats, render_markdown_report  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402
from rupsaa.dataset.taxonomy import CATEGORIES  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", default="approved", help="Comma-separated statuses, or 'all'.")
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args()

    base_dir = Path(args.base_dir) if args.base_dir else default_base_dir()
    store = DatasetStore(base_dir)

    statuses = None if args.status == "all" else set(args.status.split(","))
    locations = store.list_all(statuses)
    records = [loc.record for loc in locations]

    stats = build_stats(records)

    print(f"Dataset report (status filter: {args.status})")
    print(f"Total conversations: {stats.total}")
    print(f"Total messages: {stats.message_count}")
    print(f"Approx. token count: {stats.approx_token_total}")
    print(f"\nBy category:")
    for cat, count in stats.by_category.most_common():
        print(f"  {cat}: {count}")

    missing_categories = set(CATEGORIES) - set(stats.by_category)
    if missing_categories:
        print(f"\nCategories with ZERO approved examples so far ({len(missing_categories)}):")
        for cat in sorted(missing_categories):
            print(f"  - {cat}")

    print(f"\nBy language: {dict(stats.by_language)}")
    print(f"By tone: {dict(stats.by_tone)}")
    print(f"By conversation_length: {dict(stats.by_conversation_length)}")
    print(f"By source_type: {dict(stats.by_source_type)}")

    store.reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    md_path = store.reports_dir / f"stats_{timestamp}.md"
    json_path = store.reports_dir / f"stats_{timestamp}.json"

    md_path.write_text(render_markdown_report(f"Rupsaa Dataset Report (status={args.status})", stats), encoding="utf-8")
    json_report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status_filter": args.status,
        "total": stats.total,
        "message_count": stats.message_count,
        "approx_token_total": stats.approx_token_total,
        "by_status": dict(stats.by_status),
        "by_category": dict(stats.by_category),
        "by_subcategory": dict(stats.by_subcategory),
        "by_language": dict(stats.by_language),
        "by_tone": dict(stats.by_tone),
        "by_conversation_length": dict(stats.by_conversation_length),
        "by_source_type": dict(stats.by_source_type),
        "missing_categories": sorted(missing_categories),
    }
    json_path.write_text(json.dumps(json_report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nReport written to:\n  {md_path}\n  {json_path}")


if __name__ == "__main__":
    main()
