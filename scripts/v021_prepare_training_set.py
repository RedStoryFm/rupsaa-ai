#!/usr/bin/env python3
"""Freeze Rupsaa V0.2.1 and write its LLaMA-Factory export — never trains.

    python scripts/v021_prepare_training_set.py --dry-run   # plan + checks, writes nothing
    python scripts/v021_prepare_training_set.py             # freeze (needs FREEZE_AUTHORIZATION.json)

Mixture (V021_TRAINING_PLAN.md / PRETRAINING_REPORT.md):
  train.jsonl        = frozen V0.2 train (1380, unchanged) + every corrective TRAIN record twice
  validation / test  = frozen V0.2 validation / test, byte-identical copies (never trained)
  corrective_holdout = ~10% of the corrective set, stratified by category, never trained

Weighting is implemented as exact duplicate rows (2 copies of each corrective train record).
LLaMA-Factory 0.7.1 has no separate eval file: it carves its internal eval slice from train.jsonl
with datasets' train_test_split(test_size=val_size, seed=42), which depends only on the row count.
This script computes those row positions and puts ONLY single-copy frozen V0.2 rows there (V0.2's
own 69 internal-eval rows first), so no corrective record can sit in both the optimizer's train
set and the eval set used to pick the best checkpoint. train_row_map.jsonl records every row.

Refuses to run unless: frozen V0.2 files match their manifest, the corrective records are exactly
what the runtime rebuilds (train-as-serve), the corpus gates and the leakage check pass, the
authorization file pins the current corrective_records.jsonl, and the freeze does not exist yet.
Frozen files are made read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import stat
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402

CORR_DIR = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.1"
RECORDS = CORR_DIR / "corrective_records.jsonl"
SOURCE = CORR_DIR / "source_conversations.py"
AUTH = CORR_DIR / "FREEZE_AUTHORIZATION.json"
V02_EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2"
V02_SNAPSHOT = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training"
V02_MANIFEST = V02_SNAPSHOT / "V02_TRAINING_MANIFEST.json"
REPORTS = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation"
OUT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.1"
SNAPSHOT = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2.1_training"
MANIFEST_NAME = "V021_TRAINING_MANIFEST.json"

UPSAMPLE = 2
HOLDOUT_FRACTION = 0.10
VAL_SIZE = 0.05  # must equal val_size in the CLI and GUI configs
SEED = 42  # LLaMA-Factory / HF trainer default seed used by split_dataset
BATCH, GRAD_ACC, EPOCHS = 2, 8, 2


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def holdout_ids(records: list[dict]) -> set[str]:
    """Deterministic, stratified: per category the ceil(10%) ids with the smallest sha1(id)."""
    by_cat = defaultdict(list)
    for r in records:
        by_cat[r["category"]].append(r["id"])
    out = set()
    for ids in by_cat.values():
        k = max(1, math.ceil(len(ids) * HOLDOUT_FRACTION))
        out.update(sorted(ids, key=lambda i: hashlib.sha1(i.encode()).hexdigest())[:k])
    return out


def internal_eval_positions(n_rows: int) -> set[int]:
    """Row indices LLaMA-Factory 0.7.1's split_dataset will use for eval (same call, same seed)."""
    from datasets import Dataset
    split = Dataset.from_dict({"i": list(range(n_rows))}).train_test_split(test_size=VAL_SIZE, seed=SEED)
    return set(split["test"]["i"])


def expected_steps(n_train_rows: int) -> tuple[int, int]:
    batches = math.ceil(n_train_rows / BATCH)
    per_epoch = batches // GRAD_ACC  # HF Trainer: len(dataloader) // gradient_accumulation_steps
    return per_epoch, per_epoch * EPOCHS


def build_rows(v02_train: list[str], corr_train: list[dict]) -> tuple[list[str], list[dict], dict]:
    """Order rows so every internal-eval position holds a single-copy frozen V0.2 row."""
    n = len(v02_train) + UPSAMPLE * len(corr_train)
    eval_pos = internal_eval_positions(n)
    v02_eval_before = internal_eval_positions(len(v02_train))  # V0.2's own 69 internal-eval rows
    preferred = sorted(v02_eval_before) + [i for i in range(len(v02_train)) if i not in v02_eval_before]
    eval_src = preferred[: len(eval_pos)]
    eval_src_set = set(eval_src)
    rest_v02 = [i for i in range(len(v02_train)) if i not in eval_src_set]
    rest = [("v02", i, 1) for i in rest_v02] + [("corr", j, c + 1) for c in range(UPSAMPLE) for j in range(len(corr_train))]
    eval_iter, rest_iter = iter(eval_src), iter(rest)
    rows, row_map = [], []
    for pos in range(n):
        if pos in eval_pos:
            src = ("v02", next(eval_iter), 1)
        else:
            src = next(rest_iter)
        kind, idx, copy = src
        if kind == "v02":
            rows.append(v02_train[idx])
            row_map.append({"row": pos, "source": "rupsaa_v0.2_train", "source_line": idx + 1, "copy": 1,
                            "internal_split": "eval" if pos in eval_pos else "train"})
        else:
            rec = corr_train[idx]
            rows.append(json.dumps({"messages": rec["messages"]}, ensure_ascii=False) + "\n")
            row_map.append({"row": pos, "source": "rupsaa_v0.2.1_corrective", "id": rec["id"], "copy": copy,
                            "internal_split": "train"})
    assert next(eval_iter, None) is None and next(rest_iter, None) is None, "row placement did not use every row"
    info = {"rows": n, "internal_eval_rows": len(eval_pos), "internal_train_rows": n - len(eval_pos),
            "internal_eval_from_v02_internal_eval": len(set(eval_src) & v02_eval_before),
            "corrective_rows_in_internal_eval": sum(1 for m in row_map if m["internal_split"] == "eval"
                                                    and m["source"] != "rupsaa_v0.2_train")}
    return rows, row_map, info


def run_gate(script: str) -> None:
    r = subprocess.run([sys.executable, f"scripts/{script}"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{script} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")


def make_readonly(path: Path) -> None:
    for p in ([path] if path.is_file() else sorted(path.rglob("*"))):
        if p.is_file():
            p.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    v02_manifest = json.loads(V02_MANIFEST.read_text(encoding="utf-8"))
    for split in ("train", "validation", "test"):
        if sha256(V02_EXPORT / f"{split}.jsonl") != v02_manifest["export_files_sha256"][split]:
            sys.exit(f"frozen V0.2 {split}.jsonl does not match its manifest — refusing")
    if sha256(V02_SNAPSHOT / "frozen_records.jsonl") != v02_manifest["dataset_sha256"]:
        sys.exit("frozen V0.2 records do not match their manifest — refusing")

    from rupsaa.rag.terminology import TerminologyStore
    from scripts.v021_build_corrective import build, load_source
    records = [json.loads(line) for line in open(RECORDS, encoding="utf-8")]
    rebuilt, errors = build(load_source(), TerminologyStore(PROJECT_ROOT / "knowledge/terminology"))
    if errors or [r["messages"] for r in rebuilt] != [r["messages"] for r in records]:
        sys.exit("corrective_records.jsonl is not what the runtime rebuilds from the source — run v021_build_corrective.py")
    run_gate("v021_corrective_checks.py")
    checks = json.loads((REPORTS / "corrective_checks.json").read_text(encoding="utf-8"))
    if not checks["all_gates_pass"]:
        sys.exit(f"corpus gates fail: {checks['gates']}")
    run_gate("v021_leakage_check.py")

    hold = holdout_ids(records)
    corr_train = [r for r in records if r["id"] not in hold]
    corr_hold = [r for r in records if r["id"] in hold]
    v02_train = open(V02_EXPORT / "train.jsonl", encoding="utf-8").readlines()
    rows, row_map, split_info = build_rows(v02_train, corr_train)
    per_epoch, total = expected_steps(split_info["internal_train_rows"])
    plan = {"v02_train_rows": len(v02_train), "corrective_train_records": len(corr_train),
            "corrective_holdout_records": len(corr_hold), "upsample": UPSAMPLE, "train_rows": len(rows),
            "corrective_share_of_train_rows": round(UPSAMPLE * len(corr_train) / len(rows), 3), **split_info,
            "expected_steps_per_epoch": per_epoch, "expected_total_steps": total, "holdout_ids": sorted(hold)}
    print(json.dumps(plan, indent=1))
    if split_info["corrective_rows_in_internal_eval"]:
        sys.exit("a corrective row landed in the internal eval slice — refusing")
    if args.dry_run:
        print("dry run: nothing written")
        return

    if not AUTH.exists():
        sys.exit(f"No freeze authorization ({AUTH.relative_to(PROJECT_ROOT)}).")
    auth = json.loads(AUTH.read_text(encoding="utf-8"))
    if not auth.get("authorized") or auth.get("corrective_records_sha256") != sha256(RECORDS):
        sys.exit("Freeze authorization missing, not authorized, or for a different corrective_records.jsonl.")
    if OUT.exists() or SNAPSHOT.exists():
        sys.exit(f"{OUT.relative_to(PROJECT_ROOT)} or {SNAPSHOT.relative_to(PROJECT_ROOT)} already exists — a freeze is never overwritten.")

    # --- snapshot (what was reviewed and approved) ---
    SNAPSHOT.mkdir(parents=True)
    for f in (RECORDS, SOURCE, AUTH):
        shutil.copy2(f, SNAPSHOT / f.name)
    # --- export (what LLaMA-Factory reads) ---
    OUT.mkdir(parents=True)
    (OUT / "train.jsonl").write_text("".join(rows), encoding="utf-8")
    for split in ("validation", "test"):
        shutil.copyfile(V02_EXPORT / f"{split}.jsonl", OUT / f"{split}.jsonl")
    (OUT / "corrective_holdout.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in corr_hold), encoding="utf-8")
    (OUT / "train_row_map.jsonl").write_text("".join(json.dumps(m) + "\n" for m in row_map), encoding="utf-8")
    fmt = json.loads((V02_EXPORT / "dataset_info.json").read_text(encoding="utf-8"))["rupsaa_v0.2_train"]
    info = {f"rupsaa_v0.2.1_{s}": {**fmt, "file_name": f"{s}.jsonl"} for s in ("train", "validation", "test")}
    info["rupsaa_v0.2.1_corrective_holdout"] = {**fmt, "file_name": "corrective_holdout.jsonl"}
    (OUT / "dataset_info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")

    files = {p.name: sha256(p) for p in sorted(OUT.glob("*.jsonl")) + [OUT / "dataset_info.json"]}
    order = ("train.jsonl", "validation.jsonl", "test.jsonl", "corrective_holdout.jsonl")
    dataset_sha = hashlib.sha256("".join(f"{files[n]}  {n}\n" for n in order).encode()).hexdigest()
    frozen = [json.loads(line) for line in open(V02_SNAPSHOT / "frozen_records.jsonl", encoding="utf-8")]
    base_train = [r for r in frozen if r["split"] == "train"]
    n_replies = lambda recs: sum(1 for r in recs for m in r["messages"] if m["role"] == "assistant")  # noqa: E731
    from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout.strip()
    manifest = {
        "name": "rupsaa_v0.2.1",
        "status": "frozen",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head_at_freeze": git,
        "dataset_sha256": dataset_sha,
        "dataset_sha256_definition": "sha256 of the lines '<sha256>  <file>\\n' for train.jsonl, validation.jsonl, "
                                     "test.jsonl, corrective_holdout.jsonl (in that order) of this export",
        "files_sha256": files,
        "snapshot_files_sha256": {p.name: sha256(p) for p in sorted(SNAPSHOT.iterdir())},
        "parent_dataset": {"name": "rupsaa_v0.2", "dataset_sha256": v02_manifest["dataset_sha256"],
                           "export_files_sha256": v02_manifest["export_files_sha256"],
                           "manifest": str(V02_MANIFEST.relative_to(PROJECT_ROOT)), "modified": False},
        "prompt_version": "v0.2",
        "system_prompt_sha256": hashlib.sha256(V02_SYSTEM_PROMPT.encode()).hexdigest(),
        "system_prompt_note": "Every row's system turn is exactly what the runtime sends (V02_SYSTEM_PROMPT + the "
                              "terminology block / recall note / language directive where the runtime adds them).",
        "conversations": {"base_v02_train_unique": len(base_train), "corrective_train_unique": len(corr_train),
                          "corrective_holdout_unique": len(corr_hold),
                          "unique_training_conversations": len(base_train) + len(corr_train)},
        "assistant_replies": {"base_v02_train": n_replies(base_train), "corrective_train_unique": n_replies(corr_train),
                              "corrective_train_weighted": UPSAMPLE * n_replies(corr_train),
                              "corrective_holdout": n_replies(corr_hold),
                              "training_total_weighted": n_replies(base_train) + UPSAMPLE * n_replies(corr_train)},
        "languages": {"base_v02_train": dict(Counter(r["language"] for r in base_train)),
                      "corrective_train_final_reply": dict(Counter(r["language"] for r in corr_train)),
                      "corrective_holdout_final_reply": dict(Counter(r["language"] for r in corr_hold)),
                      "corrective_language_switch_conversations": sum(r["category"] == "language_switch" for r in records)},
        "sources": {"base_v02_train": dict(Counter(r.get("source_type", "?") for r in base_train)),
                    "corrective": dict(Counter(r["source_type"] for r in records))},
        "corrective_categories": {"train": dict(Counter(r["category"] for r in corr_train)),
                                  "holdout": dict(Counter(r["category"] for r in corr_hold))},
        "weighting": {"method": "duplicate rows", "corrective_train_copies": UPSAMPLE, "base_copies": 1,
                      "corrective_share_of_train_rows": plan["corrective_share_of_train_rows"],
                      "holdout_duplicated": False, "row_map": "train_row_map.jsonl",
                      "internal_eval_placement": "LLaMA-Factory 0.7.1 split_dataset = datasets.train_test_split("
                                                 f"test_size={VAL_SIZE}, seed={SEED}); those row positions hold only "
                                                 "single-copy frozen V0.2 rows (V0.2's own 69 internal-eval rows first)"},
        "splits": {"train_file_rows": len(rows), "internal_train_rows": split_info["internal_train_rows"],
                   "internal_eval_rows": split_info["internal_eval_rows"],
                   "internal_eval_rows_shared_with_v02_internal_eval": split_info["internal_eval_from_v02_internal_eval"],
                   "corrective_rows_in_internal_eval": 0,
                   "external_validation": sum(1 for _ in open(OUT / "validation.jsonl", encoding="utf-8")),
                   "external_test": sum(1 for _ in open(OUT / "test.jsonl", encoding="utf-8")),
                   "corrective_holdout": len(corr_hold)},
        "holdout_ids": sorted(hold),
        "preserved_evaluation_sets": {
            "frozen_v02_validation_test": "byte-identical copies (see files_sha256 == parent export_files_sha256)",
            "clean_v01_vs_v02_subsets": "data/production/evaluation/rupsaa_v0.2/eval_manifests.json (unchanged)",
            "unseen_terminology_24": "data/production/evaluation/rupsaa_v0.2/terminology_generalization.jsonl (unchanged)",
            "corrective_holdout_21": "corrective_holdout.jsonl"},
        "training": {"expected_steps_per_epoch": per_epoch, "expected_total_steps": total,
                     "batch": BATCH, "gradient_accumulation": GRAD_ACC, "epochs": EPOCHS, "val_size": VAL_SIZE,
                     "config_cli": "configs/training/llamafactory_rupsaa_v0.2.1.yaml",
                     "config_gui_template": "configs/training/llamafactory_webui_rupsaa_v0.2.1.yaml",
                     "output_dir": "adapters/rupsaa-v0.2.1", "status": "NOT STARTED — owner approval required"},
        "reviews": {"corpus_checks": "data/production/reports/rupsaa_v0.2.1_preparation/corrective_checks.json",
                    "leakage": "data/production/reports/rupsaa_v0.2.1_preparation/leakage_report.json",
                    "human_review": "data/production/reports/rupsaa_v0.2.1_preparation/CORRECTIVE_DATA_REVIEW.md"},
        "authorization": auth,
    }
    for d in (OUT, SNAPSHOT):
        (d / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    make_readonly(OUT)
    make_readonly(SNAPSHOT)
    print(f"FROZEN rupsaa_v0.2.1  dataset_sha256={dataset_sha}")
    print(f"  export   : {OUT.relative_to(PROJECT_ROOT)}/")
    print(f"  snapshot : {SNAPSHOT.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
