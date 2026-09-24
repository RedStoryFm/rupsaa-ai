#!/usr/bin/env python3
"""Export APPROVED production conversations into QLoRA-pipeline-compatible
train/validation/test JSONL files.

Usage:
    python scripts/dataset_export.py
    python scripts/dataset_export.py --output-dir data/production/exports --seed 42

Only records with quality_status == "approved" are exported. All production
metadata (id, category, tone, notes, ...) is stripped — the output is
exactly the {"messages": [...]} shape the existing QLoRA pipeline expects
(scripts/train_qlora.py, scripts/validate_dataset.py), verified by running
that pipeline's own validator against the exported files before declaring
success.

This NEVER writes to data/train.jsonl, data/validation.jsonl, data/test.jsonl,
or data/examples/ — those are the existing pipeline's own files and are left
untouched. To actually train on this export, either point
configs/training.yaml's data.train_path/validation_path at the files under
--output-dir, or copy them into data/ yourself once you're ready.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import default_base_dir, load_dataset_config  # noqa: E402
from rupsaa.dataset.dedup import group_near_duplicates  # noqa: E402
from rupsaa.dataset.diversity import analyze_with_config  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402
from scripts.prepare_dataset import split_id_groups  # noqa: E402
from scripts.validate_dataset import print_report, validate_file  # noqa: E402


def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-dir", default=None, help="data/production/ location.")
    parser.add_argument("--output-dir", default=None, help="Defaults to <base-dir>/exports.")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--train-ratio", type=float, default=None)
    parser.add_argument("--val-ratio", type=float, default=None)
    parser.add_argument("--allow-diversity-failures", action="store_true",
                        help="Export even if the corpus-diversity gate reports BLOCK issues. Only for reproducing "
                             "historical exports / diagnosis — such an export is NOT training-ready.")
    args = parser.parse_args()

    cfg = load_dataset_config()
    split_cfg = cfg["split"]
    seed = args.seed if args.seed is not None else split_cfg["seed"]
    train_ratio = args.train_ratio if args.train_ratio is not None else split_cfg["train_ratio"]
    val_ratio = args.val_ratio if args.val_ratio is not None else split_cfg["val_ratio"]

    base_dir = Path(args.base_dir) if args.base_dir else default_base_dir()
    store = DatasetStore(base_dir)
    output_dir = Path(args.output_dir) if args.output_dir else store.exports_dir

    approved = [loc.record for loc in store.list_all({"approved"})]
    if not approved:
        print("No approved conversations found — nothing to export. Approve some with scripts/dataset_review.py first.")
        sys.exit(1)

    # Corpus-level diversity gate (V0.1 post-mortem: "honestly" in 863/1129
    # training replies passed every per-record check).
    diversity = analyze_with_config(approved)
    if diversity.blocking:
        print(f"Corpus diversity gate: {len(diversity.blocking)} BLOCK issue(s):")
        for issue in diversity.blocking[:15]:
            print(f"  - {issue.describe()}")
        if not args.allow_diversity_failures:
            print("REFUSING to export: the approved corpus is not training-ready. Fix the concentration "
                  "(see scripts/dataset_audit.py) or pass --allow-diversity-failures for a non-training export.")
            sys.exit(1)
        print("WARNING: --allow-diversity-failures set — this export is NOT training-ready.")

    print(f"Exporting {len(approved)} approved conversation(s) (seed={seed}, train_ratio={train_ratio}, val_ratio={val_ratio})")

    # Group near-duplicate/closely-related conversations before splitting,
    # so no cluster of similar variants ends up split across train and
    # validation/test (which would let validation loss look artificially
    # good just from memorized near-copies in train).
    near_cfg = cfg["near_duplicate"]
    id_groups = group_near_duplicates(
        approved, ngram_size=near_cfg["ngram_size"], threshold=near_cfg["similarity_threshold"],
        max_records=near_cfg["max_records_for_full_scan"],
    )
    non_singleton = [g for g in id_groups if len(g) > 1]
    if non_singleton:
        print(f"Grouped {sum(len(g) for g in non_singleton)} near-duplicate record(s) into {len(non_singleton)} cluster(s) kept together across the split.")

    train_ids, val_ids, test_ids = split_id_groups(id_groups, seed, train_ratio, val_ratio)
    by_id = {r.id: r for r in approved}
    train = [by_id[i].strip_for_training() for i in train_ids]
    val = [by_id[i].strip_for_training() for i in val_ids]
    test = [by_id[i].strip_for_training() for i in test_ids]

    train_path = output_dir / "train.jsonl"
    val_path = output_dir / "validation.jsonl"
    test_path = output_dir / "test.jsonl"
    write_jsonl(train, train_path)
    write_jsonl(val, val_path)
    write_jsonl(test, test_path)
    (output_dir / "diversity_report.json").write_text(
        json.dumps(diversity.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Wrote {len(train)} train / {len(val)} validation / {len(test)} test examples to {output_dir}")

    print("\nValidating export against the existing QLoRA pipeline's own validator...")
    all_valid = True
    for path in (train_path, val_path, test_path):
        report = validate_file(path)
        print_report(report)
        all_valid = all_valid and report.is_valid

    if not all_valid:
        print("\nExport produced data that fails the pipeline's own validator — this indicates a bug in the exporter. Investigate before using this export.")
        sys.exit(1)

    print(f"\nExport compatible with the QLoRA pipeline. To train on it:")
    print(f"  - edit configs/training.yaml data.train_path/validation_path to point at {output_dir}, OR")
    print(f"  - copy {train_path} -> data/train.jsonl (and validation.jsonl) once you're ready.")
    print("This script never modifies data/train.jsonl, data/examples/, or configs/ automatically.")


if __name__ == "__main__":
    main()
