#!/usr/bin/env python3
"""Base-model selection, step 2: run ONE candidate base model on the 16-prompt Rupsaa session (inference only).

    PYTHONPATH=/teamspace/studios/this_studio/.basecheck_pkgs python scripts/base_select_run.py <key>

Needs a newer transformers than the project pins, supplied ONLY through PYTHONPATH for this script (the project
environment and LLaMA-Factory are untouched). Every candidate gets the SAME per-turn system prompts from
contexts.json (the real Rupsaa runtime: V0.2 prompt + the terminology/dance record production attaches +
language directive + recall note) and its OWN earlier replies as history, like the app. Greedy decoding,
repetition_penalty 1.05, max 320 new tokens, no LoRA. Writes base_model_selection/<key>.json.
"""

import gc
import json
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data/production/reports/base_model_selection"
CANDIDATES = {
    "gemma3_12b": {"id": "unsloth/gemma-3-12b-it", "official": "google/gemma-3-12b-it", "quant": "8bit"},
    "qwen3_8b": {"id": "Qwen/Qwen3-8B", "official": "Qwen/Qwen3-8B", "quant": "bf16"},
    "tiny_aya_fire": {"id": "1-800-LLMs/tiny-aya-fire", "official": "CohereLabs/tiny-aya-fire", "quant": "bf16"},
}


def load(c):
    kw = {"dtype": torch.bfloat16, "device_map": "cuda:0"}
    if c["quant"] == "8bit":
        kw["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
    if "gemma-3" in c["id"]:
        from transformers import Gemma3ForConditionalGeneration
        model = Gemma3ForConditionalGeneration.from_pretrained(c["id"], **kw)
    else:
        model = AutoModelForCausalLM.from_pretrained(c["id"], **kw)
    return model.eval(), AutoTokenizer.from_pretrained(c["id"])


def main():
    key = sys.argv[1]
    c = CANDIDATES[key]
    contexts = json.loads((DIR / "contexts.json").read_text(encoding="utf-8"))
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    try:
        model, tok = load(c)
    except Exception as e:  # noqa: BLE001
        (DIR / f"{key}.json").write_text(json.dumps({"key": key, **c, "load_success": False, "error": repr(e)}, indent=1))
        raise
    load_s, load_vram = time.time() - t0, torch.cuda.max_memory_allocated() / 2**30
    history, turns = [], []
    for ctx in contexts:
        msgs = [{"role": "system", "content": ctx["system"]}] + history + [{"role": "user", "content": ctx["user"]}]
        extra = {"enable_thinking": False} if "Qwen3" in c["id"] else {}
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt", return_dict=True, **extra)
        ids = {k: v.to(model.device) for k, v in ids.items()}
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=320, do_sample=False, repetition_penalty=1.05,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
        reply = tok.decode(out[0, ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        turns.append({"turn": ctx["turn"], "user": ctx["user"], "records": ctx["records"],
                      "requested_language": ctx["requested_language"], "reply": reply})
        history += [{"role": "user", "content": ctx["user"]}, {"role": "assistant", "content": reply}]
        print(f"[{key}] {ctx['turn']:2} USER: {ctx['user']}\n      REPLY: {reply}\n", flush=True)
    res = {"key": key, **c, "load_success": True, "load_seconds": round(load_s), "vram_gib_loaded": round(load_vram, 2),
           "vram_gib_peak": round(torch.cuda.max_memory_allocated() / 2**30, 2), "decoding": "greedy, repetition_penalty 1.05",
           "turns": turns, "total_seconds": round(time.time() - t0)}
    (DIR / f"{key}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    del model
    gc.collect()
    torch.cuda.empty_cache()
    print(json.dumps({k: res[k] for k in ("key", "vram_gib_loaded", "vram_gib_peak", "load_seconds", "total_seconds")}))


if __name__ == "__main__":
    main()
