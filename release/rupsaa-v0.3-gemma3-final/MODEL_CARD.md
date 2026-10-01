---
base_model: google/gemma-3-12b-it
library_name: peft
pipeline_tag: text-generation
license: gemma
tags: [lora, qlora, peft, sft, gemma3, bengali, banglish, not-for-all-audiences]
language: [bn, en]
---

# Rupsaa — final Gemma 3 12B LoRA adapter (`rupsaa-v0.3-gemma3-final`)

Rupsaa is a multilingual (Bengali / Banglish / English) conversational companion. **This folder holds only the
LoRA adapter.** The base model `google/gemma-3-12b-it` is **not included** — obtain it separately from Hugging Face after
accepting Google's Gemma terms. The application (FastAPI, web UI, RAG knowledge, routing, memory) is in the
Rupsaa GitHub repository.

Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms. This adapter is a
Gemma derivative and its use must comply with those terms and the Gemma Prohibited Use Policy.

| | |
|---|---|
| Base model | `google/gemma-3-12b-it` (not included; gated — accept the Gemma license) |
| Adapter SHA-256 | `3c79e394578261cdb04033867a9d6a96bb20784d5b0fc9d78d20e1b057724f05` (261,982,424 bytes) |
| Method | SFT + QLoRA: 4-bit NF4 + double quant, bf16 compute; LoRA r16 / α32 / dropout 0.05 on q,k,v,o,gate,up,down of the language model |
| Training | 2 epochs, LR 0.0001 cosine, effective batch 16, 216 steps; eval loss 2.488 → 1.892 |
| Selected checkpoint | final adapter (step 216) |
| Dataset | `rupsaa_v0.3_final` — 1804 conversations (not published) |
| Dataset SHA-256 | `6eedeb105c5ebd069d59aca751a4df849767a192ad96944c6de79fbe87fbdc69` |
| Prompt version | `v0.2` persona prompt + runtime blocks (terminology / dance / recall / language directive) |
| Serving notes | enabled in production (identity + conversational style; `RUPSAA_SERVING_NOTES=0` disables) |
| Serving profile | **Rupsaa Conversational Core V1** — this adapter + v0.2 prompt + serving notes + temperature 0.55 + bf16 compute + `<end_of_turn>` stop |
| Recommended generation | temperature 0.55, top-p 0.9, top-k 50, repetition penalty 1.1 |

## Inference requirements
- transformers ≥ 4.57 (Gemma 3), peft 0.21, bitsandbytes; the Rupsaa app runs it with `PYTHONPATH=.gemma_stack`.
- Load with an explicit bf16 compute dtype (fp16 gives NaN logits with Gemma 3).
- Stop generation on `<end_of_turn>` as well as `<eos>`.
- Use the base model's tokenizer and chat template (unchanged); the system turn is folded into the first user turn.
- About 11.6 GB VRAM at 4-bit on an NVIDIA L4 (23 GB).

## Load
```python
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                         bnb_4bit_compute_dtype=torch.bfloat16)
tok = AutoTokenizer.from_pretrained("google/gemma-3-12b-it")
base = AutoModelForCausalLM.from_pretrained("google/gemma-3-12b-it", quantization_config=bnb, torch_dtype=torch.bfloat16,
                                            device_map="auto")
model = PeftModel.from_pretrained(base, "<repo>", subfolder="rupsaa-v0.3-gemma3-final", revision="rupsaa-v0.3-gemma3-final")
```

## Files
`adapter_model.safetensors`, `adapter_config.json`, `train_summary.json` (training metrics), `manifest.json`,
`checksums.sha256`. Checkpoints, optimizer state, base weights and training data are intentionally not published.

## Application layers (not in these weights)
Curated knowledge / RAG (Terminology, Dance, General Knowledge), opt-in user memory, the consent-based internet
fallback (ASK / ALLOW / DENY) and the owner Teacher Mode are parts of the Rupsaa application (Personal AI V1). They
change no weights: knowledge the owner teaches is stored as app records and retrieved at runtime, and new knowledge
does not produce a new adapter version.

## Known limitations
- Occasional awkward Banglish phrasing; a trained tendency to answer shared preferences with a question.
- Base-model identity can leak without the serving notes (e.g. "created by Google").
- Facts about dances/terminology come from the app's RAG records, not from the adapter.
