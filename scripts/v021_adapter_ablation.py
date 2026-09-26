#!/usr/bin/env python3
"""Same exact inputs, adapter on vs off: did the V0.2 LoRA help or hurt a skill?

    python scripts/v021_adapter_ablation.py

Takes the traced turns (system prompt + history + user message, exactly as the
app sent them; RUPSAA_TRACE_FILE of the after-fix replay) for the owner's
Strip / Forplay / Bengali-switch / recall turns and generates each with the
V0.2 adapter and with the adapter disabled (base Qwen2.5-7B-Instruct), 3 seeds,
current inference settings. No training. Writes adapter_ablation.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402

DIR = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation"
TURNS = ["Strip mane ki?", "Forplay ki?", "এটা বাংলায় বুঝিয়ে বলো", "ami ki color bolechilam?", "ami age ki bolechilam?",
         "tumi amar sathe banglish e kotha bolbe?"]
SEEDS = (101, 202, 303)


def main() -> None:
    import torch

    from rupsaa.model.generation import ChatMessage, GenerationParams, generate_reply
    from rupsaa.model.loader import load_model

    rows = [json.loads(line) for line in open(DIR / "trace_after.jsonl", encoding="utf-8")]
    first_run = rows[:11]  # one conversation, exactly as the app built it
    loaded = load_model(adapter_path=PROJECT_ROOT / "adapters/rupsaa-v0.2", use_adapter=True)
    model, tok = loaded.model, loaded.tokenizer
    params = GenerationParams.from_config()
    out = []
    for row in first_run:
        if row["user"] not in TURNS:
            continue
        msgs = ([ChatMessage("system", row["system_prompt"])] + [ChatMessage(m["role"], m["content"]) for m in row["history_passed"]]
                + [ChatMessage("user", row["user"])])
        entry = {"user": row["user"], "route": row["route"], "requested_language": row["requested_language"], "runs": {}}
        for variant in ("rupsaa_v02", "base"):
            replies = []
            for seed in SEEDS:
                torch.manual_seed(seed)
                torch.cuda.manual_seed_all(seed)
                if variant == "base":
                    with model.disable_adapter():
                        replies.append(generate_reply(model, tok, msgs, params).text)
                else:
                    replies.append(generate_reply(model, tok, msgs, params).text)
            entry["runs"][variant] = replies
            for r in replies:
                print(f"[{variant}] {row['user']} -> {r[:200]}", flush=True)
        out.append(entry)
    (DIR / "adapter_ablation.json").write_text(json.dumps({"seeds": SEEDS, "generation": vars(params), "turns": out},
                                                          ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", DIR / "adapter_ablation.json")


if __name__ == "__main__":
    main()
