#!/usr/bin/env python3
"""Rupsaa V0.2.2 — choose the checkpoint by real conversation quality (never trains, never promotes).

    python scripts/v022_select_checkpoint.py --checkpoints 80 120 160 186

One 4-bit Qwen2.5-7B-Instruct with the chosen V0.2.2 checkpoints attached side by side. Every checkpoint runs
the SAME suite through the REAL production service path (router, language control, recall note, terminology +
dance stores, V0.2 prompt) with the SAME seeds:
  - the 12-turn diagnostic session (the rescue suite + memory), seed 777 at the production temperature and
    seed 777 at 0.3
  - 5 single-turn probes (identity, Bengali dance queries, Banglish dance)
Automatic flags per reply (to point the human grader at problems, not the verdict): wrong script, intra-word
mixed-script corruption, repetition loop, expected record missing.
Writes data/production/reports/rupsaa_v0.2.2_final/checkpoint_selection.json.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402

ADAPTER = PROJECT_ROOT / "adapters/rupsaa-v0.2.2"
OUT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.2_final"
SESSION = ["hi, tumi kemon acho?", "ajke amar mood ta bhalo na", "achcha", "Strip mane ki?", "Foreplay ki?",
           "এটা বাংলায় বুঝিয়ে বলো", "amar favourite color blue", "ami ki color bolechilam?", "Belly dance ki?",
           "Kathak kothakar dance?", "এবার বাংলায় বলো", "ami age ki bolechilam?"]
SINGLES = ["tumi dekhte kemon?", "are you human?", "ভাংড়া কী?", "মাম্বো কোথাকার নাচ?", "Bhangra ta banglish e bojhao"]
RUNS = ((777, 0.8), (777, 0.3))
EXPECT = {"Strip mane ki?": "term-strip_stripping", "Foreplay ki?": "term-foreplay", "Belly dance ki?": "dance-belly_dance",
          "Kathak kothakar dance?": "dance-kathak", "ভাংড়া কী?": "dance-bhangra", "মাম্বো কোথাকার নাচ?": "dance-mambo",
          "Bhangra ta banglish e bojhao": "dance-bhangra"}
BN = re.compile(r"[ঀ-৿]")


def flags(user: str, reply: str, terms: list[str], lang: str | None) -> list[str]:
    out = []
    want = lang or ("bn" if BN.search(user) else "latin")
    want = {"banglish": "latin", "en": "latin"}.get(want, want)
    b, lat = len(BN.findall(reply)), len(re.findall(r"[A-Za-z]", reply))
    got = "bn" if b and b >= lat else ("latin" if not b else "mixed")
    if (want == "bn" and got == "latin") or (want == "latin" and got == "bn"):
        out.append(f"script {got} (wanted {want})")
    if re.search(r"[ঀ-৿][A-Za-z]|[A-Za-z][ঀ-৿]", reply):
        out.append("intra-word mixed script")
    words = reply.split()
    grams = [" ".join(words[i:i + 4]) for i in range(max(0, len(words) - 3))]
    if grams and max(grams.count(g) for g in set(grams)) >= 3:
        out.append("repetition loop")
    if user in EXPECT and EXPECT[user] not in terms:
        out.append(f"record {EXPECT[user]} missing")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoints", nargs="+", required=True)
    ap.add_argument("--out", default=str(OUT / "checkpoint_selection.json"))
    args = ap.parse_args()
    import torch
    from peft import PeftModel

    from api.services import RupsaaService
    from rupsaa.model.inference import RupsaaEngine
    from rupsaa.model.loader import load_model

    OUT.mkdir(parents=True, exist_ok=True)
    first = ADAPTER / f"checkpoint-{args.checkpoints[0]}"
    loaded = load_model(adapter_path=first, use_adapter=True)
    model = loaded.model
    if not isinstance(model, PeftModel):
        raise SystemExit("adapter did not attach")
    names = {args.checkpoints[0]: "default"}
    for c in args.checkpoints[1:]:
        model.load_adapter(str(ADAPTER / f"checkpoint-{c}"), adapter_name=f"ck{c}")
        names[c] = f"ck{c}"

    class Engine(RupsaaEngine):
        seed, n = 0, 0

        def chat(self, **kw):
            Engine.n += 1
            torch.manual_seed(self.seed + Engine.n)
            torch.cuda.manual_seed_all(self.seed + Engine.n)
            return RupsaaEngine.chat(self, **kw)

    engine = Engine(dataclasses.replace(loaded, adapter_path=str(ADAPTER)), prompt_version="v0.2")

    def session(turns, seed, temp):
        svc = RupsaaService()
        svc._engine = engine
        engine.seed, Engine.n = seed * 1000, 0
        cid, out = None, []
        for user in turns:
            r = svc.chat(message=user, conversation_id=cid, use_rag=True, temperature=temp, top_p=None, max_new_tokens=None)
            cid = r["conversation_id"]
            t = {"user": user, "reply": r["response"], "route": r.get("route"), "terms_used": r.get("terms_used", []),
                 "response_language": r.get("response_language")}
            t["flags"] = flags(user, t["reply"], t["terms_used"], t["response_language"])
            out.append(t)
        return out

    res = {"session": SESSION, "singles": SINGLES, "runs": [list(r) for r in RUNS], "results": {}}
    t0 = time.time()
    for c in args.checkpoints:
        model.set_adapter(names[c])
        res["results"][c] = []
        for seed, temp in RUNS:
            turns = session(SESSION, seed, temp) + [session([s], seed + i + 1, temp)[0] for i, s in enumerate(SINGLES)]
            res["results"][c].append({"seed": seed, "temperature": temp, "turns": turns})
            for t in turns:
                print(f"[ck{c} t{temp}] {t['user']} -> {t['reply'][:110]!r} {t['flags'] or ''}", flush=True)
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    res["flag_totals"] = {c: sum(len(t["flags"]) for run in runs for t in run["turns"]) for c, runs in res["results"].items()}
    res["runtime_seconds"] = round(time.time() - t0)
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("flag totals:", res["flag_totals"], "->", args.out, flush=True)


if __name__ == "__main__":
    main()
