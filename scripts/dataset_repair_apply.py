#!/usr/bin/env python3
"""Apply a batch of hand-authored repair edits to DRAFT conversations.

Usage:
    python scripts/dataset_repair_apply.py --edits batch.jsonl

Input format (one JSON object per line):
    {"conversation_id": "rup-000056", "message_index": 1,
     "new_content": "...", "reason": "...", "repair_notes": "..."}

Each edit patches exactly one existing assistant-role message's content in
place. Never touches user/system messages, never changes quality_status
(stays draft), never adds/removes messages. Appends one entry per successful
edit to data/production/reports/VOICE_REPAIR_V1.jsonl (creating it on first
run). Conversations that fail validation are skipped and reported, not
silently dropped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import default_base_dir  # noqa: E402
from rupsaa.dataset.repair import RepairEdit, RepairError, apply_repair, build_audit_index  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def append_jsonl(entries: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--edits", required=True, help="JSONL file of edit instructions")
    parser.add_argument("--audit", default="data/production/reports/VOICE_AUDIT_V1.jsonl")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--repair-log", default="data/production/reports/VOICE_REPAIR_V1.jsonl")
    args = parser.parse_args()

    base_dir = Path(args.base_dir) if args.base_dir else default_base_dir()
    store = DatasetStore(base_dir)

    audit_records = load_jsonl(Path(args.audit))
    audit_index = build_audit_index(audit_records)

    edits_raw = load_jsonl(Path(args.edits))
    print(f"Loaded {len(edits_raw)} edit instruction(s) from {args.edits}")

    applied, failed = [], []
    for raw in edits_raw:
        edit = RepairEdit(
            conversation_id=raw["conversation_id"],
            message_index=raw["message_index"],
            new_content=raw["new_content"],
            reason=raw["reason"],
            repair_notes=raw.get("repair_notes", ""),
        )
        try:
            log_entry = apply_repair(store, edit, audit_index)
        except RepairError as e:
            failed.append((raw.get("conversation_id", "?"), str(e)))
            continue
        applied.append({
            "conversation_id": log_entry.conversation_id,
            "original_scores": log_entry.original_scores,
            "original_flags": log_entry.original_flags,
            "changed_message_indices": log_entry.changed_message_indices,
            "reason_for_change": log_entry.reason_for_change,
            "before": log_entry.before,
            "after": log_entry.after,
            "repair_notes": log_entry.repair_notes,
        })

    append_jsonl(applied, Path(args.repair_log))

    print(f"Applied: {len(applied)}")
    print(f"Failed:  {len(failed)}")
    for cid, reason in failed:
        print(f"  - {cid}: {reason}")
    print(f"Repair log: {args.repair_log}")


if __name__ == "__main__":
    main()
