#!/usr/bin/env python3
"""Decoding-settings probe for the V0.2 adapter (no training): runs the owner
failure prompts through the real router + V0.2 prompt under several
generation settings, 2 seeds each, and writes decoding_probe.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.posttrain_v02 as pt  # noqa: E402
from rupsaa.config import PROJECT_ROOT  # noqa: E402

SETTINGS = {
    "current_t0.8_rp1.1": {"temperature": 0.8, "top_p": 0.9, "repetition_penalty": 1.1},
    "t0.5_rp1.05": {"temperature": 0.5, "top_p": 0.9, "repetition_penalty": 1.05},
    "t0.3_rp1.0": {"temperature": 0.3, "top_p": 0.9, "repetition_penalty": 1.0},
}
IDS = ["live-01", "live-03", "live-04", "live-07", "live-09", "live-10", "own-01", "own-02", "own-03", "own-05", "own-06", "own-11"]


class Probe(pt.Backend):
    overrides: dict = {}

    def generate(self, variant, messages, seed):
        import torch

        from rupsaa.model.generation import ChatMessage, GenerationParams, generate_reply
        params = GenerationParams.from_config(self.overrides)
        chat = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]
        self.model.set_adapter("default")
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        return generate_reply(self.model, self.tokenizer, chat, params).text


def main() -> None:
    ev = PROJECT_ROOT / "data/production/evaluation/rupsaa_v0.2"
    cases = json.loads((ev / "live_behavior_checks.json").read_text()) + json.loads((ev / "posttrain_supplementary_checks.json").read_text())
    cases = [c for c in cases if c["id"] in IDS]
    from peft import PeftModel

    from rupsaa.model.loader import load_model
    loaded = load_model(adapter_path=pt.V02_ADAPTER, use_adapter=True)
    assert isinstance(loaded.model, PeftModel)
    b = Probe(loaded.model, loaded.tokenizer)
    out = {}
    for name, ov in SETTINGS.items():
        b.overrides = ov
        out[name] = {}
        for seed_base in (11000, 12000):
            res = pt.run_live_checks(b, cases, variants=("rupsaa_v02",), seed_base=seed_base, tag=name)
            out[name][str(seed_base)] = [{"id": c["id"], "turns": [{"user": t["user"], "route": t["route"], "reply": t["reply"]}
                                                                   for t in c["runs"]["rupsaa_v02"]["turns"]]} for c in res["cases"]]
    dest = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_posttraining/decoding_probe.json"
    dest.write_text(json.dumps({"settings": SETTINGS, "results": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", dest)


if __name__ == "__main__":
    main()
