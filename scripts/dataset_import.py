#!/usr/bin/env python3
"""Import conversations into the Rupsaa dataset production workspace.

Accepts either:
  - plain canonical JSONL (like data/examples/starter_conversations.jsonl):
    one {"messages": [...]} object per line, with optional "category" etc.
  - a JSON file containing a single record or a list of records
  - already-extended production records (with id/category/language/... set)

Missing metadata fields fall back to the --category/--language/etc. CLI
flags; conversation_length is auto-derived from turn count if not given;
missing ids are auto-assigned (rup-000001, rup-000123, ...). Every imported
record starts at --status (default: draft) and is written to
data/production/drafts/ (or wherever --status maps to).

Usage:
    python scripts/dataset_import.py --input data/examples/starter_conversations.jsonl \\
        --source-type imported --status draft

    python scripts/dataset_import.py --input my_new_batch.jsonl \\
        --category relationship_dating --language en --tone empathetic

Records that fail validation are skipped (not imported) and reported —
one bad record never blocks the rest of a batch. Exits non-zero if any
record failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import default_base_dir, load_dataset_config  # noqa: E402
from rupsaa.dataset.normalize import normalize_messages  # noqa: E402
from rupsaa.dataset.schema import ConversationRecord, derive_conversation_length, validate_record  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402


def load_source_records(paths: list[Path]) -> list[dict]:
    records: list[dict] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"input path not found: {path}")
        if path.suffix == ".jsonl":
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        elif path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            records.extend(data if isinstance(data, list) else [data])
        else:
            raise ValueError(f"unsupported input file type: {path} (expected .jsonl or .json)")
    return records


def build_record(raw: dict, store: DatasetStore, cfg: dict, args: argparse.Namespace) -> ConversationRecord:
    if "messages" not in raw:
        raise ValueError("record has no 'messages' field")

    messages = normalize_messages(raw["messages"])

    category = raw.get("category") or args.category
    if not category:
        raise ValueError("no category on record and no --category default given")

    record_id = raw.get("id") or store.generate_id(cfg["ids"]["prefix"], cfg["ids"]["padding"])

    conversation_length = raw.get("conversation_length") or derive_conversation_length(
        messages, cfg["conversation_length_bins"]
    )

    return ConversationRecord(
        id=record_id,
        messages=messages,
        language=raw.get("language") or args.language,
        language_mix=raw.get("language_mix") or args.language_mix,
        category=category,
        subcategory=raw.get("subcategory") or args.subcategory,
        tone=raw.get("tone") or args.tone,
        conversation_length=conversation_length,
        source_type=raw.get("source_type") or args.source_type,
        quality_status=raw.get("quality_status") or args.status,
        notes=raw.get("notes") or args.notes or "",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", nargs="+", required=True)
    parser.add_argument("--base-dir", default=None, help="Override data/production/ location (mainly for tests).")
    parser.add_argument("--category", default=None, help="Default category if a record doesn't specify one.")
    parser.add_argument("--subcategory", default=None)
    parser.add_argument("--language", default="en")
    parser.add_argument("--language-mix", default=None)
    parser.add_argument("--tone", default=None)
    parser.add_argument("--source-type", default="imported")
    parser.add_argument("--status", default="draft")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    cfg = load_dataset_config()
    base_dir = Path(args.base_dir) if args.base_dir else default_base_dir()
    store = DatasetStore(base_dir)

    raw_records = load_source_records([Path(p) for p in args.input])
    print(f"Loaded {len(raw_records)} source record(s) from {len(args.input)} file(s).")

    imported, failed = 0, []
    for i, raw in enumerate(raw_records):
        try:
            record = build_record(raw, store, cfg, args)
        except ValueError as e:
            failed.append((i, str(e)))
            continue

        errors = validate_record(record)
        if errors:
            failed.append((i, "; ".join(errors)))
            continue

        store.save_new(record)
        imported += 1

    print(f"\nImported: {imported}")
    print(f"Failed:   {len(failed)}")
    for i, reason in failed:
        print(f"  - source record {i}: {reason}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
