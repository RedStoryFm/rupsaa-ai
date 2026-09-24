#!/usr/bin/env python3
"""Safe bulk-review workflow for production conversations.

This does NOT change any record's status by itself. It is a two-step
workflow, always in this order:

  1. `candidates` — filters the live dataset (by status, voice-audit
     recommendation, source_type, language, and/or category) and writes
     the matching ids to a plain-text file, one per line, with enough
     context (score/flags/first line) for a human to actually read before
     deciding, not just rubber-stamp.

         python scripts/dataset_bulk_review.py candidates \\
             --audit data/production/reports/VOICE_AUDIT_V1_0_SESSION_FINAL.jsonl \\
             --recommendation STRONG --source-type synthetic_curated \\
             --out /tmp/candidates.txt

  2. A human reads that file and deletes any line they do NOT want
     actioned (or runs `python scripts/dataset_review.py show <id>` to
     read the full conversation first). Only ids that SURVIVE in the file
     get used in step 3.

  3. `apply` — reads that (now human-edited) file and applies exactly one
     action (approve / reject / needs-edit) to exactly those ids, and only
     those ids. It re-verifies each id still matches the same filters used
     in step 1 (protects against the dataset changing since then), prints
     the number affected and the filters before doing anything, and
     refuses to run at all without `--confirm`. Rejecting requires
     `--notes` explaining why (same rule as scripts/dataset_review.py).

         python scripts/dataset_bulk_review.py apply \\
             --audit data/production/reports/VOICE_AUDIT_V1_0_SESSION_FINAL.jsonl \\
             --recommendation STRONG --source-type synthetic_curated \\
             --ids-file /tmp/candidates.txt --action approve --confirm

This is intentionally NOT an "approve everything matching a filter"
one-liner — a human must look at (and can freely edit down) the candidate
list between step 1 and step 3, and every apply prints exactly what it's
about to change before doing it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import default_base_dir  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402


def load_audit(path: str | None) -> dict[str, dict]:
    if not path:
        return {}
    entries = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            entries[entry["conversation_id"]] = entry
    return entries


def _matches_filters(record, audit_entry, args) -> bool:
    if args.recommendation and args.recommendation != "all":
        if audit_entry is None or audit_entry.get("recommendation") != args.recommendation:
            return False
    if args.source_type and record.source_type != args.source_type:
        return False
    if args.language and record.language != args.language:
        return False
    if args.category and record.category != args.category:
        return False
    return True


def _filter_summary(args) -> str:
    parts = [f"status={args.status}"]
    if args.recommendation and args.recommendation != "all":
        parts.append(f"recommendation={args.recommendation}")
    if args.source_type:
        parts.append(f"source_type={args.source_type}")
    if args.language:
        parts.append(f"language={args.language}")
    if args.category:
        parts.append(f"category={args.category}")
    return ", ".join(parts)


def cmd_candidates(store: DatasetStore, args: argparse.Namespace) -> None:
    audit = load_audit(args.audit)
    statuses = None if args.status == "all" else {args.status}
    pool = {loc.record.id: loc for loc in store.list_all(statuses)}

    matched = [
        cid for cid, loc in pool.items()
        if _matches_filters(loc.record, audit.get(cid), args)
    ]
    matched.sort()

    print(f"Filters: {_filter_summary(args)}")
    print(f"Matched {len(matched)} conversation(s) out of {len(pool)} in status pool '{args.status}'.")

    if not matched:
        print("Nothing to write.")
        return

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(
            f"# Bulk-review candidates — filters: {_filter_summary(args)}\n"
            "# Delete any line for a conversation you do NOT want actioned.\n"
            "# Only ids remaining in this file when passed to `apply` will be touched.\n"
            "# Use `python scripts/dataset_review.py show <id>` to read the full conversation first.\n#\n"
        )
        for cid in matched:
            record = pool[cid].record
            entry = audit.get(cid)
            first_user = next((m["content"] for m in record.messages if m["role"] == "user"), "")[:60]
            score_part = f"score={entry['scores']['total_score']} rec={entry['recommendation']} " if entry else ""
            f.write(
                f"{cid}  # {score_part}source_type={record.source_type} "
                f"category={record.category} language={record.language} | \"{first_user}\"\n"
            )

    print(f"Written to {out_path}")
    print("Review this file (edit it down to only what you actually want), then run `apply` with the same filters plus --action and --confirm.")


def _parse_ids_file(path: Path) -> list[str]:
    ids = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.append(line.split()[0])  # first token on the line is the id
    return ids


_ACTION_TO_STATUS = {"approve": "approved", "reject": "rejected", "needs-edit": "needs_edit"}


def cmd_apply(store: DatasetStore, args: argparse.Namespace) -> None:
    if args.action == "reject" and not (args.notes and args.notes.strip()):
        print("--notes is required when --action reject (same rule as scripts/dataset_review.py).")
        sys.exit(1)

    audit = load_audit(args.audit)
    ids = _parse_ids_file(Path(args.ids_file))
    if not ids:
        print("ids-file contained no ids after stripping comments/blank lines — nothing to do.")
        return

    print(f"Filters: {_filter_summary(args)}")
    print(f"Action: {args.action} -> quality_status={_ACTION_TO_STATUS[args.action]}")
    print(f"Candidate ids in file: {len(ids)}")

    if not args.confirm:
        print("\nRefusing to apply without --confirm. This changes real production conversation status — review the ids-file, then re-run this exact command with --confirm.")
        sys.exit(1)

    new_status = _ACTION_TO_STATUS[args.action]
    changed, skipped = [], []
    for cid in ids:
        loc = store.load(cid)
        if loc is None:
            skipped.append((cid, "not found in dataset"))
            continue
        if loc.record.quality_status != args.status:
            skipped.append((cid, f"no longer '{args.status}' (currently {loc.record.quality_status})"))
            continue
        if not _matches_filters(loc.record, audit.get(cid), args):
            skipped.append((cid, "no longer matches the given filters"))
            continue
        note = f"[bulk-{args.action} via dataset_bulk_review.py, filters: {_filter_summary(args)}]"
        if args.notes:
            note += f" {args.notes}"
        loc.record.notes = (loc.record.notes + " " if loc.record.notes else "") + note
        store.move(loc.record, loc.path, new_status)
        changed.append(cid)

    print(f"\n{args.action.capitalize()}d {len(changed)} conversation(s).")
    if skipped:
        print(f"Skipped {len(skipped)} id(s):")
        for cid, reason in skipped:
            print(f"  {cid}: {reason}")


def _add_common_filters(p: argparse.ArgumentParser) -> None:
    p.add_argument("--status", default="draft", help="Status pool to select from (default: draft).")
    p.add_argument("--audit", default=None, help="Voice-audit JSONL report, needed for --recommendation.")
    p.add_argument("--recommendation", default=None, choices=["STRONG", "NEEDS_EDIT", "WEAK", "all"],
                    help="Filter by the audit's recommendation for each id (requires --audit).")
    p.add_argument("--source-type", default=None, help="e.g. human_authored, synthetic_curated, imported.")
    p.add_argument("--language", default=None, help="e.g. bn, banglish, en, mixed.")
    p.add_argument("--category", default=None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-dir", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_candidates = subparsers.add_parser("candidates")
    _add_common_filters(p_candidates)
    p_candidates.add_argument("--out", required=True, help="Where to write the reviewable candidate list.")
    p_candidates.set_defaults(func=cmd_candidates)

    p_apply = subparsers.add_parser("apply")
    _add_common_filters(p_apply)
    p_apply.add_argument("--ids-file", required=True, help="The (human-reviewed/edited) candidate list.")
    p_apply.add_argument("--action", required=True, choices=["approve", "reject", "needs-edit"])
    p_apply.add_argument("--notes", default=None, help="Required for --action reject.")
    p_apply.add_argument("--confirm", action="store_true")
    p_apply.set_defaults(func=cmd_apply)

    args = parser.parse_args()
    base_dir = Path(args.base_dir) if args.base_dir else default_base_dir()
    store = DatasetStore(base_dir)
    args.func(store, args)


if __name__ == "__main__":
    main()
