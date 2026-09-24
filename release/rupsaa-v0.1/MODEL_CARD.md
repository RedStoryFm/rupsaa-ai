---
base_model: Qwen/Qwen2.5-7B-Instruct
library_name: peft
pipeline_tag: text-generation
tags:
- lora
- qlora
- peft
- sft
- llama-factory
- bengali
- banglish
- not-for-all-audiences
language:
- bn
- en
---

# Rupsaa V0.1 — LoRA adapter

Rupsaa is an 18+ multilingual (Bengali / Banglish / English / code-switched)
conversational companion. **This repository holds only the LoRA adapter**; it
must be attached to the base model below. The application (API, web UI,
knowledge/RAG, terminology, training and evaluation tooling) lives in the
Rupsaa GitHub repository, whose `setup_rupsaa.sh` downloads this adapter
automatically.

| | |
|---|---|
| Release | `rupsaa-v0.1` (HF tag `rupsaa-v0.1`, folder `rupsaa-v0.1/`) |
| Base model | [`Qwen/Qwen2.5-7B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct) (not included here) |
| Method | Supervised fine-tuning (SFT) + QLoRA, LLaMA-Factory 0.7.1 |
| Adapter type | LoRA (PEFT 0.21.0) — never merged into the base |
| Quantization | 4-bit NF4 (bitsandbytes), bf16 compute during training; 4-bit NF4 + double quant at inference |
| LoRA rank / alpha / dropout | 16 / 32 / 0.05 |
| Target modules | down_proj, gate_proj, k_proj, o_proj, q_proj, up_proj, v_proj (all 7 attention + MLP projection types) |
| Training | 3.0 epochs, LR 0.0002, cosine, cutoff 2048, batch 2 × grad-acc 8 |
| Selected checkpoint | best eval loss (`load_best_model_at_end`) |
| Train loss (mean) / eval loss | 1.468 / 1.704 |
| Dataset | `rupsaa_v0.1` — 858 approved conversations, splits {'train': 772, 'validation': 43, 'test': 43} |
| Dataset SHA-256 | `2df533999559d5f873be9e5dc5350812e874dd18c8e4017741f5b8c18666fa2a` |
| Adapter SHA-256 | `f897bd0ba0069c5edc41b42aa96980998aa03a9108f3c885f07d4e8fa8795ae5` (161,533,192 bytes) |

## Load the adapter

```python
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

base_id = "Qwen/Qwen2.5-7B-Instruct"
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
tokenizer = AutoTokenizer.from_pretrained(base_id)
base = AutoModelForCausalLM.from_pretrained(base_id, quantization_config=bnb, device_map="auto")
model = PeftModel.from_pretrained(base, "<your-hf-username>/rupsaa", subfolder="rupsaa-v0.1", revision="rupsaa-v0.1")
model.eval()

messages = [{"role": "system", "content": "You are Rupsaa."}, {"role": "user", "content": "kemon acho?"}]
inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to(model.device)
print(tokenizer.decode(model.generate(inputs, max_new_tokens=128)[0][inputs.shape[1]:], skip_special_tokens=True))
```

With the Rupsaa application:
`git clone <rupsaa repo> && cd rupsaa-ai && bash setup_rupsaa.sh && bash scripts/start_rupsaa_v01.sh`.

## Files

- `rupsaa-v0.1/adapter_model.safetensors`, `rupsaa-v0.1/adapter_config.json` — the adapter
- `rupsaa-v0.1/trainer_*`, `*_results.json`, `training_*loss.png` — training metadata
- `rupsaa-v0.1/manifest.json` — full release manifest (code commit, environment, dataset identity)
- `rupsaa-v0.1/checksums.sha256` — SHA-256 of every published file

Intermediate checkpoints, optimizer state and base-model weights are intentionally not published.

## Known limitations

- Strong verbal tic: 'honestly'/'actually' in most replies (inherited from the V0.1 dataset; 863/1129 training replies).
- Bengali-script and Banglish replies are often incoherent or semantically wrong; English is the strongest language.
- Flirting can come out flat or dismissive.
- Occasional overclaiming of capabilities (browsing, live data).
- Held-out test loss 3.345 -> 1.515 vs base; this measures fit to the dataset style, not overall quality.
- 18+ adult-oriented persona. Not a general-purpose assistant.

## Compatibility

- Loads with transformers 4.46.3 + peft 0.21.0 + bitsandbytes 0.50.2 on torch 2.8.0+cu128 (NVIDIA L4, 23 GB).
- Base model is downloaded from the Hub on first load (Qwen/Qwen2.5-7B-Instruct, ~15 GB); the adapter is never merged.
- Chat template: Qwen ChatML via tokenizer.apply_chat_template (LLaMA-Factory template 'qwen' in training).
- Top-level adapter = best-eval checkpoint (checkpoint-100 of 135 steps, load_best_model_at_end).
- Trained with system prompt 'You are Rupsaa.'; the app serves a longer persona prompt (see V0.2 preparation report).
- LLaMA-Factory 0.7.1 GUI needs scripts/setup_llamafactory.sh (pinned gradio 4.38.1 + two compatibility patches).

## Intended use

Adult (18+) conversational companion research and product development by the
Rupsaa owner. Not intended for minors, for factual advice without retrieval
grounding, or as a general assistant. The application enforces essential hard
boundaries (e.g. anything sexual involving minors is refused before the model
is called).

License: not yet specified by the owner; the base model is released under its own license.
