#!/usr/bin/env python3
"""Human review workflow for production conversations: list, inspect,
approve, reject, mark needs-edit, or send back to draft.

Usage:
    python scripts/dataset_review.py list --status draft
    python scripts/dataset_review.py list --category relationship_dating --limit 20
    python scripts/dataset_review.py show rup-000012
    python scripts/dataset_review.py approve rup-000012 --notes "clean, good variation"
    python scripts/dataset_review.py reject rup-000013 --notes "repetitive opening, redo"
    python scripts/dataset_review.py needs-edit rup-000014 --notes "assistant reply too long"
    python scripts/dataset_review.py to-draft rup-000013

Physical storage: DRAFT and NEEDS_EDIT both live in data/production/drafts/
(distinguished by the quality_status field); APPROVED and REJECTED move the
file to data/production/approved/ and data/production/rejected/
respectively. Rejecting always requires --notes explaining why.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import default_base_dir  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402


def cmd_list(store: DatasetStore, args: argparse.Namespace) -> None:
    statuses = None if args.status == "all" else set(args.status.split(","))
    locations = store.list_all(statuses)
    if args.category:
        locations = [loc for loc in locations if loc.record.category == args.category]
    if args.language:
        locations = [loc for loc in locations if loc.record.language == args.language]

    locations = locations[: args.limit]
    if not locations:
        print("(no matching records)")
        return

    print(f"{'ID':<14} {'STATUS':<12} {'CATEGORY':<28} {'LANG':<10} {'TURNS':<6} FIRST USER MESSAGE")
    for loc in locations:
        r = loc.record
        turns = sum(1 for m in r.messages if m["role"] == "user")
        first_user = next((m["content"] for m in r.messages if m["role"] == "user"), "")[:40]
        print(f"{r.id:<14} {r.quality_status:<12} {r.category:<28} {r.language:<10} {turns:<6} {first_user}")


def cmd_show(store: DatasetStore, args: argparse.Namespace) -> None:
    loc = store.load(args.id)
    if loc is None:
        print(f"No record found with id '{args.id}'")
        sys.exit(1)
    print(loc.record.to_json())


def _transition(store: DatasetStore, record_id: str, new_status: str, notes: str | None, require_notes: bool) -> None:
    loc = store.load(record_id)
    if loc is None:
        print(f"No record found with id '{record_id}'")
        sys.exit(1)
    if require_notes and not (notes and notes.strip()):
        print(f"--notes is required when moving a record to '{new_status}'")
        sys.exit(1)
    if notes:
        loc.record.notes = notes
    new_path = store.move(loc.record, loc.path, new_status)
    print(f"{record_id}: {loc.record.quality_status} -> moved to {new_path}")


def cmd_approve(store: DatasetStore, args: argparse.Namespace) -> None:
    _transition(store, args.id, "approved", args.notes, require_notes=False)


def cmd_reject(store: DatasetStore, args: argparse.Namespace) -> None:
    _transition(store, args.id, "rejected", args.notes, require_notes=True)


def cmd_needs_edit(store: DatasetStore, args: argparse.Namespace) -> None:
    _transition(store, args.id, "needs_edit", args.notes, require_notes=False)


def cmd_to_draft(store: DatasetStore, args: argparse.Namespace) -> None:
    _transition(store, args.id, "draft", args.notes, require_notes=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-dir", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_list = subparsers.add_parser("list")
    p_list.add_argument("--status", default="draft")
    p_list.add_argument("--category", default=None)
    p_list.add_argument("--language", default=None)
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=cmd_list)

    p_show = subparsers.add_parser("show")
    p_show.add_argument("id")
    p_show.set_defaults(func=cmd_show)

    p_approve = subparsers.add_parser("approve")
    p_approve.add_argument("id")
    p_approve.add_argument("--notes", default=None)
    p_approve.set_defaults(func=cmd_approve)

    p_reject = subparsers.add_parser("reject")
    p_reject.add_argument("id")
    p_reject.add_argument("--notes", required=True)
    p_reject.set_defaults(func=cmd_reject)

    p_needs_edit = subparsers.add_parser("needs-edit")
    p_needs_edit.add_argument("id")
    p_needs_edit.add_argument("--notes", default=None)
    p_needs_edit.set_defaults(func=cmd_needs_edit)

    p_to_draft = subparsers.add_parser("to-draft")
    p_to_draft.add_argument("id")
    p_to_draft.add_argument("--notes", default=None)
    p_to_draft.set_defaults(func=cmd_to_draft)

    args = parser.parse_args()
    base_dir = Path(args.base_dir) if args.base_dir else default_base_dir()
    store = DatasetStore(base_dir)
    args.func(store, args)


if __name__ == "__main__":
    main()
