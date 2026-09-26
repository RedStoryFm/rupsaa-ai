#!/usr/bin/env python3
"""Leakage report for Rupsaa V0.2.1: held-out corrective cases, benchmarks and frozen splits.

    python scripts/v021_leakage_check.py

Checks (user AND assistant turns, case/space-normalised):
  1. held-out corrective (21) vs corrective train      exact, near-duplicate (>=0.80), same term, same concept
  2. held-out corrective vs frozen V0.2 train/val/test  exact, near-duplicate, concept keyword
  3. all corrective vs benchmarks: owner live sequence, 10 live checks, 29 supplementary checks,
     24 unseen-terminology cases (turns + terms), frozen validation/test (incl. the clean V0.1-vs-V0.2 subsets)
Writes leakage_report.json + LEAKAGE_REPORT.md. Exit 1 if any blocking finding.
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from rupsaa.rag.router import classify_message  # noqa: E402

CORR = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.1/corrective_records.jsonl"
FROZEN = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/frozen_records.jsonl"
EVAL = PROJECT_ROOT / "data/production/evaluation/rupsaa_v0.2"
OUT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation"
NEAR = 0.80
MIN_LEN = 12  # below this, similarity ratios are meaningless ("ok" vs "okay"); exact matches still count


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\sঀ-৿]", " ", t.lower())).strip()


def turns(rec: dict, role: str) -> list[str]:
    return [m["content"] for m in rec["messages"] if m["role"] == role]


def near(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if a == b:
        return 1.0
    if len(a) < MIN_LEN or len(b) < MIN_LEN:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def concept(rec: dict) -> str | None:
    """What a definition-style record is about: its terminology entries, else the router's term candidate."""
    terms = sorted({t for tr in rec.get("runtime_trace", []) for t in tr["terms_used"]})
    if terms:
        return ",".join(terms)
    cand = classify_message(turns(rec, "user")[0]).term_candidate
    return norm(cand) if cand else None


def main() -> None:
    from scripts.v021_prepare_training_set import holdout_ids
    from scripts.v021_replay_live import OWNER_SEQUENCE

    corr = [json.loads(line) for line in open(CORR, encoding="utf-8")]
    hold_ids = holdout_ids(corr)
    hold = [r for r in corr if r["id"] in hold_ids]
    train = [r for r in corr if r["id"] not in hold_ids]
    frozen = [json.loads(line) for line in open(FROZEN, encoding="utf-8")]
    term_cases = [json.loads(line) for line in open(EVAL / "terminology_generalization.jsonl", encoding="utf-8")]
    bench_prompts = [("owner_live_sequence", p) for p in OWNER_SEQUENCE]
    for name in ("live_behavior_checks.json", "posttrain_supplementary_checks.json"):
        for c in json.loads((EVAL / name).read_text(encoding="utf-8")):
            bench_prompts += [(f"{name}:{c['id']}", t) for t in c["turns"]]
    for c in term_cases:
        bench_prompts += [(f"terminology:{c['id']}", t) for t in c["turns"]]

    blocking, warnings = [], []

    # 1. held-out vs corrective train
    train_concepts = {}
    for r in train:
        c = concept(r)
        if c:
            train_concepts.setdefault(c, []).append(r["id"])
    for h in hold:
        for role in ("user", "assistant"):
            for ht in turns(h, role):
                for r in train:
                    for tt in turns(r, role):
                        s = near(ht, tt)
                        if s >= NEAR:
                            blocking.append({"check": f"holdout_vs_train_{role}", "holdout": h["id"], "train": r["id"],
                                             "similarity": round(s, 3), "holdout_text": ht, "train_text": tt})
        c = concept(h)
        if c and c in train_concepts:
            blocking.append({"check": "holdout_concept_in_train", "holdout": h["id"], "concept": c, "train": train_concepts[c]})

    # 2. held-out vs frozen V0.2 (all splits)
    frozen_users = [(f["id"], f["split"], t) for f in frozen for t in turns(f, "user")]
    frozen_asst = [(f["id"], f["split"], t) for f in frozen for t in turns(f, "assistant")]
    frozen_blob = norm(" ".join(t for *_, t in frozen_users + frozen_asst))
    for h in hold:
        for role, pool in (("user", frozen_users), ("assistant", frozen_asst)):
            for ht in turns(h, role):
                for fid, split, ft in pool:
                    s = near(ht, ft)
                    if s >= NEAR:
                        (blocking if len(norm(ht)) >= MIN_LEN else warnings).append(
                            {"check": f"holdout_vs_frozen_{role}", "holdout": h["id"], "frozen": fid, "split": split,
                             "similarity": round(s, 3), "holdout_text": ht, "frozen_text": ft})
        c = concept(h)
        if c and "term-" not in c and re.search(r"(?<!\w)" + re.escape(c) + r"(?!\w)", frozen_blob):
            blocking.append({"check": "holdout_concept_in_frozen", "holdout": h["id"], "concept": c})

    # 3. all corrective vs benchmarks and the frozen external validation/test
    unseen_terms = {c["term"].lower() for c in term_cases}
    for r in corr:
        for ut in turns(r, "user"):
            for src, bp in bench_prompts:
                s = near(ut, bp)
                if s >= 0.9 or norm(ut) == norm(bp):
                    blocking.append({"check": "corrective_vs_benchmark_prompt", "record": r["id"], "benchmark": src,
                                     "similarity": round(s, 3), "text": ut, "benchmark_text": bp})
        blob = norm(" ".join(m["content"] for m in r["messages"][1:]))
        for t in unseen_terms | {"strip", "stripping", "foreplay"}:
            if re.search(r"(?<!\w)" + re.escape(norm(t)) + r"(?!\w)", blob):
                blocking.append({"check": "corrective_mentions_held_out_term", "record": r["id"], "term": t})
    ext = [(f["id"], f["split"], t) for f in frozen if f["split"] in ("validation", "test") for t in turns(f, "user") + turns(f, "assistant")]
    for r in corr:
        for t in turns(r, "user") + turns(r, "assistant"):
            for fid, split, ft in ext:
                s = near(t, ft)
                if s >= 0.9:
                    blocking.append({"check": "corrective_vs_frozen_eval", "record": r["id"], "frozen": fid, "split": split,
                                     "similarity": round(s, 3), "text": t, "frozen_text": ft})

    report = {"holdout_ids": sorted(hold_ids), "train_records": len(train), "holdout_records": len(hold),
              "thresholds": {"near_duplicate": NEAR, "benchmark_near": 0.9, "min_len_for_fuzzy": MIN_LEN},
              "benchmarks_checked": {"owner_live_sequence": len(OWNER_SEQUENCE), "prompts_total": len(bench_prompts),
                                     "unseen_terms": len(unseen_terms), "frozen_validation_test_turns": len(ext)},
              "blocking": blocking, "warnings": warnings, "pass": not blocking}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "leakage_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    L = ["# V0.2.1 leakage report", "", f"**Result: {'PASS — no leakage found' if not blocking else 'FAIL'}**", "",
         f"Held-out corrective cases: {len(hold)} ({', '.join(sorted(hold_ids))}); corrective train: {len(train)}.", "",
         "Checked, on user and assistant turns (normalised case/punctuation):",
         f"1. held-out vs corrective train — exact, near-duplicate (≥{NEAR}), same terminology entry, same definition concept",
         "2. held-out vs the frozen V0.2 train/validation/test — exact, near-duplicate, concept keyword",
         f"3. every corrective record vs {len(bench_prompts)} benchmark prompts (owner's 11-turn live sequence, 10 live checks, "
         f"29 supplementary checks, 24 unseen-terminology cases) at ≥0.9 or exact, vs the {len(unseen_terms)} unseen terms + "
         f"Strip/Foreplay, and vs all {len(ext)} frozen validation/test turns (which contain the clean V0.1-vs-V0.2 subsets) at ≥0.9",
         f"Strings under {MIN_LEN} characters are compared exactly only (\"ok\" vs \"okay\" similarity is meaningless).", ""]
    L += ["## Blocking findings", ""] + ([f"- `{b}`" for b in blocking] or ["none"]) + [""]
    L += ["## Warnings (short strings identical to frozen data)", ""] + ([f"- `{w}`" for w in warnings] or ["none"]) + [""]
    (OUT / "LEAKAGE_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("holdout_ids", "pass")}, indent=1))
    for b in blocking:
        print("BLOCK", b)
    for w in warnings:
        print("WARN", w)
    sys.exit(0 if not blocking else 1)


if __name__ == "__main__":
    main()
