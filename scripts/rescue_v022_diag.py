#!/usr/bin/env python3
"""Rupsaa V0.2.2 rapid-rescue diagnostic (never trains, never promotes, read-only on adapters).

    python scripts/rescue_v022_diag.py

One 4-bit Qwen2.5-7B-Instruct with LoRA adapters attached side by side (not merged): base (adapter off),
V0.2, and V0.2.1 R2 checkpoints 40/60/80/100/120/160/200. Every variant runs the SAME compact suite through
the REAL production service path (router, language control, recall note, terminology + dance stores,
V0.2 runtime prompt), with the same seeds:
  - the 9-turn owner diagnostic as ONE session, seeds 777 and 888 at the production temperature (0.8),
    and seed 777 at temperature 0.3 (is the garbling sampling noise or the learned distribution?)
  - 3 single-turn probes: physical identity, Bengali Bhangra, Banglish Bhangra
Writes data/production/reports/rupsaa_v0.2.2_rescue/diag_results.json.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402

V021 = PROJECT_ROOT / "adapters/rupsaa-v0.2.1"
V02 = PROJECT_ROOT / "adapters/rupsaa-v0.2"
OUT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.2_rescue"
CHECKPOINTS = (40, 60, 80, 100, 120, 160, 200)
VARIANTS = ("base", "v02", *(f"r2_ck{c}" for c in CHECKPOINTS))
SESSION = ["hi, tumi kemon acho?", "ajke amar mood ta bhalo na", "achcha", "Strip mane ki?", "Foreplay ki?",
           "এটা বাংলায় বুঝিয়ে বলো", "Belly dance ki?", "Kathak kothakar dance?", "এবার বাংলায় বলো"]
SINGLES = ["tumi dekhte kemon?", "ভাংড়া কী?", "Bhangra ta banglish e bojhao"]
RUNS = ((777, 0.8), (888, 0.8), (777, 0.3))


def main() -> None:
    import torch
    from peft import PeftModel

    from api.services import RupsaaService
    from rupsaa.model.inference import RupsaaEngine
    from rupsaa.model.loader import load_model

    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    loaded = load_model(adapter_path=V02, use_adapter=True)  # adapter "default" = V0.2
    model = loaded.model
    if not isinstance(model, PeftModel):
        raise SystemExit("V0.2 adapter did not attach")
    for c in CHECKPOINTS:
        model.load_adapter(str(V021 / f"checkpoint-{c}"), adapter_name=f"r2_ck{c}")
    print(f"loaded in {time.time() - t0:.0f}s", flush=True)

    def with_variant(variant, fn):
        if variant == "base":
            with model.disable_adapter():
                return fn()
        model.set_adapter("default" if variant == "v02" else variant)
        return fn()

    class Engine(RupsaaEngine):
        variant, seed, n = "base", 0, 0

        def chat(self, **kw):
            Engine.n += 1
            torch.manual_seed(self.seed + Engine.n)
            torch.cuda.manual_seed_all(self.seed + Engine.n)
            return with_variant(self.variant, lambda: RupsaaEngine.chat(self, **kw))

    engine = Engine(dataclasses.replace(loaded, adapter_path=str(V021)), prompt_version="v0.2")

    def session(turns, seed, temp):
        svc = RupsaaService()
        svc._engine = engine
        engine.seed, Engine.n = seed * 1000, 0
        cid, out = None, []
        for user in turns:
            r = svc.chat(message=user, conversation_id=cid, use_rag=True, temperature=temp, top_p=None, max_new_tokens=None)
            cid = r["conversation_id"]
            out.append({"user": user, "reply": r["response"], "route": r.get("route"),
                        "terms_used": r.get("terms_used", []), "response_language": r.get("response_language")})
        return out

    res = {"variants": VARIANTS, "runs": [list(r) for r in RUNS], "session": SESSION, "singles": SINGLES, "results": {}}
    for v in VARIANTS:
        engine.variant = v
        res["results"][v] = []
        for seed, temp in RUNS:
            turns = session(SESSION, seed, temp)
            singles = [session([s], seed + i + 1, temp)[0] for i, s in enumerate(SINGLES)]
            res["results"][v].append({"seed": seed, "temperature": temp, "session": turns, "singles": singles})
            for t in turns + singles:
                print(f"[{v} s{seed} t{temp}] {t['user']} -> {t['reply'][:100]!r}", flush=True)
        (OUT / "diag_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    res["runtime_seconds"] = round(time.time() - t0)
    (OUT / "diag_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done ->", OUT / "diag_results.json", flush=True)


if __name__ == "__main__":
    main()
