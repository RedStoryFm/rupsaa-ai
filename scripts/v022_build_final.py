#!/usr/bin/env python3
"""Build + quality-gate + (optionally) freeze the FINAL Rupsaa V0.2.2 training corpus.

    python scripts/v022_build_final.py            # dry run: build, gate, print what was dropped/repaired
    python scripts/v022_build_final.py --freeze   # also write data/production/exports/rupsaa_v0.2.2/

Sources (every conversation appears ONCE — no upsampling):
  1. frozen V0.2 train (1,380)                      data/production/exports/rupsaa_v0.2/train.jsonl
  2. V0.2.1 corrective (141; the 21 held-out cases excluded) + dance (24), rebuilt through the CURRENT runtime
  3. V0.2.2 corrections (100)                       data/production/corrective/rupsaa_v0.2.2_draft/draft_records.jsonl
Drops (rescue diagnosis, data/production/reports/rupsaa_v0.2.2_rescue/):
  - any conversation with a reply the manual audit labelled BAD (semantic nonsense, malformed Banglish,
    corrupted/spliced Bengali)
  - invented human body/life (audit + explicit list + embodiment patterns in all languages)
  - catchphrase replies (Heyy / bindaas / babe / baby), intra-word mixed-script corruption
  - exact duplicate conversations
Repairs (mechanical only): Bengali danda in Latin-script replies -> "."; template openers the audit flagged
("Fair,", "Interesting question -", "Notice kora eta e first/boro step।") removed from the start of a reply.
V0.2 rows keep their V0.2-runtime system prompt when it carries a knowledge block (documents cannot be
re-retrieved); a bare-prompt V0.2 row whose final turn now gets terminology/dance/recall/language context
from the current runtime is given the current runtime prompt, so training matches serving.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT  # noqa: E402
from rupsaa.rag.dance import DanceStore  # noqa: E402
from rupsaa.rag.terminology import TerminologyStore  # noqa: E402

V02 = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2"
SNAP = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/frozen_records.jsonl"
DRAFT = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.2_draft/draft_records.jsonl"
AUDIT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.2_rescue"
R2 = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.1_r2"
OUT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.2"
DATASET = "rupsaa_v0.2.2"

BN = re.compile(r"[ঀ-৿]")
HUMAN_IDS = {"rup-000080", "rup-000083", "rup-000292", "rup-000296", "rup-000531", "rup-000731", "rup-000821",
             "rup-000853", "rup-000932", "rup-001024", "rup-001212", "c021-006", "c021-027"}
EMBODIED = re.compile(
    r"\b(I ate|I had (lunch|dinner|breakfast)|I drank|my (coffee|tea|lunch|dinner|breakfast|hair|face|skin|eyes|glasses|"
    r"childhood|body|legs|hands)|when I was (a kid|little|young|a child|growing up)|I grew up|I('m| am) (sitting|lying|eating|"
    r"drinking|wearing)|I slept|I woke up|I went to (a|the)|I travel+ed|in my twenties|khaisi|kheyechi|ghumiyechilam|"
    r"chhotobelay ami|amar chhotobela)\b|আমি (খেয়েছি|ঘুমিয়েছিলাম)|আমার ছোটবেলা|ছোটবেলায় আমি", re.I)
CATCH = re.compile(r"^(heyy+|bindaas)\b|\b(babe|baby)\b|\bbindaas\b", re.I)
INTRA = re.compile(r"[ঀ-৿][A-Za-z]|[A-Za-z][ঀ-৿]")
TEMPLATE_OPENER = re.compile(
    r"^(fair( enough| observation| concern| point| worries| bhoy| frustration| signal| follow-up)?[,.!]?\s+(?:-\s*)?|"
    r"interesting (question|thought|observation|effect|pattern)[,.!]?\s*(?:-\s*)?|"
    r"notice kora (eta|ta)? ?e (first|boro|big) step[।.]\s*)", re.I)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def script(text: str) -> str:
    b, lat = len(BN.findall(text)), len(re.findall(r"[A-Za-z]", text))
    return "bn" if b and b >= lat else ("latin" if not b else "mixed")


def repair(reply: str) -> tuple[str, list[str]]:
    fixes, new = [], reply
    m = TEMPLATE_OPENER.match(new)
    if m and len(new) - m.end() > 15:
        rest = new[m.end():]
        new = rest[0].upper() + rest[1:]
        fixes.append("template opener removed")
    if not BN.search(new) and "।" in new:
        new = new.replace("।", ".")
        fixes.append("danda -> period in Latin text")
    return new, fixes


def load_sources():
    frozen = {}
    for line in open(SNAP, encoding="utf-8"):
        r = json.loads(line)
        frozen[json.dumps([m["content"] for m in r["messages"][1:]], ensure_ascii=False)] = r
    v02 = []
    for line in open(V02 / "train.jsonl", encoding="utf-8"):
        msgs = json.loads(line)["messages"]
        meta = frozen[json.dumps([m["content"] for m in msgs[1:]], ensure_ascii=False)]
        v02.append({"id": meta["id"], "source": "rupsaa_v0.2_train", "language": meta["language"],
                    "category": meta["category"], "messages": msgs})
    from scripts.v021_build_corrective import build_all
    outputs, errors = build_all()  # rebuilt through the current runtime; frozen V0.2.1 files are not touched
    if errors:
        raise SystemExit("V0.2.1 rebuild errors: " + "; ".join(errors))
    by_name = {p.name: recs for p, recs in outputs.items()}
    held_out = {json.loads(line)["id"] for line in open(R2 / "corrective_holdout.jsonl", encoding="utf-8")}
    corr = [{"id": r["id"], "source": "rupsaa_v0.2.1_corrective", "language": r["language"], "category": r["category"],
             "messages": r["messages"]} for r in by_name["corrective_records.jsonl"] if r["id"] not in held_out]
    dance = [{"id": r["id"], "source": "rupsaa_v0.2.1_dance", "language": r["language"], "category": r["category"],
              "messages": r["messages"]} for r in by_name["dance_records.jsonl"]]
    draft = []
    for line in open(DRAFT, encoding="utf-8"):
        r = json.loads(line)
        if r.get("runtime_gap"):
            raise SystemExit(f"{r['id']} still has a runtime gap: {r['runtime_gap']}")
        draft.append({"id": r["id"], "source": "rupsaa_v0.2.2_corrective", "language": r["language"],
                      "category": r["category"], "messages": r["messages"]})
    return v02, corr, dance, draft


def runtime_prompt_for(messages, store, dance):
    """The system prompt the current runtime would send on this conversation's final turn."""
    from scripts.v021_build_corrective import replay
    turns = [(u["content"], a["content"]) for u, a in zip(messages[1::2], messages[2::2])]
    return replay({"id": "x", "category": "x", "language": "x", "turns": turns}, store, dance)["messages"][0]["content"]


def build():
    v02, corr, dance, draft = load_sources()
    audit = {}
    for f in ("audit_banglish_replies.json", "audit_bengali_replies.json"):
        for r in json.loads((AUDIT / f).read_text(encoding="utf-8")):
            audit.setdefault(r["id"], []).append(r)
    bad_ids = {i for i, rs in audit.items() if any(r["label"] == "BAD" for r in rs)}
    human_ids = HUMAN_IDS | {i for i, rs in audit.items() if any("human" in (r.get("why") or "") for r in rs)}
    store = TerminologyStore(PROJECT_ROOT / "knowledge/terminology")
    dstore = DanceStore(PROJECT_ROOT / "knowledge/dance")

    kept, dropped, repairs, prompt_updates = [], Counter(), Counter(), 0
    drop_log, seen = [], set()
    for rec in v02 + corr + dance + draft:
        replies = [m["content"] for m in rec["messages"] if m["role"] == "assistant"]
        reason = None
        if rec["id"] in bad_ids:
            reason = "audit BAD reply"
        elif rec["id"] in human_ids or any(EMBODIED.search(r) for r in replies):
            reason = "invented human body/life"
        elif any(CATCH.search(r) for r in replies):
            reason = "catchphrase"
        elif any(INTRA.search(r) for r in replies):
            reason = "intra-word mixed script"
        key = json.dumps([m["content"] for m in rec["messages"][1:]], ensure_ascii=False)
        if not reason and key in seen:
            reason = "exact duplicate"
        if reason:
            dropped[reason] += 1
            drop_log.append({"id": rec["id"], "source": rec["source"], "reason": reason})
            continue
        seen.add(key)
        msgs = [dict(m) for m in rec["messages"]]
        for m in msgs:
            if m["role"] == "assistant":
                m["content"], fx = repair(m["content"])
                for f in fx:
                    repairs[f] += 1
        if rec["source"] == "rupsaa_v0.2_train" and msgs[0]["content"] == V02_SYSTEM_PROMPT:
            current = runtime_prompt_for(msgs, store, dstore)
            if current != msgs[0]["content"]:
                msgs[0]["content"] = current
                prompt_updates += 1
        kept.append({**rec, "messages": msgs})
    return kept, dropped, repairs, prompt_updates, drop_log


def gate(kept):
    """Essential pre-training checks. Returns {check: (ok, detail)}."""
    replies = [m["content"] for r in kept for m in r["messages"] if m["role"] == "assistant"]
    keys = [json.dumps(r["messages"][1:], ensure_ascii=False) for r in kept]
    reply_counts = Counter(replies)
    flood = {t: n for t, n in reply_counts.items() if n > 4}
    openers = Counter(" ".join(r.split()[:2]).lower() for r in replies)
    top_opener, top_n = openers.most_common(1)[0]
    catch = sum(bool(CATCH.search(r)) for r in replies)
    intra = sum(bool(INTRA.search(r)) for r in replies)
    embodied = sum(bool(EMBODIED.search(r)) for r in replies)
    prompts_ok = all(r["messages"][0]["role"] == "system" and r["messages"][0]["content"].startswith(V02_SYSTEM_PROMPT)
                     for r in kept)
    alternating = all([m["role"] for m in r["messages"][1:]] == ["user", "assistant"] * (len(r["messages"][1:]) // 2)
                      for r in kept)
    identity = sum(bool(re.search(r"\b(ami|I'm|I am) (ekta )?(an )?AI\b|আমি (একটা )?এআই", r)) for r in replies)
    ai_ratio = identity / len(replies)
    # RAG examples receive their context: every V0.2.2/V0.2.1 record was built through the runtime with expect_terms;
    # spot-check the terminology/dance definition questions in the whole corpus.
    from rupsaa.rag.context_builder import build_turn_knowledge
    ts, ds = TerminologyStore(PROJECT_ROOT / "knowledge/terminology"), DanceStore(PROJECT_ROOT / "knowledge/dance")
    missing = []
    for r in kept:
        last_user = r["messages"][-2]["content"]
        k = build_turn_knowledge(last_user, use_rag=False, rag_query=None, terminology=ts, dance=ds, history_messages=0)
        blocks = [x for x in (k.terminology_context, k.dance_context) if x]
        if k.route == "terminology" and k.terms_used and len(r["messages"]) == 3:
            if not all(b.splitlines()[0] in r["messages"][0]["content"] for b in blocks):
                missing.append(r["id"])
    hold = {json.loads(line)["id"] for f in ("corrective_holdout.jsonl", "dance_holdout.jsonl")
            for line in open(R2 / f, encoding="utf-8")}
    leaked = [r["id"] for r in kept if r["id"] in hold]
    return {
        "no_holdout_leakage": (not leaked, f"held-out ids in train: {leaked}"),
        "no_exact_duplicates": (len(set(keys)) == len(keys), f"{len(keys)} conversations, {len(set(keys))} unique"),
        "no_near_duplicate_flooding": (not flood, f"replies used >4 times: {len(flood)} {list(flood.items())[:3]}"),
        "no_catchphrase_domination": (catch == 0 and top_n / len(replies) < 0.05,
                                      f"catchphrase replies {catch}; top opener {top_opener!r} {top_n / len(replies):.1%}"),
        "no_mixed_script_corruption": (intra == 0, f"intra-word mixed-script replies {intra}"),
        "no_human_body_claims": (embodied == 0, f"embodiment-pattern replies {embodied}"),
        "identity_not_a_catchphrase": (0 < ai_ratio < 0.02, f"'I'm an AI' replies {identity} ({ai_ratio:.2%})"),
        "train_as_serve_prompts": (prompts_ok and alternating, "every record starts with the V0.2 runtime prompt; turns alternate"),
        "rag_examples_have_context": (not missing, f"single-turn definition records missing their block: {missing[:10]}"),
    }


def stats(kept):
    replies = [m["content"] for r in kept for m in r["messages"] if m["role"] == "assistant"]
    return {"conversations": len(kept), "assistant_replies": len(replies),
            "by_source": dict(Counter(r["source"] for r in kept)),
            "by_language_label": dict(Counter(r["language"] for r in kept)),
            "reply_script": dict(Counter(script(t) for t in replies))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()
    kept, dropped, repairs, prompt_updates, drop_log = build()
    checks = gate(kept)
    st = stats(kept)
    print(json.dumps({"stats": st, "dropped": dict(dropped), "repairs": dict(repairs),
                      "v02_prompts_updated_to_current_runtime": prompt_updates,
                      "gate": {k: [ok, d] for k, (ok, d) in checks.items()}}, ensure_ascii=False, indent=1))
    if not all(ok for ok, _ in checks.values()):
        raise SystemExit("QUALITY GATE FAILED — not frozen")
    if not args.freeze:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "train.jsonl").write_text("".join(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n"
                                             for r in kept), encoding="utf-8")
    (OUT / "train_row_map.jsonl").write_text("".join(json.dumps({"row": i, "id": r["id"], "source": r["source"],
                                                                 "language": r["language"], "category": r["category"]},
                                                                ensure_ascii=False) + "\n" for i, r in enumerate(kept)),
                                             encoding="utf-8")
    (OUT / "dropped.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in drop_log), encoding="utf-8")
    for name in ("validation.jsonl", "test.jsonl", "corrective_holdout.jsonl", "dance_holdout.jsonl"):
        (OUT / name).write_bytes((R2 / name).read_bytes())  # unchanged evaluation sets
    info = json.loads((R2 / "dataset_info.json").read_text(encoding="utf-8"))
    info = {k.replace("rupsaa_v0.2.1_r2", DATASET): v for k, v in info.items()}
    (OUT / "dataset_info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    order = ["train.jsonl", "validation.jsonl", "test.jsonl", "corrective_holdout.jsonl", "dance_holdout.jsonl"]
    files = {n: sha(OUT / n) for n in order}
    dataset_sha = hashlib.sha256("".join(f"{files[n]}  {n}\n" for n in order).encode()).hexdigest()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout.strip()
    manifest = {
        "name": DATASET, "status": "FROZEN", "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head_at_freeze": head, "dataset_sha256": dataset_sha,
        "dataset_sha256_definition": "sha256 of the lines '<sha256>  <file>\\n' for " + ", ".join(order) + " (in that order)",
        "files_sha256": files | {"train_row_map.jsonl": sha(OUT / "train_row_map.jsonl"), "dropped.jsonl": sha(OUT / "dropped.jsonl")},
        "prompt_version": "v0.2", "system_prompt_sha256": hashlib.sha256(V02_SYSTEM_PROMPT.encode()).hexdigest(),
        "stats": st, "dropped": dict(dropped), "repairs": dict(repairs),
        "v02_prompts_updated_to_current_runtime": prompt_updates,
        "weighting": "none — every conversation appears exactly once",
        "splits": {"train": "train.jsonl (LLaMA-Factory val_size 0.05, seed 42 -> internal eval slice)",
                   "external_validation": "validation.jsonl (77, unchanged)", "external_test": "test.jsonl (76, unchanged)",
                   "corrective_holdout": "21, never trained", "dance_holdout": "12, never trained"},
        "gate": {k: [ok, d] for k, (ok, d) in checks.items()},
        "training": {"config": "configs/training/llamafactory_rupsaa_v0.2.2.yaml", "base": "Qwen/Qwen2.5-7B-Instruct",
                     "fresh_lora": True, "output_dir": "adapters/rupsaa-v0.2.2"},
    }
    (OUT / "V022_TRAINING_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"FROZEN {DATASET}: {len(kept)} conversations, dataset_sha256={dataset_sha}")


if __name__ == "__main__":
    main()
