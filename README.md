# Rupsaa AI

Rupsaa is an 18+ adult-oriented, multilingual (Bengali / Banglish / English /
code-switched) conversational AI companion, built by QLoRA fine-tuning an
open-weight instruction model and pairing it with a retrieval-augmented
knowledge system.

This README documents the actual pipeline built in this repository, inside
this specific Lightning AI Studio environment. Every command below has been
run against this codebase.

## Quick start

**Current release: Rupsaa V0.1.** It's a LoRA adapter (rank 16, alpha 32, all 7 attention and MLP projection
layers) trained with SFT + QLoRA on `Qwen/Qwen2.5-7B-Instruct`. The adapter is served in 4-bit NF4 on top of the
base model and is never merged.

```bash
# Fresh install / restore (new Lightning Studio or any Linux + NVIDIA GPU box)
git clone <your-github-repo-url> rupsaa-ai
cd rupsaa-ai
hf auth login                 # only if the Hugging Face adapter repo is private
bash setup_rupsaa.sh

# Start
bash scripts/start_rupsaa_v01.sh
```

**Open:** port **5500** only.

**Verify the trained model:** send one chat message (the first one downloads and loads the base model, so it can
take minutes), then open `<5500 URL>/api/model/info`. It should show:

```json
"adapter_loaded": true,
"quantized": true
```

**Tools and docs:**
- **Knowledge Manager:** `<5500 URL>/knowledge.html`. It covers documents plus the **Terminology** tab: create,
  edit, delete, search and routing test, and **CSV/XLSX bulk import** with downloadable templates, a preview, and
  duplicate SKIP/UPDATE.
- **Backup, restore and release:** [docs/BACKUP_AND_RESTORE.md](docs/BACKUP_AND_RESTORE.md).
- **Release record:** `release/rupsaa-v0.1/` (manifest, checksums, model card).
- **Offline install check:** `python scripts/verify_installation.py`.

---

## 1. What Rupsaa is

Rupsaa's personality: cute, modern, warm, playful, confident, naturally
flirty when contextually appropriate, and knowledgeable about creator
platforms and adult-industry terminology. She mirrors whichever
language/register the user writes in — Bengali script, Banglish (Bengali in
Latin letters), English, or a mix — without being asked to.

Fine-tuning teaches personality, response style, and language behavior. RAG
supplies facts that change over time (platform policies, FAQs, docs) so
Rupsaa never has to be retrained just because a fact changed.

## 2. Architecture

```
Open-Weight Base LLM (Qwen2.5-7B-Instruct)
        |
Rupsaa QLoRA fine-tuning (adapters/)
        |
RAG knowledge system (knowledge/ -> FAISS index)
        |
Conversation management (in-memory, swappable backend)
        |
Inference layer (rupsaa/model/)
        |
FastAPI (api/)
        |
Web chat UI (web/) / future mobile app
```

Everything that shapes *how Rupsaa talks* lives in `rupsaa/personality/`.
Everything that must never be allowed lives, isolated, in
`rupsaa/guardrails/`. Neither scatters into the model, RAG, or API code.

**Three deliberately separate layers, never merged:**
- **QLoRA training data** (`data/production/` → `data/train.jsonl`) teaches
  voice, response style, and language behavior. It should not carry large
  factual payloads (platform policies, FAQs) that change over time.
- **RAG knowledge** (`knowledge/documents/` → FAISS index) supplies facts
  that change over time. Editing a document and running a reindex changes
  what Rupsaa knows immediately — it never requires retraining.
- **System prompt / runtime config** (`rupsaa/personality/system_prompt.py`)
  reinforces voice at inference time. Personality facts are not hard-coded
  scattered across Python files — see `knowledge/documents/rupsaa_identity.md`
  for owner-editable identity facts, which is RAG content, not code.

Two owner-only tools (not exposed as public features — see
`api/owner_routes.py` for the auth model) write into these layers directly
through the same production pipelines used everywhere else, never a second
parallel format:
- **Teach Rupsaa** (`web/teach.html`) — manually author conversation
  examples into the dataset pipeline as `draft`/`human_authored` records.
- **Rupsaa Knowledge** (`web/knowledge.html`) — create/edit/delete RAG
  knowledge documents and trigger a reindex.

## 3. Lightning Studio hardware detected

Captured by `scripts/environment_check.py` at build time:

| | |
|---|---|
| GPU | NVIDIA L4, 23 GB VRAM |
| Driver | 580.173.02 (CUDA 13.0) |
| PyTorch | 2.8.0+cu128 (CUDA 12.8 runtime — already installed, not touched) |
| Python | 3.12.11 |
| System RAM | 31 GB |
| Disk free | ~320 GB |

Re-run any time with:

```bash
python scripts/environment_check.py
```

## 4. Selected base model

**`Qwen/Qwen2.5-7B-Instruct`** (configurable — see `configs/model.yaml` /
`MODEL_ID` env var). Fallback: `Qwen/Qwen2.5-3B-Instruct`.

Why this model:
- **License**: Apache-2.0, no restrictive acceptable-use policy — unlike
  Gemma's or Llama's community licenses, which explicitly restrict sexual
  content. This matters directly for an 18+-oriented product.
- **Multilingual**: strong pretraining coverage across 29+ languages gives
  usable Bengali/Banglish/English/code-switching behavior before any
  fine-tuning, which QLoRA then sharpens into Rupsaa's actual voice.
- **Fits the hardware**: 7B in 4-bit NF4 QLoRA runs comfortably on the 23 GB
  L4 with room for gradient checkpointing and a 2048-token sequence length.
- **Native chat template**: ships a ChatML template that
  `tokenizer.apply_chat_template` uses directly — no custom prompt format
  to maintain.
- **Ungated**: public repo, no Hugging Face access request needed.

The model ID is read from exactly one place (`configs/model.yaml`,
overridable by the `MODEL_ID` env var, both resolved through
`rupsaa/config.py`) — it is never hard-coded elsewhere in the codebase.

## 5. Project structure

```
rupsaa-ai/
├── configs/            model.yaml, training.yaml, inference.yaml, rag.yaml
├── data/                train.jsonl / validation.jsonl / test.jsonl (generated)
│   └── examples/         starter_conversations.jsonl (hand-curated, small)
├── scripts/             environment_check, prepare/validate_dataset, train_qlora,
│                         evaluate, merge_adapter, chat, ingest_knowledge
├── rupsaa/
│   ├── config.py         single source of truth for paths/model id/env
│   ├── model/            loader.py, generation.py, inference.py
│   ├── personality/      system_prompt.py, language.py
│   ├── rag/               embeddings, document_loader, chunker, vector_store,
│   │                      retriever, pipeline
│   ├── conversation/      manager.py (swappable storage backend)
│   └── guardrails/        essential_boundaries.py (isolated, narrow scope)
├── knowledge/documents/  drop .txt/.md/.json/.pdf files here
├── knowledge/index/      FAISS index (generated)
├── adapters/             trained LoRA adapters (generated)
├── checkpoints/          training checkpoints (generated)
├── merged_model/         merged standalone models (generated)
├── api/                  FastAPI app (main.py, schemas.py, services.py)
├── web/                  lightweight chat UI (index.html, app.js, style.css)
└── tests/                pytest suite (model-free — see §18)
```

## 6. Installation

Python 3.12 + the existing CUDA 12.8 PyTorch build are already set up in
this Studio and were **not** touched. Install the rest:

```bash
cd rupsaa-ai
pip install -r requirements.txt
```

`requirements.txt` pins the exact versions verified compatible with this
environment (torch itself is intentionally left unpinned — see the comment
at the top of the file).

## 7. Environment variables

```bash
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `HUGGINGFACE_TOKEN` | Only needed for gated/private models — Qwen2.5-Instruct is public |
| `MODEL_ID` | Overrides `configs/model.yaml` base model |
| `ADAPTER_PATH` | Where to load/save the trained LoRA adapter |
| `API_HOST` / `API_PORT` | FastAPI bind address |
| `CORS_ORIGINS` | Comma-separated allowed origins — never `*` in production |
| `WEB_API_URL` | Backend URL the web UI calls (see `web/config.js`) |
| `EMBEDDING_MODEL_ID` | Overrides `configs/rag.yaml` embedding model |
| `VECTOR_STORE_DIR`, `KNOWLEDGE_DOCS_DIR` | RAG paths |

## 8. Hugging Face authentication

Not required for the default model (`Qwen/Qwen2.5-7B-Instruct` is ungated
and public). If you switch `MODEL_ID` to a gated model, set
`HUGGINGFACE_TOKEN` in `.env` — never paste a token into source code.

## 9. Dataset format

Canonical JSONL schema, one conversation per line:

```json
{"messages": [
  {"role": "system", "content": "..."},
  {"role": "user", "content": "Tumi ke?"},
  {"role": "assistant", "content": "Ami Rupsaa 💕 ..."}
]}
```

Multi-turn conversations are supported (just add more user/assistant
message pairs). The model's native chat template is applied at training and
inference time — nothing hand-rolled.

## 10. Adding conversations

`data/examples/starter_conversations.jsonl` is a **small, hand-curated
example dataset (47 conversations)** that exists to verify the pipeline —
greetings, casual chat, Bengali/Banglish/English, code-switching, creator
questions, adult terminology (kept definitional), relationship/dating,
contextual flirtiness, uncertainty handling, RAG-grounded examples, longer
explanations, and short answers. It is explicitly **not** the production
Rupsaa personality dataset — the spec calls for 5,000–15,000 curated
conversations for that, which is a separate, deliberate effort.

Add new conversations by appending JSONL lines in the same format to
`data/examples/` (or a new file), then re-run dataset prep (§13).

## 11. Dataset validation

```bash
python scripts/validate_dataset.py --input data/examples/starter_conversations.jsonl
```

Catches invalid JSON, missing/unsupported roles, empty content, broken
Unicode, exact duplicates, unusually long samples, and suspiciously
repetitive assistant replies. Prints conversation/message/approx-token
counts, a rough language distribution, and a length distribution.

## 12. Dataset preparation

```bash
python scripts/prepare_dataset.py --input data/examples/starter_conversations.jsonl --seed 42
```

Validates the source data first (refuses to proceed on hard errors), then
writes `data/train.jsonl`, `data/validation.jsonl`, `data/test.jsonl`
(80/10/10 by default, deterministic given `--seed`).

## 13. QLoRA configuration

`configs/training.yaml` — LoRA rank/alpha/dropout, learning rate, epochs,
batch size, gradient accumulation, warmup, eval/save strategy, optimizer
(`paged_adamw_8bit`). `configs/model.yaml` — quantization (NF4, double
quant, bf16 compute on this L4) and the LoRA target modules for Qwen2's
architecture (`q/k/v/o_proj`, `gate/up/down_proj`). Nothing here is
hard-coded into `scripts/train_qlora.py` — edit the YAML, not the script.

## 14. Starting training

**A smoke test has already been run and verified the pipeline** (model
load, quantization, LoRA attachment, tokenizer, dataset, chat template, one
training step) — see the final report for the result. Real training was
deliberately **not** started automatically.

To launch the real run once you have a production-sized dataset in
`data/train.jsonl` / `data/validation.jsonl`:

```bash
python scripts/train_qlora.py --config configs/training.yaml
```

## 15. Resuming training

```bash
python scripts/train_qlora.py --config configs/training.yaml --resume-from-checkpoint checkpoints/checkpoint-<N>
```

## 16. Adapter location

Final adapter: `adapters/rupsaa-v1/` (path set by
`training.final_adapter_dir` in `configs/training.yaml`). Intermediate
checkpoints: `checkpoints/`.

**Rupsaa V0.1** (trained with LLaMA-Factory, see
`configs/training/llamafactory_webui_rupsaa_v0.1.yaml`) lives in
`adapters/rupsaa-v0.1/`. Its top-level adapter is the best-eval-loss
checkpoint (`checkpoint-100`, `load_best_model_at_end`). Run the app with it:

```bash
bash scripts/start_rupsaa_v01.sh     # sets RUPSAA_ADAPTER_PATH, runs start_rupsaa.py
```

`GET /api/model/info` (via the web port) shows `configured_adapter_path` /
`configured_adapter_exists` immediately, and `adapter_loaded: true` +
`adapter_path` once the model has loaded (lazily, on the first message).

## 17. Testing the adapter

```bash
python scripts/chat.py
```

Loads the base model + adapter (if present at `ADAPTER_PATH`/
`adapters/rupsaa-v1`) through the same `RupsaaEngine` the API uses. Use
`--no-adapter` to compare against the base model.

## 18. Merging the adapter

```bash
python scripts/merge_adapter.py --adapter adapters/rupsaa-v1 --output merged_model/rupsaa-v1
```

Verifies the adapter's recorded base model matches `configs/model.yaml`
before merging, refuses to overwrite a non-empty output directory, and
never touches the original base model weights or the adapter directory.

## 19. Adding RAG documents

Drop `.txt`, `.md`, `.json`, or `.pdf` files into `knowledge/documents/`.

## 20. Rebuilding the RAG index

```bash
python scripts/ingest_knowledge.py
```

Rebuilds `knowledge/index/` from scratch from whatever is currently in
`knowledge/documents/` — safe to re-run any time; never requires retraining
Rupsaa.

**Terminology** (structured definitions, e.g. "Strip mane ki?") lives in
`knowledge/terminology/` — one JSON file per term, managed in the owner UI
(`knowledge.html` → **Terminology** tab) or via `/owner/terminology`. Terms
are live on the next message: no reindex, no retraining.

**Routing** (`rupsaa/rag/router.py`): each message is classified as
casual / memory / follow-up / terminology / knowledge / general before any
retrieval. Casual chat and "what did I say?" questions never get documents;
definition questions use terminology first. Hidden files such as
`.metadata.json` are never indexed or returned as sources.

## Dataset V0.2 preparation

```bash
python scripts/v02_dataset_diagnosis.py        # reports → data/production/reports/rupsaa_v0.2_preparation/
python scripts/v02_repair_review.py summary     # review KEEP/REPAIR/REJECT/HUMAN_REVIEW proposals
```

`scripts/dataset_audit.py` now fails and `scripts/dataset_export.py` refuses
to export when a catchphrase, opening or response template dominates the
corpus (`rupsaa/dataset/diversity.py`, thresholds in
`configs/dataset_production.yaml` → `diversity`).

## 21. Terminal chat

```bash
python scripts/chat.py --rag
```

Commands inside the chat: `/reset` (clear history), `/exit` (quit), or
Ctrl+C. Flags: `--temperature`, `--top-p`, `--top-k`, `--max-new-tokens`,
`--repetition-penalty`, `--no-adapter`.

## 22. Starting FastAPI

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The model loads lazily on the first `/chat` call, so the server itself
starts instantly (matters for health checks). Interactive docs at
`http://localhost:8000/docs`.

## 23. Starting the web chat

```bash
cd web
python3 -m http.server 5500
```

Open `http://localhost:5500`. Edit `web/config.js` (or set
`window.RUPSAA_API_URL` before it loads) to point at your FastAPI backend —
never hard-coded to `localhost` inside the app logic.

## 24. API usage

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "tumi ke?", "conversation_id": null, "use_rag": true}'
```

Endpoints: `GET /health`, `GET /model/info`, `POST /chat`,
`POST /rag/reindex`, `POST /conversation/reset`. Full schemas in
`api/schemas.py`; interactive docs at `/docs`.

## 25. Evaluation

```bash
python scripts/evaluate.py --compare-base --output evaluation_results.json
```

Runs a fixed set of starter cases (Bengali, Banglish, English, mixing,
personality, creator questions, adult terminology, concise vs. detailed,
uncertainty, RAG grounding, essential-boundary behavior) and writes both
base-model and adapter outputs side by side for you to read. It does not
auto-score quality — don't claim fine-tuning helped without reading the
output yourself.

For V0.1: `python scripts/evaluate_v01.py` runs the same cases for base vs
base + `adapters/rupsaa-v0.1` (one 4-bit load, adapter toggled, identical
seeds/params, production and training system prompts, RAG where the
pipeline retrieves context) and computes assistant-token loss on the
held-out `test.jsonl`. Results: `data/production/reports/rupsaa_v0.1_evaluation/`.

## 26. Deployment options

- **Adapter + base**: load `Qwen/Qwen2.5-7B-Instruct` + `adapters/rupsaa-v1`
  at inference time (smaller artifact to ship, needs PEFT at serve time).
- **Merged model**: `scripts/merge_adapter.py` output under `merged_model/`
  — a standalone Transformers model directory, portable to any GPU
  inference server, or uploadable to a private model repo. Nothing in
  `rupsaa/model/` is Lightning-Studio-specific.

## 27. CUDA troubleshooting

- `torch.cuda.is_available()` returning `False`: confirm `nvidia-smi` works
  in this Studio session and that you haven't reinstalled `torch` with a
  CPU-only wheel. Do not reinstall CUDA — this Studio's driver (580.173.02,
  CUDA 13.0) already supports the installed `torch==2.8.0+cu128` build.
- Version mismatch after a `pip install` of an unrelated package: run
  `python -c "import torch; print(torch.__version__)"` — if it changed from
  `2.8.0+cu128`, reinstall the pinned version from `requirements.txt`
  (torch itself isn't in that file on purpose; reinstall with
  `pip install torch==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128`
  only if actually necessary).

## 28. bitsandbytes troubleshooting

- Import errors or "no GPU support detected": confirm `bitsandbytes==0.50.2`
  is installed (`pip show bitsandbytes`) and that `torch.cuda.is_available()`
  is `True` first — bitsandbytes depends on a working CUDA torch install,
  not the other way around.
- If quantized loading fails on a different GPU later (e.g. no bf16
  support), `rupsaa/model/loader.py` already falls back to fp16 compute
  dtype automatically — check the logged dtype rather than assuming bf16.

## 29. GPU OOM troubleshooting

In order, per `configs/training.yaml`'s inline guidance:
1. Lower `training.per_device_train_batch_size` (e.g. 2 → 1).
2. Raise `training.gradient_accumulation_steps` to compensate.
3. Lower `data.max_seq_length` (e.g. 2048 → 1024).
4. Confirm `training.gradient_checkpointing: true`.
5. Switch `configs/model.yaml` `base_model_id` to the fallback
   `Qwen/Qwen2.5-3B-Instruct`.

Errors are never hidden — `scripts/train_qlora.py` lets CUDA OOM exceptions
surface with their real traceback rather than catching and masking them.

---

## Notes on the 18+ design

`rupsaa/guardrails/essential_boundaries.py` is intentionally narrow: it
blocks only sexual content involving minors, exploitation, and
non-consensual material. It does **not** filter ordinary adult
terminology, dating/relationship talk, or creator-platform subject matter —
that judgment is left to the fine-tuned model and the system prompt in
`rupsaa/personality/`. Age verification, jurisdiction-specific compliance,
and platform-policy layers can be added inside `rupsaa/guardrails/` later
without touching fine-tuning, RAG, or the API.
