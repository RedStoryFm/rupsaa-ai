#!/usr/bin/env python3
"""Rupsaa V0.2 preparation: deep diagnosis of the dataset corpus + triage.

Usage:
    python scripts/v02_dataset_diagnosis.py
    python scripts/v02_dataset_diagnosis.py --out data/production/reports/rupsaa_v0.2_preparation

READ-ONLY with respect to the dataset: never changes a record, a
quality_status, the frozen V0.1 snapshot/export, or anything under
data/production/{approved,drafts,rejected}. It writes only report files:

  phrase_frequency.json        catchphrase rates by corpus/language/category/source/status/prior-audit rec.
  diversity_full_corpus.json   corpus-diversity gate over every record (all statuses)
  diversity_v01_approved.json  gate over the approved set V0.1 was exported from
  diversity_v01_train.json     gate over the frozen V0.1 train.jsonl (what the LoRA actually learned)
  openings_templates.json      top openings, transitions after dashes, response skeletons
  language_quality.json        Bengali/Banglish/code-switch issue counts by language × source
  triage.jsonl                 KEEP / REPAIR / REJECT / HUMAN_REVIEW per record (+ proposals)
  triage_summary.json          counts by classification × language × source
  projected_after_repairs.json corpus gate if KEEP + all REPAIR proposals were accepted

Review proposals with scripts/v02_repair_review.py. Nothing is approved here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import PROJECT_ROOT, default_base_dir, load_dataset_config  # noqa: E402
from rupsaa.dataset.diversity import analyze_with_config, contains_phrase, skeleton, tokenize  # noqa: E402
from rupsaa.dataset.language_quality import analyze_record, triage_record  # noqa: E402
from rupsaa.dataset.schema import ConversationRecord  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402

V01_EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.1"
V01_SNAPSHOT_APPROVED = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.1_training/approved"
PRIOR_AUDIT = PROJECT_ROOT / "data/production/reports/VOICE_AUDIT_V1_0_TRACKA_FINAL.jsonl"


def _fp(messages: list[dict]) -> str:
    msgs = [{"role": m["role"], "content": m["content"]} for m in messages]
    return hashlib.sha256(json.dumps(msgs, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def load_v01_train_records() -> list[ConversationRecord]:
    """The frozen V0.1 train split, re-joined to snapshot metadata (read-only)."""
    meta = {}
    for path in V01_SNAPSHOT_APPROVED.glob("*.json"):
        rec = ConversationRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        meta[_fp(rec.messages)] = rec
    out = []
    for line in open(V01_EXPORT / "train.jsonl", encoding="utf-8"):
        msgs = json.loads(line)["messages"]
        rec = meta.get(_fp(msgs))
        out.append(replace(rec, messages=msgs) if rec else ConversationRecord(id="unknown", messages=msgs))
    return out


def rate_table(groups: dict[str, list[str]], phrases: list[str]) -> dict:
    table = {}
    for name, texts in sorted(groups.items()):
        n = len(texts)
        table[name] = {"replies": n, **{p: round(sum(contains_phrase(t, p) for t in texts) / n, 4) for p in phrases if n}}
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="data/production/reports/rupsaa_v0.2_preparation")
    args = parser.parse_args()
    out = PROJECT_ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    cfg = load_dataset_config()
    watchlist = cfg["diversity"]["watchlist"]
    store = DatasetStore(default_base_dir())
    records = [loc.record for loc in store.list_all()]
    approved = [r for r in records if r.quality_status == "approved"]
    v01_train = load_v01_train_records()
    prior = {}
    if PRIOR_AUDIT.exists():
        for line in open(PRIOR_AUDIT, encoding="utf-8"):
            row = json.loads(line)
            prior[row["conversation_id"]] = row
    print(f"corpus: {len(records)} records ({len(approved)} approved); V0.1 train: {len(v01_train)} conversations")

    # --- 1. corpus diversity gates ---
    reports = {
        "diversity_full_corpus.json": analyze_with_config(records),
        "diversity_v01_approved.json": analyze_with_config(approved),
        "diversity_v01_train.json": analyze_with_config(v01_train),
    }
    for name, rep in reports.items():
        (out / name).write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{name}: training_ready={rep.training_ready} block={len(rep.blocking)} warn={len(rep.warnings)}")

    # --- 2. phrase frequency by dimension ---
    replies = [(r, m["content"]) for r in records for m in r.messages if m.get("role") == "assistant"]
    dims = {
        "corpus": lambda r: "all",
        "language": lambda r: r.language,
        "category": lambda r: r.category,
        "source_type": lambda r: r.source_type,
        "quality_status": lambda r: r.quality_status,
        "prior_voice_audit_recommendation": lambda r: prior.get(r.id, {}).get("recommendation", "not_audited"),
    }
    phrase_frequency = {}
    for dim, key in dims.items():
        groups: dict[str, list[str]] = defaultdict(list)
        for r, t in replies:
            groups[key(r)].append(t)
        phrase_frequency[dim] = rate_table(groups, watchlist)
    v01_texts = [m["content"] for r in v01_train for m in r.messages if m.get("role") == "assistant"]
    phrase_frequency["v01_train_export"] = {
        "replies": len(v01_texts),
        **{p: sum(contains_phrase(t, p) for t in v01_texts) for p in watchlist},
    }
    (out / "phrase_frequency.json").write_text(json.dumps(phrase_frequency, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 3. openings / transitions / templates ---
    transitions = Counter()
    for _, t in replies:
        for m in re.finditer(r"\s[-–—]\s+(\S+(?:\s+\S+)?)", t):
            transitions[" ".join(tokenize(m.group(1))[:2])] += 1
    by_lang_open: dict[str, Counter] = defaultdict(Counter)
    by_src_open: dict[str, Counter] = defaultdict(Counter)
    for r, t in replies:
        first = " ".join(tokenize(t)[:1])
        by_lang_open[r.language][first] += 1
        by_src_open[r.source_type][first] += 1
    corpus_rep = reports["diversity_full_corpus.json"]
    openings = {
        "top_openings": corpus_rep.top_openings,
        "top_opening_bigrams": corpus_rep.top_opening_bigrams,
        "top_skeletons": corpus_rep.top_skeletons,
        "top_transitions_after_dash": transitions.most_common(20),
        "openings_by_language": {k: v.most_common(8) for k, v in by_lang_open.items()},
        "openings_by_source": {k: v.most_common(8) for k, v in by_src_open.items()},
        "skeleton_by_source": {
            src: Counter(skeleton(t, watchlist) for r, t in replies if r.source_type == src).most_common(5)
            for src in sorted({r.source_type for r in records})
        },
    }
    (out / "openings_templates.json").write_text(json.dumps(openings, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- 4. language quality + triage ---
    overused = corpus_rep.overused_phrases()
    lq_counts: dict[str, Counter] = defaultdict(Counter)
    lq_records_with: dict[str, Counter] = defaultdict(Counter)
    triage = []
    for r in records:
        lq = analyze_record(r, overused)
        group = f"{r.language}|{r.source_type}"
        lq_records_with[group]["_records"] += 1
        for code in lq.codes:
            lq_records_with[group][code] += 1
        for issue in lq.issues:
            lq_counts[group][issue.code] += 1
        triage.append(triage_record(r, overused, set(prior.get(r.id, {}).get("flags", []))))
    language_quality = {
        "note": "records_with_issue = records with >=1 assistant turn raising the code; heuristic, see rupsaa/dataset/language_quality.py",
        "records_with_issue": {g: dict(c) for g, c in sorted(lq_records_with.items())},
        "turn_issue_counts": {g: dict(c) for g, c in sorted(lq_counts.items())},
    }
    (out / "language_quality.json").write_text(json.dumps(language_quality, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(out / "triage.jsonl", "w", encoding="utf-8") as f:
        for d in triage:
            f.write(json.dumps(asdict(d), ensure_ascii=False) + "\n")
    summary = {
        "classification": Counter(d.classification for d in triage),
        "by_language": defaultdict(Counter),
        "by_source": defaultdict(Counter),
        "by_status": defaultdict(Counter),
        "top_reasons": Counter(),
    }
    for d in triage:
        summary["by_language"][d.language][d.classification] += 1
        summary["by_source"][d.source_type][d.classification] += 1
        summary["by_status"][d.quality_status][d.classification] += 1
        for code in {i["code"] for i in d.issues}:
            summary["top_reasons"][f"{d.classification}:{code}"] += 1
    summary_json = {k: (dict(v) if isinstance(v, Counter) else {kk: dict(vv) for kk, vv in v.items()}) for k, v in summary.items()}
    (out / "triage_summary.json").write_text(json.dumps(summary_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print("triage:", dict(summary["classification"]))

    # --- 5. projected corpus if KEEP + every REPAIR proposal were accepted ---
    by_id = {r.id: r for r in records}
    projected = []
    for d in triage:
        if d.classification == "KEEP":
            projected.append(by_id[d.record_id])
        elif d.classification == "REPAIR":
            projected.append(replace(by_id[d.record_id], messages=d.proposed_messages))
    proj_rep = analyze_with_config(projected)
    proj = {
        "assumption": "KEEP records + all REPAIR proposals accepted; REJECT and HUMAN_REVIEW excluded. Hypothetical — nothing approved.",
        "records": len(projected),
        "by_language": Counter(r.language for r in projected),
        "by_category": Counter(r.category for r in projected),
        "diversity": proj_rep.to_dict(),
    }
    (out / "projected_after_repairs.json").write_text(json.dumps(proj, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")
    print(f"projected: {len(projected)} records, training_ready={proj_rep.training_ready}, "
          f"block={len(proj_rep.blocking)} warn={len(proj_rep.warnings)}")
    for i in proj_rep.issues[:12]:
        print("   ", i.describe())
    print(f"written to {out}")


if __name__ == "__main__":
    main()
