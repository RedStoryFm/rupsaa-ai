# Rupsaa V0.3 — Gemma 3 12B IT QLoRA: training + essential live test (2026-09-28)

**Result: FAIL — STOP.** Banglish quality does not meet the owner gate. There is no retraining, and no new phase has been started.

## Training
The run was **restarted** from step 0. The previous L4 run died during its first evaluation at step 20, before any checkpoint was saved.

- **GPU:** NVIDIA RTX PRO 6000 Blackwell Server Edition, 96 GB.
- **Batching:** micro batch 4 × grad accumulation 4 = effective batch 16.
  - A probe at 8 × 2 ran out of memory at more than 93 GB.
- **Performance settings:** gradient checkpointing off, TF32 on.
- **Unchanged recipe:** frozen `rupsaa_v0.2.2` dataset (SHA verified), same LoRA r16 / α32 / dropout 0.05, NF4 with double quant, bf16, LR 1e-4 cosine, 2 epochs.
- **Speed and memory:** 186 steps, 2.2 s/step, 448 s training time (7.5 min), peak VRAM 55.5 GiB.
- **Eval loss** by step (monotonic, no overfitting):

  | Step | 20 | 40 | 60 | 80 | 100 | 120 | 140 | 160 | 180 |
  |---|---|---|---|---|---|---|---|---|---|
  | Eval loss | 2.351 | 2.140 | 2.045 | 1.988 | 1.951 | 1.946 | 1.920 | 1.912 | 1.908 |

  Mean train loss: 1.955.
- **Selected checkpoint:** the final adapter (step 186). SHA-256 `ec7a658f7dd50a353b39b865ac9ea57bb3e68d4a84ec18588a53d75fa86b7ec4`.

## Runtime bugs found and fixed (needed to serve Gemma at all; no model or training change)

1. **`rupsaa/model/loader.py`:** with quantization on, the loader set no dtype. transformers 4.57 then loaded Gemma's non-quantized layers in fp16, which gave NaN logits and a CUDA assert. The fix always passes the compute dtype (bf16), which is what every adapter was trained with.
2. **`rupsaa/model/generation.py`:** generation stopped only on `tokenizer.eos_token_id`. Gemma ends a turn with `<end_of_turn>`, so it invented further turns until it hit `max_new_tokens`. The fix stops on every end-of-turn token. Qwen is unchanged (`<|im_end|>`).
3. **Production config (`.env`, not committed):** `RUPSAA_PROMPT_VERSION=v0.2`. The app only infers v0.2 for adapters named `rupsaa-v0.2*`, but the Gemma corpus uses the v0.2 prompt.

## Live test
The 17 owner prompts went through the real production app: router, terminology/dance retrieval, recall note and adapter.

- Runs: `live_test_final.json` (server default temperature 0.8) and `live_test_final_t04.json` (temperature 0.4).

| Area | Result |
|---|---|
| Bengali (#8, #13, #14) | **PASS** — coherent and correct |
| RAG / dance facts (belly dance, Kathak, mambo, Breaking) | **PASS** |
| Memory ("ami ki color bolechilam?" → "Blue") | **PASS** |
| Language switching / follow-up carry-over | **PASS** |
| Identity ("no body", "AI, not human") | **PASS** |
| Foreplay (Banglish) | understandable |
| Strip (Banglish) | **FAIL** — the core definition is garbled or Hindi-tinged in 3 of 4 runs |
| Casual Banglish | **FAIL** — recurring malformed or incoherent phrases |

Strip examples:
- "kapro ferotwa"
- "kapde uthano"
- "kapde ulta neme"
- "stripling mane kapde fele felle dhore feleni"

Casual Banglish examples:
- "hoyto naki hoyto"
- "Achcha bolte parbe na"
- "Eta mone dorkar nai"
- "Kajol er modhhe blue ghum diyechile"
- "khubshund"

Base Gemma 3 12B (base-model selection) already showed the same Banglish weakness ("boshor kore cloth neva", "Lekhin tomar manobhyang"). An earlier checkpoint is closer to the base and has a higher eval loss, so none was tested.
