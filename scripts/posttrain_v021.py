#!/usr/bin/env python3
"""Rupsaa V0.2.1 R2 — complete post-training evaluation (never trains, never promotes).

    python scripts/posttrain_v021.py [--skip-generation]

One 4-bit Qwen2.5-7B-Instruct with three LoRA adapters attached side by side (not merged):
  rupsaa_v021 = adapters/rupsaa-v0.2.1 (best checkpoint-200), rupsaa_v02, rupsaa_v01, + base (adapter off).

Loss (token-weighted assistant cross-entropy, same metric as the V0.2 report):
  A. frozen external validation 77 / test 76, B. clean V0.1-vs-V0.2 subsets 41 / 38,
  C. corrective held-out 21, D. dance held-out 12.  V0.2.1/V0.2/base see the V0.2 runtime prompt;
  V0.1 its own persona prompt with the same reference blocks.
Generation (temperature/top-p from configs/inference.yaml, fixed seeds):
  E. unseen terminology generalisation 24 (V0.2.1, V0.2, base) — the established suite
  F. through the REAL production service path (RupsaaService: router, language control, recall note,
     terminology + dance stores) for V0.2.1 and V0.2: 10 live checks, 29 supplementary checks,
     21 corrective held-out, 12 dance held-out, showcase-dance probes, and the owner's exact live
     conversation as ONE session (V0.2.1 twice with different seeds, V0.2 once).
Writes data/production/reports/rupsaa_v0.2.1_posttraining/posttrain_results.json (raw everything).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402

import scripts.posttrain_v02 as pt  # noqa: E402

V021 = PROJECT_ROOT / "adapters/rupsaa-v0.2.1"
V02 = PROJECT_ROOT / "adapters/rupsaa-v0.2"
V01 = PROJECT_ROOT / "adapters/rupsaa-v0.1"
OUT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_posttraining"
EVAL = PROJECT_ROOT / "data/production/evaluation/rupsaa_v0.2"
R2 = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.1_r2"
LOSS_VARIANTS = ("rupsaa_v021", "rupsaa_v02", "rupsaa_v01", "base")
GEN_VARIANTS = ("rupsaa_v021", "rupsaa_v02")
ADAPTER_NAME = {"rupsaa_v021": "default", "rupsaa_v02": "rupsaa_v02", "rupsaa_v01": "rupsaa_v01"}
pt.PROMPT_VERSION["rupsaa_v021"] = "v0.2"
BN = re.compile(r"[ঀ-৿]")

OWNER_LIVE = ["hi, tumi kemon acho?", "ajke amar mood ta bhalo na", "achcha", "tumi amar sathe banglish e kotha bolbe?",
              "Strip mane ki?", "strip ta ektu simple kore bojhao", "Foreplay ki?", "এটা বাংলায় বুঝিয়ে বলো",
              "amar favourite color blue", "ami ki color bolechilam?", "ami age ki bolechilam?",
              "Belly dance ki?", "belly dance ta simple kore bojhao", "Kathak kothakar dance?", "এবার বাংলায় বলো",
              "Breaking ar breakdance same?"]
SHOWCASE_SESSIONS = [
    ["Belly dance ki?", "belly dance ta simple kore bojhao"], ["Ballet kothay originate korechilo?"],
    ["Kathak kothakar dance?"], ["আমাকে কথক সম্পর্কে বলো"], ["Voguing ki?"], ["Breaking ar breakdance same?"],
    ["Haka origin kothay?"], ["Bhangra ta banglish e bojhao"], ["ভাংড়া কী?"],
]
SHOWCASE_EXPECT = {"Belly dance ki?": "dance-belly_dance", "belly dance ta simple kore bojhao": "dance-belly_dance",
                   "Ballet kothay originate korechilo?": "dance-ballet", "Kathak kothakar dance?": "dance-kathak",
                   "আমাকে কথক সম্পর্কে বলো": "dance-kathak", "Voguing ki?": "dance-voguing",
                   "Breaking ar breakdance same?": "dance-breaking_breakdance", "Haka origin kothay?": "dance-haka",
                   "Bhangra ta banglish e bojhao": "dance-bhangra", "ভাংড়া কী?": "dance-bhangra"}


class Backend(pt.Backend):
    @classmethod
    def load(cls) -> "Backend":
        from peft import PeftModel

        from rupsaa.model.loader import load_model
        loaded = load_model(adapter_path=V021, use_adapter=True)
        if not isinstance(loaded.model, PeftModel):
            raise SystemExit("V0.2.1 adapter did not attach")
        loaded.model.load_adapter(str(V02), adapter_name="rupsaa_v02")
        loaded.model.load_adapter(str(V01), adapter_name="rupsaa_v01")
        b = cls(loaded.model, loaded.tokenizer)
        b.loaded = loaded
        return b

    def _with(self, variant: str, fn):
        if variant == "base":
            with self.model.disable_adapter():
                return fn()
        self.model.set_adapter(ADAPTER_NAME[variant])
        return fn()


def make_engine(backend: Backend, variant: str):
    """A production RupsaaEngine bound to one adapter of the shared model (seeded per call)."""
    import torch

    from rupsaa.model.inference import RupsaaEngine

    adapter_dir = {"rupsaa_v021": V021, "rupsaa_v02": V02}[variant]
    loaded = dataclasses.replace(backend.loaded, adapter_path=str(adapter_dir))

    class VariantEngine(RupsaaEngine):
        seed = 0

        def chat(self, **kw):
            VariantEngine.seed += 1
            torch.manual_seed(self.seed_base + VariantEngine.seed)
            torch.cuda.manual_seed_all(self.seed_base + VariantEngine.seed)
            return backend._with(variant, lambda: RupsaaEngine.chat(self, **kw))

    eng = VariantEngine(loaded, prompt_version="v0.2")
    eng.seed_base = 0
    return eng


def service_for(engine, seed_base: int):
    from api.services import RupsaaService

    svc = RupsaaService()
    engine.seed_base = seed_base
    type(engine).seed = 0
    svc._engine = engine
    return svc


def run_session(svc, turns: list[str]) -> list[dict]:
    cid, out = None, []
    for user in turns:
        r = svc.chat(message=user, conversation_id=cid, use_rag=True, temperature=None, top_p=None, max_new_tokens=None)
        cid = r["conversation_id"]
        out.append({"user": user, "reply": r["response"], "route": r.get("route"), "terms_used": r.get("terms_used", []),
                    "response_language": r.get("response_language"), "conversation_id": cid})
    return out


# ---------------------------------------------------------------------------------------- loss

def v01_messages(messages: list[dict]) -> list[dict]:
    from rupsaa.personality.system_prompt import base_persona
    from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT
    sys_c = messages[0]["content"]
    rest = sys_c[len(V02_SYSTEM_PROMPT):] if sys_c.startswith(V02_SYSTEM_PROMPT) else ""
    return [{"role": "system", "content": base_persona("v0.1").strip() + rest}] + messages[1:]


def score(backend, rows: list[dict]) -> dict:
    """rows: {id, language, messages, v01_messages} -> overall + by-language token-weighted loss."""
    per = []
    for r in rows:
        rec = {"id": r["id"], "language": r["language"]}
        for v in LOSS_VARIANTS:
            msgs = r["v01_messages"] if v == "rupsaa_v01" else r["messages"]
            rec[f"loss_{v}"], rec["tokens"] = backend.loss(v, msgs)
        per.append(rec)
        print(f"  loss {r['id']} " + " ".join(f"{v}={rec[f'loss_{v}']:.3f}" for v in LOSS_VARIANTS), flush=True)

    def summ(rs):
        tok = sum(x["tokens"] for x in rs) or 1
        s = {"records": len(rs), "tokens": tok}
        for v in LOSS_VARIANTS:
            loss = sum(x[f"loss_{v}"] * x["tokens"] for x in rs) / tok
            s[f"loss_{v}"], s[f"ppl_{v}"] = round(loss, 4), round(math.exp(loss), 3)
        s["v021_better_than_v02"] = sum(x["loss_rupsaa_v021"] < x["loss_rupsaa_v02"] for x in rs)
        return s
    by = defaultdict(list)
    for x in per:
        by[x["language"]].append(x)
    return {"overall": summ(per), "by_language": {k: summ(v) for k, v in sorted(by.items())}, "per_record": per}


def loss_suites(backend) -> dict:
    frozen = {json.loads(line)["id"]: json.loads(line) for line in open(pt.SNAPSHOT / "frozen_records.jsonl", encoding="utf-8")}
    cand = {json.loads(line)["id"]: json.loads(line)["messages"]
            for line in open(pt.SNAPSHOT / "inputs/candidate_set.jsonl", encoding="utf-8")}
    manifests = json.loads((EVAL / "eval_manifests.json").read_text(encoding="utf-8"))
    out = {"metric": "token-weighted assistant-token cross-entropy (content + <|im_end|>), cutoff 2048; ppl = exp(loss)"}
    for block in ("A_full", "B_clean_v01_vs_v02"):
        for split in ("validation", "test"):
            ids = manifests[block][split]["ids"]
            rows = [{"id": i, "language": frozen[i]["language"], "messages": frozen[i]["messages"],
                     "v01_messages": [{"role": "system", "content": cand[i][0]["content"]}] + frozen[i]["messages"][1:]}
                    for i in ids]
            print(f"== loss {block}/{split} ({len(rows)})", flush=True)
            out[f"{block}/{split}"] = score(backend, rows)
    for name, path in (("corrective_holdout", R2 / "corrective_holdout.jsonl"), ("dance_holdout", R2 / "dance_holdout.jsonl")):
        recs = [json.loads(line) for line in open(path, encoding="utf-8")]
        rows = [{"id": r["id"], "language": r["language"], "messages": r["messages"], "v01_messages": v01_messages(r["messages"])}
                for r in recs]
        print(f"== loss {name} ({len(rows)})", flush=True)
        out[name] = score(backend, rows)
    return out


# ------------------------------------------------------------------------------------- generation

def generation_suites(backend) -> dict:
    live = json.loads((EVAL / "live_behavior_checks.json").read_text(encoding="utf-8"))
    supp = json.loads((EVAL / "posttrain_supplementary_checks.json").read_text(encoding="utf-8"))
    corr_hold = [json.loads(line) for line in open(R2 / "corrective_holdout.jsonl", encoding="utf-8")]
    dance_hold = [json.loads(line) for line in open(R2 / "dance_holdout.jsonl", encoding="utf-8")]
    res = {"sessions": {}}
    engines = {v: make_engine(backend, v) for v in GEN_VARIANTS}
    groups = [("live_checks", [(c["id"], c["turns"]) for c in live]),
              ("supplementary", [(c["id"], c["turns"]) for c in supp]),
              ("corrective_holdout", [(r["id"], [m["content"] for m in r["messages"] if m["role"] == "user"]) for r in corr_hold]),
              ("dance_holdout", [(r["id"], [m["content"] for m in r["messages"] if m["role"] == "user"]) for r in dance_hold]),
              ("showcase_dance", [(f"show-{i + 1:02d}", t) for i, t in enumerate(SHOWCASE_SESSIONS)])]
    for gi, (group, cases) in enumerate(groups):
        print(f"== sessions: {group} ({len(cases)})", flush=True)
        res["sessions"][group] = []
        for ci, (cid, turns) in enumerate(cases):
            entry = {"id": cid, "runs": {}}
            for v in GEN_VARIANTS:
                svc = service_for(engines[v], seed_base=100000 * (gi + 1) + 100 * ci)
                entry["runs"][v] = run_session(svc, turns)
            res["sessions"][group].append(entry)
            print(f"  {group} {cid}: " + " | ".join(f"{v}: {entry['runs'][v][-1]['reply'][:70]!r}" for v in GEN_VARIANTS), flush=True)
    print("== owner live conversation (one session)", flush=True)
    res["owner_live"] = {}
    for v, seeds in (("rupsaa_v021", (777, 888)), ("rupsaa_v02", (777,))):
        res["owner_live"][v] = []
        for seed in seeds:
            turns = run_session(service_for(engines[v], seed_base=seed * 1000), OWNER_LIVE)
            res["owner_live"][v].append({"seed": seed, "turns": turns})
            for t in turns:
                print(f"  [{v} s{seed}] {t['user']} -> {t['reply'][:90]!r}", flush=True)
    # isolation through the real service: a second session cannot see the first one's facts
    svc = service_for(engines["rupsaa_v021"], seed_base=424242)
    a = run_session(svc, ["amar favourite color blue"])
    b = svc.chat(message="ami ki color bolechilam?", conversation_id="1", use_rag=True, temperature=None, top_p=None, max_new_tokens=None)
    c = svc.chat(message="ami ki color bolechilam?", conversation_id=a[0]["conversation_id"], use_rag=True,
                 temperature=None, top_p=None, max_new_tokens=None)
    res["isolation"] = {"session_a": a[0]["conversation_id"], "foreign_id_request_got": b["conversation_id"],
                        "foreign_reply": b["response"], "same_session_reply": c["response"],
                        "isolated": b["conversation_id"] not in ("1", a[0]["conversation_id"])}
    print("  isolation:", res["isolation"], flush=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-generation", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"timestamp": datetime.now(timezone.utc).isoformat()}
    t0 = time.time()
    backend = Backend.load()
    print(f"model loaded in {time.time() - t0:.0f}s (4-bit base + V0.2.1 + V0.2 + V0.1 adapters, not merged)", flush=True)
    result["loss"] = loss_suites(backend)
    (OUT / "posttrain_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.skip_generation:
        cases = [json.loads(line) for line in open(EVAL / "terminology_generalization.jsonl", encoding="utf-8")]
        print("== terminology generalisation (24)", flush=True)
        result["terminology"] = pt.run_terminology_suite(backend, cases, variants=("rupsaa_v021", "rupsaa_v02", "base"))
        (OUT / "posttrain_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        result["generation"] = generation_suites(backend)
    result["runtime_seconds"] = round(time.time() - t0)
    (OUT / "posttrain_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done ->", (OUT / "posttrain_results.json").relative_to(PROJECT_ROOT))


if __name__ == "__main__":
    main()
