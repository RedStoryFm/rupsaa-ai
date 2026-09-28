#!/usr/bin/env python3
"""Build + validate + freeze the Rupsaa V0.3 FINAL corrective dataset (never trains).

    PYTHONPATH=/teamspace/studios/this_studio/.gemma_stack python scripts/v03_build_final.py [--check-only]

Input  (read-only): data/production/exports/rupsaa_v0.2.2/  — the frozen Gemma V1 corpus (sha verified)
                    data/production/corrective/rupsaa_v0.3_final/{source_definitions,source_casual,corpus_repairs}.py
Output (new):       data/production/exports/rupsaa_v0.3_final/  train.jsonl, train_row_map.jsonl, the V1
                    validation/test/holdout files copied byte-for-byte, V03_FINAL_MANIFEST.json, VALIDATION.json

Steps: (1) the 66 hand rewrites of Banglish replies that mixed Bengali script (guarded by original text);
(2) one spelling per high-frequency Banglish word; (3) the 250 new conversations replayed through the REAL
runtime (router, terminology/dance stores, language directive, recall note — the V0.2.1/V0.2.2 builder) so
each record carries exactly the system prompt the app sends; (4) targeted validation (scripts, Hindi
leakage, kapor coverage, language switches, duplicates/templates, facts via expected records, identity,
test-prompt and holdout leakage, Gemma template + assistant-only masking + truncation); (5) freeze.
Any hard validation error aborts before anything is written.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rupsaa.rag.dance import DanceStore  # noqa: E402
from rupsaa.rag.terminology import TerminologyStore  # noqa: E402
from scripts.v021_build_corrective import replay  # noqa: E402

V1 = ROOT / "data/production/exports/rupsaa_v0.2.2"
V1_SHA = "df6277b205b83f245d4d2fe8463a6640efbff165b17f3d1560c03fc60d57fd35"
SRC = ROOT / "data/production/corrective/rupsaa_v0.3_final"
OUT = ROOT / "data/production/exports/rupsaa_v0.3_final"
SPLIT_FILES = ["train.jsonl", "validation.jsonl", "test.jsonl", "corrective_holdout.jsonl", "dance_holdout.jsonl"]
COPY_UNCHANGED = SPLIT_FILES[1:] + ["dataset_info.json"]

BN = re.compile(r"[ঀ-৿]")
LAT2 = re.compile(r"[A-Za-z]{2,}")
FOREIGN = re.compile(r"[^\W\d_A-Za-zঀ-৿À-ɏ]")  # letters from any other script (e.g. Devanagari, Arabic)
HINDI = re.compile(r"(?<![a-z])(kapde|kapda|kapro|kapad|ferotwa|thoda|badan|nahi|nahin|kya|bahut|matlab|jaldi|accha hai|"
                   r"hai na|utarna|utaar)(?![a-z])", re.I)
HUMAN = re.compile(r"\b(khaisi|kheyechi|amar chul|amar chokh|coffee khai|cha khai|ami gumai|ghumiye porechilam)\b|আমার চুল", re.I)
OWNER_TEST_PROMPTS = [
    "hi, tumi kemon acho?", "ajke amar mood ta bhalo na", "ajke amar mood bhalo na", "mon ta kharap", "achcha", "ki korcho?",
    "tumi amar sathe banglish e kotha bolbe?", "Strip mane ki?", "strip ta simple kore bojhao", "Strip mane ki? Banglish e bolo.",
    "kapor khola mane ki?", "Foreplay ki?", "Foreplay mane ki?", "eta easy kore bojhao", "Belly dance ki?",
    "Kathak kothakar dance?", "eta Banglish e bolo", "amar favourite color blue", "ami ki color bolechilam?",
    "এটা বাংলায় সহজ করে বুঝিয়ে বলো", "এবার বাংলায় বলো", "মাম্বো কোথাকার নাচ?", "Breaking ar breakdance same?",
    "what do you look like?", "are you human?", "ফোরপ্লে কী?", "কথক কোথাকার নাচ?",
]


def norm_text(s: str) -> str:
    return re.sub(r"[\s?.!।,]+", " ", s.strip().lower()).strip()


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SRC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dataset_sha(d: Path) -> str:
    return hashlib.sha256("".join(f"{sha_file(d / n)}  {n}\n" for n in SPLIT_FILES).encode()).hexdigest()


def normalize_spelling(text: str, table: dict[str, str]) -> str:
    if BN.search(text):
        return text  # Bengali-script / mixed replies are not touched
    for src, dst in table.items():
        def rep(m, dst=dst):
            w = m.group(0)
            return dst.capitalize() if w[0].isupper() else dst
        text = re.sub(rf"(?<![A-Za-z]){src}(?![A-Za-z])", rep, text, flags=re.I)
    return text


def user_wants_bengali(user: str) -> bool:
    return bool(re.search(r"(bengali|bangla|বাংলা)\s*(te|y|য়|য়)?\s*(bujhiye\s*)?(bolo|koro|kotha|likh|bolte|বলো|বলুন|কথা)",
                          user, re.I)) or bool(BN.search(user))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true", help="validate and report, write nothing")
    args = ap.parse_args()
    errors: list[str] = []
    warnings: list[str] = []

    if dataset_sha(V1) != V1_SHA:
        sys.exit("V1 dataset sha mismatch — refusing")
    rows = [json.loads(l)["messages"] for l in open(V1 / "train.jsonl", encoding="utf-8")]
    rmap = [json.loads(l) for l in open(V1 / "train_row_map.jsonl", encoding="utf-8")]
    repairs = load_module("corpus_repairs")
    norm_table = repairs.NORMALIZE

    # (1) hand rewrites
    modified: dict[int, list[str]] = collections.defaultdict(list)
    for (r, i), (guard, new) in repairs.REWRITES.items():
        old = rows[r][i]["content"]
        if rows[r][i]["role"] != "assistant" or not old.startswith(guard):
            errors.append(f"rewrite guard failed at row {r} msg {i}: {old[:40]!r}")
            continue
        rows[r][i]["content"] = new
        modified[r].append(f"msg{i}:script-mix rewrite")
    # (2) spelling normalisation (Latin assistant replies)
    spelling_changes = 0
    for r, msgs in enumerate(rows):
        for i, m in enumerate(msgs):
            if m["role"] == "assistant":
                new = normalize_spelling(m["content"], norm_table)
                if new != m["content"]:
                    m["content"] = new
                    spelling_changes += 1
                    modified[r].append(f"msg{i}:spelling")

    # (3) new conversations through the real runtime
    a, b = load_module("source_definitions"), load_module("source_casual")
    convs = a.DEFINITIONS + b.CASUAL + b.VOCAB
    ids = [cv["id"] for cv in convs]
    if len(ids) != len(set(ids)):
        errors.append("duplicate conversation ids")
    store, dance = TerminologyStore(ROOT / "knowledge/terminology"), DanceStore(ROOT / "knowledge/dance")
    new_records, route_table = [], collections.Counter()
    for cv in convs:
        cv = {**cv, "turns": [(u, normalize_spelling(r, norm_table)) for u, r in cv["turns"]]}
        rec = replay(cv, store, dance)
        final = rec["runtime_trace"][-1]
        route_table[final["route"]] += 1
        # Single-turn: the reply must be grounded in exactly the expected record(s). Multi-turn: the turn
        # that asks the definition must get them (superset ok); later follow-ups carry whatever the real
        # runtime sends — serving == training, the builder never forces knowledge the app would not attach.
        want = set(cv.get("expect_terms", []))
        first = set(rec["runtime_trace"][0]["terms_used"])
        if want and len(cv["turns"]) == 1 and set(final["terms_used"]) != want:
            errors.append(f"{cv['id']}: attaches {final['terms_used']}, expected {sorted(want)} (route {final['route']})")
        elif want and len(cv["turns"]) > 1 and not want <= first:
            errors.append(f"{cv['id']}: definition turn attaches {sorted(first)}, expected {sorted(want)}")
        new_records.append(rec)

    # (4) targeted validation
    test_norm = {norm_text(p) for p in OWNER_TEST_PROMPTS}
    held_users = set()
    for n in SPLIT_FILES[1:]:
        for line in open(V1 / n, encoding="utf-8"):
            held_users |= {norm_text(m["content"]) for m in json.loads(line)["messages"] if m["role"] == "user"}

    def pairs(msgs):
        for i in range(1, len(msgs)):
            if msgs[i]["role"] == "assistant" and msgs[i - 1]["role"] == "user":
                yield msgs[i - 1]["content"], msgs[i]["content"]

    for rec in new_records:
        for u, r in pairs(rec["messages"]):
            if norm_text(u) in test_norm:
                errors.append(f"{rec['id']}: owner test prompt used verbatim: {u!r}")
            if norm_text(u) in held_users:
                errors.append(f"{rec['id']}: user turn appears in a held-out split: {u!r}")
            if HUMAN.search(r):
                errors.append(f"{rec['id']}: human-life claim: {r[:60]!r}")
            if not BN.search(r) and "।" in r:
                errors.append(f"{rec['id']}: danda in Latin reply")
    corpus = rows + [rec["messages"] for rec in new_records]
    stats = collections.Counter()
    for msgs in corpus:
        for u, r in pairs(msgs):
            latin_user = not BN.search(u)
            if FOREIGN.search(r):
                errors.append(f"foreign-script letter in reply: {r[:60]!r}")
            if latin_user:
                stats["replies_to_latin_users"] += 1
                if BN.search(r) and LAT2.search(r):
                    errors.append(f"Bengali script mixed into reply to a Latin-script user: {u[:40]!r} -> {r[:60]!r}")
                elif BN.search(r) and not user_wants_bengali(u):
                    warnings.append(f"Bengali-script reply to a Latin-script user without a Bengali request: {u[:40]!r}")
                if not BN.search(r):
                    stats["banglish_or_english_latin_replies"] += 1
                    if HINDI.search(r):
                        errors.append(f"Hindi-style word in Latin reply: {HINDI.search(r).group(0)!r} in {r[:60]!r}")
                    if re.search(r"(?<![a-z])kapor(?![a-z])", r, re.I):
                        stats["kapor"] += 1
                    if re.search(r"kapor khola|kapor khule|kapor kholar", r, re.I):
                        stats["kapor khola"] += 1
    # template spam among the new replies: first three words
    openers = collections.Counter(" ".join(re.findall(r"[\w']+", r.lower())[:3]) for rec in new_records
                                  for _, r in pairs(rec["messages"]))
    n_new_replies = sum(openers.values())
    for op, n in openers.most_common(5):
        if n / n_new_replies > 0.06:
            warnings.append(f"new-reply opening {op!r} used {n}/{n_new_replies} times")
    dup = collections.Counter(json.dumps(m, ensure_ascii=False) for m in corpus)
    if any(v > 1 for v in dup.values()):
        errors.append(f"{sum(v > 1 for v in dup.values())} exact duplicate conversations")
    lang_switch = sum(1 for rec in new_records for u, _ in pairs(rec["messages"])
                      if re.search(r"(banglish|bengali|english|bangla)\s*(e|te)?\s*(bolo|kotha|explain)|বাংলায়", u, re.I))

    # Gemma template + assistant-only masking + truncation (same encode as training)
    template_report = {}
    try:
        from transformers import AutoTokenizer

        from scripts.gemma_train_qlora import CUTOFF, encode

        tok = AutoTokenizer.from_pretrained("google/gemma-3-12b-it")
        lens, sup, trunc = [], 0, 0
        for msgs in corpus:
            e = encode(tok, msgs)  # raises if the template is not prefix-consistent
            lens.append(len(e["input_ids"]))
            trunc += len(e["input_ids"]) == CUTOFF
            sup += sum(x != -100 for x in e["labels"])
            # assistant-only: every supervised span must decode to assistant text / end-of-turn
        probe = new_records[0]["messages"]
        e = encode(tok, probe)
        supervised = tok.decode([t for t, l in zip(e["input_ids"], e["labels"]) if l != -100])
        if probe[-1]["content"][:30] not in supervised or "You are Rupsaa" in supervised or probe[1]["content"] in supervised:
            errors.append("masking check failed: supervised tokens are not exactly the assistant replies")
        template_report = {"max_len": max(lens), "truncated": trunc, "supervised_tokens": sup, "cutoff": CUTOFF,
                           "masking_probe": supervised[:160]}
        if trunc:
            errors.append(f"{trunc} conversations would be truncated at {CUTOFF}")
    except ImportError as ex:
        errors.append(f"template check needs the Gemma stack on PYTHONPATH ({ex})")

    kapor_before = sum(bool(re.search(r"(?<![a-z])kapor(?![a-z])", m["content"], re.I))
                       for l in open(V1 / "train.jsonl", encoding="utf-8") for m in json.loads(l)["messages"]
                       if m["role"] == "assistant")
    report = {
        "v1_dataset_sha256": V1_SHA,
        "v1_train_conversations": len(rows),
        "added_conversations": len(new_records),
        "added_by_part": {"A_definitions": len(a.DEFINITIONS), "B_casual": len(b.CASUAL), "C_vocab_memory_followups": len(b.VOCAB)},
        "modified_v1_conversations": len(modified),
        "script_mix_rewrites": len(repairs.REWRITES),
        "spelling_normalised_replies": spelling_changes,
        "total_conversations": len(corpus),
        "banglish_latin_replies_total": stats["banglish_or_english_latin_replies"],
        "kapor_replies": {"before": kapor_before, "after": stats["kapor"], "kapor_khola_after": stats["kapor khola"]},
        "language_switch_turns_added": lang_switch,
        "final_turn_routes_of_new": dict(route_table),
        "template": template_report,
        "errors": errors,
        "warnings": warnings[:40],
        "warning_count": len(warnings),
    }
    print(json.dumps({k: v for k, v in report.items() if k not in ("warnings",)}, ensure_ascii=False, indent=1))
    for w in warnings[:15]:
        print("WARN", w)
    if errors:
        print(f"\nVALIDATION FAILED — {len(errors)} error(s); nothing written.")
        for e in errors[:40]:
            print("  -", e)
        sys.exit(1)
    if args.check_only:
        print("\nVALIDATION PASSED (check only; nothing written).")
        return

    # (5) freeze
    if OUT.exists() and any(OUT.iterdir()):
        sys.exit(f"{OUT} already exists — frozen artifacts are never overwritten")
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "train.jsonl", "w", encoding="utf-8") as f:
        for msgs in corpus:
            f.write(json.dumps({"messages": msgs}, ensure_ascii=False) + "\n")
    with open(OUT / "train_row_map.jsonl", "w", encoding="utf-8") as f:
        for r, m in enumerate(rmap):
            f.write(json.dumps({**m, "row": r, "v03_modifications": modified.get(r, [])}, ensure_ascii=False) + "\n")
        for k, rec in enumerate(new_records):
            f.write(json.dumps({"row": len(rows) + k, "id": rec["id"], "source": "rupsaa_v0.3_final_corrective",
                                "language": rec["language"], "category": rec["category"],
                                "runtime_trace": rec["runtime_trace"]}, ensure_ascii=False) + "\n")
    for n in COPY_UNCHANGED:
        shutil.copy2(V1 / n, OUT / n)
    sha = dataset_sha(OUT)
    manifest = {
        "name": "rupsaa_v0.3_final", "status": "FROZEN", "created_at": datetime.now(timezone.utc).isoformat(),
        "base_dataset": "rupsaa_v0.2.2 (Gemma V1)", "dataset_sha256": sha,
        "dataset_sha256_definition": "sha256 of the lines '<sha256>  <file>\\n' for " + ", ".join(SPLIT_FILES),
        "files_sha256": {n: sha_file(OUT / n) for n in SPLIT_FILES + ["train_row_map.jsonl"]},
        "held_out_splits": "validation/test/corrective_holdout/dance_holdout copied byte-for-byte from rupsaa_v0.2.2",
        "prompt_version": "v0.2", **{k: report[k] for k in report if k not in ("errors", "warnings")},
        "sources": {n: sha_file(SRC / f"{n}.py") for n in ("source_definitions", "source_casual", "corpus_repairs")},
    }
    (OUT / "V03_FINAL_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "VALIDATION.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nFROZEN {OUT.relative_to(ROOT)} — dataset sha256 {sha}")


if __name__ == "__main__":
    main()
