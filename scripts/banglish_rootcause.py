#!/usr/bin/env python3
"""Banglish root-cause probe for Rupsaa V0.3 (Gemma 3 12B) — analysis only, no training.

    PYTHONPATH=/teamspace/studios/this_studio/.gemma_stack python scripts/banglish_rootcause.py

One 4-bit/bf16 load of the OFFICIAL google/gemma-3-12b-it (exactly as served) + the V0.3 adapter;
"base" = the same weights with the adapter disabled. For 5 failing Banglish prompts it builds the
real runtime system prompts (router, terminology, language control, v0.2 persona — the same code
path as the app) and compares base vs trained under greedy and runtime sampling (T=0.8, fixed
seeds). It also scores candidate "Strip mane ..." answers by log-likelihood (model preference,
independent of sampling luck) and shows tokenizer splits. Writes
data/production/reports/rupsaa_v0.3_gemma/banglish_rootcause.json.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rupsaa.conversation.language_control import directive_for  # noqa: E402
from rupsaa.personality.system_prompt import build_system_prompt  # noqa: E402
from rupsaa.rag.context_builder import build_turn_knowledge  # noqa: E402
from rupsaa.rag.dance import DanceStore  # noqa: E402
from rupsaa.rag.terminology import TerminologyStore  # noqa: E402

BASE = "google/gemma-3-12b-it"
ADAPTER = ROOT / "adapters/rupsaa-v0.3-gemma3"
OUT = ROOT / "data/production/reports/rupsaa_v0.3_gemma/banglish_rootcause.json"
PROMPTS = ["hi, tumi kemon acho?", "ajke amar mood ta bhalo na", "tumi amar sathe banglish e kotha bolbe?",
           "Strip mane ki?", "strip ta simple kore bojhao"]
STRIP_CANDIDATES = [
    "Strip mane kapor khola.",          # the training corpus wording (Bengali 'kapor')
    "Strip mane kapor khule fela.",
    "Strip mane kapde khola.",          # Hindi 'kapde'
    "Strip mane kapde utarna.",         # Hindi
    "Strip mane kapde uthano.",         # seen in V1 output
    "Strip mane kapro ferotwa.",        # seen in V1 output
]
TOKEN_WORDS = ["kapor", "kapde", "khola", "kemon acho", "bhalo achi", "bojhao", "shundor", "kichu", "কাপড় খোলা",
               "ভালো আছি"]


@dataclass
class Msg:
    role: str
    content: str


def systems() -> list[str]:
    ts, ds = TerminologyStore(ROOT / "knowledge/terminology"), DanceStore(ROOT / "knowledge/dance")
    history, prev, lang, out = [], None, None, []
    for user in PROMPTS:
        k = build_turn_knowledge(user, use_rag=False, rag_query=None, terminology=ts, previous_terms=prev,
                                 history_messages=len(history), history=history, language_state=lang, dance=ds)
        prev = k.terms_used or (prev if k.route in ("followup", "memory") else None)
        lang = k.language_state
        out.append(build_system_prompt(prompt_version="v0.2", terminology_context=k.terminology_context,
                                       conversation_note=k.conversation_note,
                                       language_directive=directive_for(k.language_state if k.language else None),
                                       dance_context=k.dance_context))
        history += [Msg("user", user), Msg("assistant", "<reply>")]
    return out


def main() -> None:
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    tok = AutoTokenizer.from_pretrained(BASE)
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                           bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(BASE, quantization_config=q, torch_dtype=torch.bfloat16,
                                                 device_map={"": 0})
    model = PeftModel.from_pretrained(model, str(ADAPTER)).eval()
    stop = [tok.eos_token_id, tok.convert_tokens_to_ids("<end_of_turn>")]
    sys_prompts = systems()

    def run(use_adapter: bool, sample: bool, seed: int) -> list[str]:
        history, replies = [], []
        for system, user in zip(sys_prompts, PROMPTS):
            msgs = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user}]
            ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to(model.device)
            kw = dict(max_new_tokens=160, eos_token_id=stop, pad_token_id=tok.pad_token_id, repetition_penalty=1.1)
            kw.update(do_sample=True, temperature=0.8, top_p=0.9, top_k=50) if sample else kw.update(do_sample=False)
            torch.manual_seed(seed)
            with torch.no_grad():
                if use_adapter:
                    out = model.generate(ids, **kw)
                else:
                    with model.disable_adapter():
                        out = model.generate(ids, **kw)
            reply = tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True).strip()
            replies.append(reply)
            history += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
        return replies

    def score(use_adapter: bool) -> list[dict]:
        """Mean log-prob per token of each candidate reply to 'Strip mane ki?' (real turn-4 system prompt)."""
        msgs = [{"role": "system", "content": sys_prompts[3]}, {"role": "user", "content": PROMPTS[3]}]
        prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True)
        res = []
        for cand in STRIP_CANDIDATES:
            c = tok(cand, add_special_tokens=False)["input_ids"]
            ids = torch.tensor([prompt + c], device=model.device)
            with torch.no_grad():
                if use_adapter:
                    logits = model(ids).logits
                else:
                    with model.disable_adapter():
                        logits = model(ids).logits
            lp = torch.log_softmax(logits[0, len(prompt) - 1:-1].float(), -1)
            tok_lp = lp.gather(1, torch.tensor(c, device=model.device)[:, None])[:, 0]
            res.append({"candidate": cand, "mean_logprob": round(tok_lp.mean().item(), 3),
                        "total_logprob": round(tok_lp.sum().item(), 2), "tokens": len(c)})
        return res

    result = {"prompts": PROMPTS, "generations": {}, "strip_likelihood": {}, "tokenizer": {}}
    for label, adapter in (("base", False), ("trained_v1", True)):
        result["generations"][label] = {"greedy": run(adapter, False, 0),
                                        **{f"sample_T0.8_seed{s}": run(adapter, True, s) for s in (1, 2, 3)}}
        result["strip_likelihood"][label] = score(adapter)
    for w in TOKEN_WORDS:
        ids = tok(w, add_special_tokens=False)["input_ids"]
        result["tokenizer"][w] = tok.convert_ids_to_tokens(ids)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for label, runs in result["generations"].items():
        print(f"\n######## {label}")
        for name, replies in runs.items():
            print(f"-- {name}")
            for u, r in zip(PROMPTS, replies):
                print(f"   U: {u}\n      {r.replace(chr(10), ' / ')[:260]}")
    print("\n######## Strip likelihood (mean log-prob per token; higher = preferred)")
    for label, rows in result["strip_likelihood"].items():
        print(label, [(r["candidate"], r["mean_logprob"]) for r in rows])
    print("\n######## tokenizer", json.dumps(result["tokenizer"], ensure_ascii=False))


if __name__ == "__main__":
    main()
