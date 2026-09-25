#!/usr/bin/env python3
"""Validate, freeze and split the owner-approved Rupsaa V0.2 candidate.

Usage:
    python scripts/v02_freeze.py validate   # all pre-freeze checks, writes nothing
    python scripts/v02_freeze.py freeze     # validate, then write the frozen export + snapshot

Input: data/production/v0.2_workspace/candidate_set.jsonl — the exact content
the owner approved (built by scripts/v02_build_candidate.py) — plus the
triage/decision files that explain how each record got there.

The only transformation applied is the system message ("train as you
serve"): every record's system turn becomes exactly what the V0.2 runtime
sends, i.e. rupsaa.personality.system_prompt.build_system_prompt(
prompt_version="v0.2", ...) with the record's own retrieved-context or
terminology block re-attached. User and assistant turns are copied byte for
byte. Any system message of an unrecognised shape stops the freeze.

Outputs (freeze only; refuses to overwrite either directory):
    data/production/exports/rupsaa_v0.2/{train,validation,test}.jsonl + dataset_info.json
    data/production/snapshots/rupsaa_v0.2_training/
        V02_TRAINING_MANIFEST.json   counts, distributions, ids per split, hashes, audit, prompt
        frozen_records.jsonl         id + metadata + split + frozen messages (hashed)
        inputs/                      candidate + decision files the freeze was built from
and registers rupsaa_v0.2_{train,validation,test} in data/dataset_info.json.
Nothing under data/production/{approved,drafts,rejected}, the V0.1 export or
snapshot, or adapters/ is touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import PROJECT_ROOT, default_base_dir, load_dataset_config  # noqa: E402
from rupsaa.dataset.dedup import group_near_duplicates  # noqa: E402
from rupsaa.dataset.diversity import analyze_with_config  # noqa: E402
from rupsaa.dataset.language_quality import analyze_record  # noqa: E402
from rupsaa.dataset.schema import ConversationRecord, validate_record  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402
from rupsaa.dataset.taxonomy import LANGUAGES  # noqa: E402
from rupsaa.personality.system_prompt import build_system_prompt  # noqa: E402
from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT  # noqa: E402
from scripts.prepare_dataset import split_id_groups  # noqa: E402

WORKSPACE = PROJECT_ROOT / "data/production/v0.2_workspace"
PREP_REPORTS = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_preparation"
CANDIDATE = WORKSPACE / "candidate_set.jsonl"
TRIAGE = PREP_REPORTS / "triage.jsonl"
DECISIONS = WORKSPACE / "review_decisions.jsonl"
AUTOMATION = WORKSPACE / "repair_automation.jsonl"
KEEP_REWRITES = WORKSPACE / "keep_rewrites.jsonl"
EXPORT_DIR = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2"
SNAPSHOT_DIR = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training"
PROJECT_DATASET_INFO = PROJECT_ROOT / "data/dataset_info.json"
V01_MANIFEST = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.1_training/V01_TRAINING_MANIFEST.json"
V01_EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.1"

# What the owner approved (FINAL_HUMAN_QA / final correction pass).
EXPECTED_CONVERSATIONS = 1533
EXPECTED_ASSISTANT_REPLIES = 2144

SEED = 42
TRAIN_RATIO, VAL_RATIO = 0.90, 0.05

V01_BARE = "You are Rupsaa."
V01_RAG_PREFIX = "You are Rupsaa.\n\nRetrieved context:\n"
TERM_MARKER = "\n\nReference terminology:\n"
SPLITS = ("train", "validation", "test")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


# ---------------------------------------------------------------------------
# Metadata join: language/category/source + how each record got into V0.2
# ---------------------------------------------------------------------------

def decision_label(rid: str, t: dict | None, decisions: dict, automation: dict, keep_rewrites: dict) -> str:
    if t is None:
        return "NEW_COVERAGE"
    cls = t["classification"]
    if cls == "KEEP":
        return "KEEP_REWRITTEN" if rid in keep_rewrites else "KEEP"
    if cls == "REPAIR":
        a = automation.get(rid)
        if a and a["confidence"] == "AUTO_ACCEPT_REPAIR":
            return "AUTO_ACCEPT_REPAIR"
        d = decisions.get(rid)
        return f"REPAIR_HUMAN_REVIEWED_{d['action']}" if d else "REPAIR_UNDECIDED"
    if cls == "HUMAN_REVIEW":
        d = decisions.get(rid)
        return f"HUMAN_REVIEWED_{d['action']}" if d else "HUMAN_REVIEW_UNDECIDED"
    return cls


def load_candidate() -> list[dict]:
    store = DatasetStore(default_base_dir())
    triage = {t["record_id"]: t for t in load_jsonl(TRIAGE)}
    decisions = {d["record_id"]: d for d in load_jsonl(DECISIONS)}
    automation = {a["record_id"]: a for a in load_jsonl(AUTOMATION)}
    keep_rewrites = {k["record_id"]: k for k in load_jsonl(KEEP_REWRITES)}
    rows = []
    for c in load_jsonl(CANDIDATE):
        rid = c["id"]
        loc = store.load(rid)
        if loc is None:
            raise SystemExit(f"candidate record {rid} not found in the dataset store")
        t = triage.get(rid)
        rows.append({
            "id": rid,
            "language": loc.record.language,
            "category": loc.record.category,
            "source_type": loc.record.source_type,
            "decision": decision_label(rid, t, decisions, automation, keep_rewrites),
            "messages": c["messages"],
        })
    return rows


# ---------------------------------------------------------------------------
# Train-as-you-serve system prompt normalisation
# ---------------------------------------------------------------------------

def normalise_system(system: str) -> tuple[str, str]:
    """Returns (runtime-identical V0.2 system message, kind). Raises on any
    shape the V0.2 runtime could not have produced."""
    if system == V01_BARE:
        return build_system_prompt(prompt_version="v0.2"), "base"
    if system.startswith(V01_RAG_PREFIX):
        ctx = system[len(V01_RAG_PREFIX):]
        if not ctx.strip() or "Reference terminology:" in ctx:
            raise ValueError("retrieved-context system message with empty or mixed content")
        return build_system_prompt(prompt_version="v0.2", retrieved_context=ctx), "retrieved_context"
    if system.startswith(V02_SYSTEM_PROMPT) and TERM_MARKER in system:
        ctx = system.split(TERM_MARKER, 1)[1]
        expected = build_system_prompt(prompt_version="v0.2", terminology_context=ctx)
        if system != expected:
            raise ValueError("terminology system message differs from the runtime's terminology block format")
        return system, "terminology"
    raise ValueError(f"unrecognised system message shape: {system[:80]!r}")


def parse_term_block(system: str) -> dict:
    ctx = system.split(TERM_MARKER, 1)[1]
    fields = {}
    for line in ctx.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields[key] = value
    return fields


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def content_record(row: dict) -> ConversationRecord:
    """User/assistant turns only — every frozen record shares the same long
    system prompt, which would otherwise dominate near-duplicate similarity."""
    return ConversationRecord(
        id=row["id"], language=row["language"], category=row["category"], source_type=row["source_type"],
        quality_status="approved", messages=[m for m in row["messages"] if m["role"] != "system"],
    )


def validate(rows: list[dict]) -> dict:
    problems: list[str] = []
    report: dict = {}

    n_replies = sum(1 for r in rows for m in r["messages"] if m["role"] == "assistant")
    report["conversations"] = len(rows)
    report["assistant_replies"] = n_replies
    if len(rows) != EXPECTED_CONVERSATIONS or n_replies != EXPECTED_ASSISTANT_REPLIES:
        problems.append(f"candidate is {len(rows)} conversations / {n_replies} replies, owner approved "
                        f"{EXPECTED_CONVERSATIONS} / {EXPECTED_ASSISTANT_REPLIES}")

    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        problems.append("duplicate record ids in candidate")

    undecided = [r["id"] for r in rows if r["decision"].endswith("UNDECIDED")]
    if undecided:
        problems.append(f"{len(undecided)} undecided record(s) in candidate: {undecided[:5]}")

    malformed = []
    for r in rows:
        roles = [m["role"] for m in r["messages"]]
        rest = roles[1:]
        ok_shape = (roles[:1] == ["system"] and len(rest) >= 2 and len(rest) % 2 == 0
                    and all(role == ("user" if i % 2 == 0 else "assistant") for i, role in enumerate(rest)))
        errs = validate_record(ConversationRecord(
            id=r["id"], language=r["language"], category=r["category"], source_type=r["source_type"],
            quality_status="approved", messages=r["messages"]))
        if not ok_shape or errs or r["language"] not in LANGUAGES:
            malformed.append({"id": r["id"], "roles": roles, "errors": errs})
    report["malformed"] = malformed
    if malformed:
        problems.append(f"{len(malformed)} malformed conversation(s)")

    content = [content_record(r) for r in rows]
    fps: dict[str, list[str]] = defaultdict(list)
    for rec in content:
        fp = sha256_bytes(json.dumps(rec.messages, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        fps[fp].append(rec.id)
    exact_dupes = [v for v in fps.values() if len(v) > 1]
    report["exact_duplicate_groups"] = exact_dupes
    if exact_dupes:
        problems.append(f"{len(exact_dupes)} exact-duplicate group(s)")

    cfg = load_dataset_config()["near_duplicate"]
    groups = group_near_duplicates(content, ngram_size=cfg["ngram_size"], threshold=cfg["similarity_threshold"],
                                   max_records=max(cfg["max_records_for_full_scan"], len(content)))
    report["near_duplicate_clusters"] = [g for g in groups if len(g) > 1]

    diversity = analyze_with_config(content)
    report["diversity"] = {
        "training_ready": diversity.training_ready,
        "block": [i.describe() for i in diversity.blocking],
        "warn": [i.describe() for i in diversity.warnings],
    }
    if not diversity.training_ready:
        problems.append(f"diversity gate BLOCK: {report['diversity']['block']}")

    lq = Counter()
    corrupt = []
    for rec in content:
        codes = analyze_record(rec).codes
        lq.update(codes)
        if codes & {"FOREIGN_SCRIPT", "INTRAWORD_SCRIPT_MIX"}:
            corrupt.append(rec.id)
    report["language_quality_codes"] = dict(lq)
    report["mixed_script_corruption"] = corrupt
    if corrupt:
        problems.append(f"{len(corrupt)} record(s) with foreign-script / intra-word script corruption: {corrupt[:5]}")

    kinds = Counter()
    term_rows = []
    for r in rows:
        try:
            _, kind = normalise_system(r["messages"][0]["content"])
        except ValueError as exc:
            problems.append(f"{r['id']}: {exc}")
            continue
        kinds[kind] += 1
        if kind == "terminology":
            fields = parse_term_block(r["messages"][0]["content"])
            if not all(fields.get(k) for k in ("Term", "Category", "Definition")):
                problems.append(f"{r['id']}: terminology block missing Term/Category/Definition")
            term_rows.append(r["id"])
    report["system_message_kinds"] = dict(kinds)
    report["terminology_examples"] = len(term_rows)
    if not V02_SYSTEM_PROMPT.strip():
        problems.append("V02_SYSTEM_PROMPT is empty")

    report["problems"] = problems
    report["passed"] = not problems
    return report


# ---------------------------------------------------------------------------
# Grouped, language-stratified split
# ---------------------------------------------------------------------------

def leakage_groups(rows: list[dict], near_dup_clusters: list[list[str]]) -> list[list[str]]:
    """Union-find over every relation that should keep records on one side
    of the split: near-duplicate content, the same terminology entry, the
    same retrieved-context passage, the same opening user message."""
    parent = {r["id"]: r["id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for cluster in near_dup_clusters:
        for other in cluster[1:]:
            union(cluster[0], other)

    by_key: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        system = r["messages"][0]["content"]
        if TERM_MARKER in system:
            by_key["term:" + parse_term_block(system)["Term"].lower()].append(r["id"])
        elif system.startswith(V01_RAG_PREFIX):
            by_key["ctx:" + system[len(V01_RAG_PREFIX):].strip()].append(r["id"])
        first_user = next(m["content"] for m in r["messages"] if m["role"] == "user")
        by_key["user:" + re.sub(r"\W+", " ", first_user.lower()).strip()].append(r["id"])
    for members in by_key.values():
        for other in members[1:]:
            union(members[0], other)

    groups: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        groups[find(r["id"])].append(r["id"])
    return [sorted(g) for g in groups.values()]


def split(rows: list[dict], groups: list[list[str]]) -> dict[str, str]:
    lang = {r["id"]: r["language"] for r in rows}
    by_lang: dict[str, list[list[str]]] = defaultdict(list)
    for g in groups:
        by_lang[Counter(lang[i] for i in g).most_common(1)[0][0]].append(g)
    assignment: dict[str, str] = {}
    for language in sorted(by_lang):
        tr, va, te = split_id_groups(by_lang[language], seed=SEED, train_ratio=TRAIN_RATIO, val_ratio=VAL_RATIO)
        for name, ids in (("train", tr), ("validation", va), ("test", te)):
            for i in ids:
                assignment[i] = name
    return assignment


# ---------------------------------------------------------------------------
# Freeze
# ---------------------------------------------------------------------------

def git_state() -> dict:
    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            return None
    return {"commit": run("rev-parse", "HEAD"), "working_tree_dirty": bool(run("status", "--porcelain"))}


def make_read_only(path: Path) -> None:
    for p in [path, *path.rglob("*")]:
        if p.is_file():
            p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def sharegpt_entry(file_name: str) -> dict:
    return {
        "file_name": file_name,
        "formatting": "sharegpt",
        "columns": {"messages": "messages"},
        "tags": {"role_tag": "role", "content_tag": "content", "user_tag": "user",
                 "assistant_tag": "assistant", "system_tag": "system"},
    }


def freeze(rows: list[dict], report: dict) -> None:
    for d in (EXPORT_DIR, SNAPSHOT_DIR):
        if d.exists():
            raise SystemExit(f"{d.relative_to(PROJECT_ROOT)} already exists — a frozen dataset is never overwritten.")

    groups = leakage_groups(rows, report["near_duplicate_clusters"])
    assignment = split(rows, groups)

    frozen = []
    kinds = Counter()
    for r in sorted(rows, key=lambda x: x["id"]):
        system, kind = normalise_system(r["messages"][0]["content"])
        kinds[kind] += 1
        messages = [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"]} for m in r["messages"][1:]]
        frozen.append({**{k: r[k] for k in ("id", "language", "category", "source_type", "decision")},
                       "split": assignment[r["id"]], "messages": messages})

    # Group-level leakage check after assignment.
    group_splits = [sorted({assignment[i] for i in g}) for g in groups]
    leaking_groups = [g for g, s in zip(groups, group_splits) if len(s) > 1]
    split_fp: dict[str, set[str]] = {s: set() for s in SPLITS}
    for f in frozen:
        content = [m for m in f["messages"] if m["role"] != "system"]
        split_fp[f["split"]].add(sha256_bytes(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()))
    fp_overlap = {f"{a}&{b}": len(split_fp[a] & split_fp[b]) for a, b in
                  (("train", "validation"), ("train", "test"), ("validation", "test"))}
    if leaking_groups or any(fp_overlap.values()):
        raise SystemExit(f"leakage detected: {len(leaking_groups)} split group(s), fingerprint overlap {fp_overlap}")

    EXPORT_DIR.mkdir(parents=True)
    split_files = {}
    for s in SPLITS:
        path = EXPORT_DIR / f"{s}.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            for f in frozen:
                if f["split"] == s:
                    fh.write(json.dumps({"messages": f["messages"]}, ensure_ascii=False) + "\n")
        split_files[s] = path
    (EXPORT_DIR / "dataset_info.json").write_text(json.dumps(
        {f"rupsaa_v0.2_{s}": sharegpt_entry(f"{s}.jsonl") for s in SPLITS}, indent=2) + "\n", encoding="utf-8")

    SNAPSHOT_DIR.mkdir(parents=True)
    frozen_path = SNAPSHOT_DIR / "frozen_records.jsonl"
    with open(frozen_path, "w", encoding="utf-8") as fh:
        for f in frozen:
            fh.write(json.dumps(f, ensure_ascii=False, sort_keys=True) + "\n")
    inputs = SNAPSHOT_DIR / "inputs"
    inputs.mkdir()
    for src in (CANDIDATE, DECISIONS, KEEP_REWRITES, AUTOMATION, TRIAGE,
                PREP_REPORTS / "candidate_full_audit.json", PREP_REPORTS / "FINAL_HUMAN_QA_V02.md"):
        if src.exists():
            shutil.copy2(src, inputs / src.name)

    v01_train_ids: set[str] = set()
    if V01_MANIFEST.exists():
        v01_ids = set(json.loads(V01_MANIFEST.read_text(encoding="utf-8"))["conversation_ids"])
        v01_eval_fps = set()
        for s in ("validation", "test"):
            for line in open(V01_EXPORT / f"{s}.jsonl", encoding="utf-8"):
                v01_eval_fps.add(json.dumps(json.loads(line)["messages"][1:], sort_keys=True, ensure_ascii=False))
        # V0.1 train = V0.1 approved ids minus whatever landed in its eval splits (matched by content).
        store = DatasetStore(default_base_dir())
        for rid in v01_ids:
            loc = store.load(rid)
            if loc is None:
                continue
            if json.dumps(loc.record.messages[1:], sort_keys=True, ensure_ascii=False) not in v01_eval_fps:
                v01_train_ids.add(rid)

    def dist(key, split_name=None):
        return dict(sorted(Counter(f[key] for f in frozen if split_name in (None, f["split"])).items()))

    per_split = {}
    for s in SPLITS:
        members = [f for f in frozen if f["split"] == s]
        per_split[s] = {
            "conversations": len(members),
            "assistant_replies": sum(1 for f in members for m in f["messages"] if m["role"] == "assistant"),
            "language_distribution": dist("language", s),
            "source_distribution": dist("source_type", s),
            "terminology_examples": sum(1 for f in members if TERM_MARKER in f["messages"][0]["content"]),
            "file": str(split_files[s].relative_to(PROJECT_ROOT)),
            "file_sha256": sha256_file(split_files[s]),
            "ids": [f["id"] for f in members],
            "ids_also_in_v01_train": sorted(f["id"] for f in members if f["id"] in v01_train_ids) if s != "train" else None,
        }

    manifest = {
        "name": "rupsaa_v0.2_training",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "OWNER_APPROVED_FROZEN",
        "conversations": len(frozen),
        "assistant_replies": sum(p["assistant_replies"] for p in per_split.values()),
        "dataset_sha256": sha256_file(frozen_path),
        "dataset_sha256_definition": "sha256 of snapshots/rupsaa_v0.2_training/frozen_records.jsonl "
                                     "(one sorted-key JSON object per record, sorted by id, including split and frozen messages)",
        "export_files_sha256": {s: per_split[s]["file_sha256"] for s in SPLITS},
        "candidate_set_sha256": sha256_file(CANDIDATE),
        "split": {"seed": SEED, "ratios": {"train": TRAIN_RATIO, "validation": VAL_RATIO,
                                           "test": round(1 - TRAIN_RATIO - VAL_RATIO, 2)},
                  "method": "language-stratified, group-preserving (scripts/prepare_dataset.split_id_groups per language)",
                  "leakage_groups": {"total_groups": len(groups), "multi_record_groups": sum(1 for g in groups if len(g) > 1),
                                     "largest_group": max(len(g) for g in groups),
                                     "relations": ["near-duplicate user+assistant content (5-gram Jaccard >= 0.85)",
                                                   "same terminology entry", "same retrieved-context passage",
                                                   "same normalised first user message"]},
                  "leakage_check": {"groups_spanning_splits": 0, "content_fingerprint_overlap": fp_overlap}},
        "language_distribution": dist("language"),
        "source_distribution": dist("source_type"),
        "category_distribution": dist("category"),
        "decision_distribution": dist("decision"),
        "splits": per_split,
        "system_prompt": {
            "file": "rupsaa/personality/system_prompt_v02.py",
            "constant": "V02_SYSTEM_PROMPT",
            "text": V02_SYSTEM_PROMPT,
            "sha256": sha256_bytes(V02_SYSTEM_PROMPT.encode("utf-8")),
            "runtime_builder": "rupsaa.personality.system_prompt.build_system_prompt(prompt_version='v0.2', ...)",
            "normalisation": {
                "kinds": dict(kinds),
                "rule": "base: 'You are Rupsaa.' -> build_system_prompt(v0.2); retrieved_context: "
                        "'You are Rupsaa.\\n\\nRetrieved context:\\n<ctx>' -> build_system_prompt(v0.2, retrieved_context=<ctx>); "
                        "terminology: already V02 + runtime terminology block, verified identical. "
                        "User/assistant turns unchanged.",
            },
        },
        "final_audit": {k: report[k] for k in ("diversity", "language_quality_codes", "mixed_script_corruption",
                                                 "exact_duplicate_groups", "malformed", "terminology_examples")},
        "near_duplicate_clusters": report["near_duplicate_clusters"],
        "git": git_state(),
        "v01_untouched": {"export_dir": str(V01_EXPORT.relative_to(PROJECT_ROOT)),
                          "export_sha256": {s: sha256_file(V01_EXPORT / f"{s}.jsonl") for s in SPLITS}},
    }
    (SNAPSHOT_DIR / "V02_TRAINING_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    info = json.loads(PROJECT_DATASET_INFO.read_text(encoding="utf-8"))
    for s in SPLITS:
        info[f"rupsaa_v0.2_{s}"] = sharegpt_entry(f"production/exports/rupsaa_v0.2/{s}.jsonl")
    PROJECT_DATASET_INFO.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    make_read_only(EXPORT_DIR)
    make_read_only(SNAPSHOT_DIR)

    print(f"frozen {manifest['conversations']} conversations / {manifest['assistant_replies']} replies")
    print(f"dataset_sha256 {manifest['dataset_sha256']}")
    for s in SPLITS:
        p = per_split[s]
        print(f"  {s:10} {p['conversations']:5} conv  {p['assistant_replies']:5} replies  {p['language_distribution']}")
    print(f"system messages: {dict(kinds)}")
    print(f"wrote {EXPORT_DIR.relative_to(PROJECT_ROOT)}/, {SNAPSHOT_DIR.relative_to(PROJECT_ROOT)}/, "
          f"registered rupsaa_v0.2_* in {PROJECT_DATASET_INFO.relative_to(PROJECT_ROOT)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("validate", "freeze"))
    args = p.parse_args()

    rows = load_candidate()
    report = validate(rows)
    print(f"candidate: {report['conversations']} conversations / {report['assistant_replies']} replies")
    print(f"system messages: {report['system_message_kinds']}  terminology examples: {report['terminology_examples']}")
    print(f"diversity: training_ready={report['diversity']['training_ready']} "
          f"block={len(report['diversity']['block'])} warn={len(report['diversity']['warn'])}")
    for w in report["diversity"]["warn"]:
        print(f"    {w}")
    print(f"exact duplicate groups: {len(report['exact_duplicate_groups'])}  "
          f"near-duplicate clusters: {len(report['near_duplicate_clusters'])}  "
          f"malformed: {len(report['malformed'])}  mixed-script corruption: {len(report['mixed_script_corruption'])}")
    print(f"language-quality codes (accepted residuals): {report['language_quality_codes']}")
    if not report["passed"]:
        print("\nPRE-FREEZE VALIDATION FAILED — not freezing:")
        for prob in report["problems"]:
            print(f"  - {prob}")
        sys.exit(1)
    print("PRE-FREEZE VALIDATION PASSED")
    if args.command == "freeze":
        freeze(rows, report)


if __name__ == "__main__":
    main()
