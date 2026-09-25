# Rupsaa V0.2 — pre-training report

**Status:** frozen and ready to train. **Nothing has been trained.** No optimizer step has been run, no adapter has been merged, and V0.1 has not been touched.

**Date:** 2026-09-25

**Reproduce:**

```
python scripts/v02_freeze.py validate        # pre-freeze checks (freeze itself refuses to overwrite)
HF_HUB_OFFLINE=1 python scripts/v02_pretrain_smoke.py   # LLaMA-Factory data pipeline, tokenizer only
python -m pytest -q                           # 313 tests
```

---

## 1. Frozen dataset

| | |
|---|---|
| Conversations | **1533** |
| Assistant replies | **2144** |
| Dataset SHA-256 | `96e0125e39ab2754c8540a29b6d3fee0a3132d46ae72adb9a4c3c7dcd067da33` |
| SHA-256 definition | `frozen_records.jsonl`: one sorted-key JSON object per record, sorted by id, with split and frozen messages |
| Approved candidate SHA-256 | `f3e8875d16316ec4182bc659b0fb15fa66d3796d55c4ebe55522aa24c9029bfa` (`candidate_set.jsonl`; a rebuild gave the same hash) |
| Export | `data/production/exports/rupsaa_v0.2/{train,validation,test}.jsonl` (read-only) |
| Snapshot | `data/production/snapshots/rupsaa_v0.2_training/` with `V02_TRAINING_MANIFEST.json`, `frozen_records.jsonl` and `inputs/` (read-only) |
| Git | Frozen from base commit `4043342` (recorded in the manifest). The training state is committed and tagged `rupsaa-v0.2-training`; the commit SHA is in `release/rupsaa-v0.2/TRAINING_COMMIT.json`. |

`scripts/v02_freeze.py` refuses to write if either output directory already exists.

**Language:** English 468, Banglish 434, Bengali 400, Mixed 231.

**Source:** synthetic_curated 1005, imported 507, human_authored 21.

**Decision:** AUTO_ACCEPT_REPAIR 760, KEEP 472, REPAIR→reviewed 116 (115 accept, 1 edit), HUMAN_REVIEWED 90 (42 accept, 31 edit, 17 keep-original), NEW_COVERAGE 59, KEEP_REWRITTEN 36.

### Pre-freeze validation — PASSED

| Check | Result |
|---|---|
| Counts equal the owner approval (1533 / 2144) | yes |
| Diversity gate | **PASS**, 0 BLOCK, 3 documented WARN (§7) |
| Exact duplicates (user + assistant content) | 0 |
| Malformed conversations (roles, order, schema, language) | 0 |
| Foreign-script / intra-word script corruption | 0 |
| Undecided records | 0 |
| System messages of an unrecognised shape | 0 |
| Terminology examples with a valid Term/Category/Definition block | 30 / 30 |

These residual language-quality flags were accepted during review. They count records, not failures: LANGUAGE_MISMATCH 35, ENGLISH_CALQUE 22, SCRIPT_INCONSISTENT 4, QUESTION_UNANSWERED 2.

### The only transformation in the freeze: the system turn

User and assistant turns are copied byte for byte. Each system turn is replaced with exactly what the V0.2 runtime sends.

| Candidate system turn | Records | Frozen system turn |
|---|---|---|
| `You are Rupsaa.` | 1485 | `build_system_prompt(prompt_version="v0.2")`, which is `V02_SYSTEM_PROMPT` |
| `You are Rupsaa.\n\nRetrieved context:\n<ctx>` | 18 | `build_system_prompt(prompt_version="v0.2", retrieved_context=<ctx>)` |
| V02 prompt + terminology block | 30 | Checked equal to `build_system_prompt(prompt_version="v0.2", terminology_context=<block>)` and left unchanged |

## 2. Splits

The split is language-stratified and group-preserving, with seed 42. Groups are joined by four relations:
- near-duplicate content (5-gram Jaccard ≥ 0.85, computed on user and assistant turns only)
- the same terminology entry
- the same retrieved passage
- the same opening user message

That gives 1508 groups, 17 of them with more than one record; the largest has 5.

| Split | Conversations | Replies | Banglish | Bengali | English | Mixed | Terminology examples |
|---|---|---|---|---|---|---|---|
| train | **1380** (90.0%) | 1938 | 389 | 360 | 422 | 209 | 30 |
| validation | **77** (5.0%) | 103 | 23 | 20 | 23 | 11 | 0 |
| test | **76** (5.0%) | 103 | 22 | 20 | 23 | 11 | 0 |

**Leakage: PASS.**
- 0 groups span splits.
- 0 content-fingerprint overlap between any two splits.
- The one near-duplicate pair (rup-001503 / rup-001514, both "gaslighting" in Banglish) stays together in train.

The frozen validation and test files are not referenced by the training config, so nothing trains on them.

## 3. Train-as-you-serve: PASS

- **Prompt file:** `rupsaa/personality/system_prompt_v02.py`, constant `V02_SYSTEM_PROMPT`, SHA-256 `ef1d8fd4b16a04f9b6754d7cee623c9b4e8779c6dd75cfc0d2c1f88625f526a4`.
- **Training:** LLaMA-Factory 0.7.1's sharegpt loader takes each record's first `system` message as that sample's system prompt (`data/aligner.py` `convert_sharegpt`). The qwen template's default `You are a helpful assistant.` is never used.
- **Runtime:** `build_system_prompt()` now takes a `prompt_version` argument.
  - The engine infers the version from the adapter it actually loaded: `adapters/rupsaa-v0.2` gives `v0.2`, anything else gives `v0.1`.
  - `RUPSAA_PROMPT_VERSION` overrides the inference.
  - V0.1 serving is byte-identical to before; that's tested.
  - This rules out a silent return of the V0.1 mismatch.
- **Token-level proof (smoke check):**
  - For **1380 / 1380** training rows, LLaMA-Factory's formatted prompt tokens equal `tokenizer.apply_chat_template(...)` on the same messages. That's the call the runtime makes.
  - 0 rows use `You are Rupsaa.`, and no row contains the qwen default prompt.

## 4. Terminology training format: PASS

- The block format matches the runtime `TermRecord.to_context()` block: `Term / Also called / Category / Definition / Details / Owner's guidance`. It sits under the runtime `TERMINOLOGY_INSTRUCTIONS` and the `Reference terminology:` header.
- All 30 blocks survive LLaMA-Factory formatting intact.
- All 30 are in train, including the Strip and Foreplay families.

## 5. Pre-training smoke validation: 17 / 17 PASS

The smoke check ran LLaMA-Factory's own parser and data pipeline with the Qwen tokenizer only. No model weights were loaded and 0 optimizer steps ran. Output: `smoke_check.json`.

- The frozen export SHA-256 matches the manifest.
- The config parses; the dataset is `rupsaa_v0.2_train`; the output is `adapters/rupsaa-v0.2`, which is absent, so there's no overwrite risk.
- QLoRA settings are 4-bit NF4 with double quantization, gradient checkpointing, bf16 and paged_adamw_8bit. LoRA is r16 / α32 / dropout 0.05 on all 7 projections.
- 1380 of 1380 rows survive preprocessing. The resplit gives 1311 / 69, which is 82 steps per epoch and 164 in total.
- Every example starts with its V0.2 system turn, and all 30 terminology blocks survive.
- SFT labels equal exactly the assistant turns plus `<|im_end|>` in every row, with nothing from system or user turns.
- The longest sample is 848 tokens against the 2048 cutoff; 0 were truncated.
- The config for scoring on the frozen validation split parses (`do_train: false`).

**GPU memory (L4, 23 GB):**
- This is the V0.1 configuration unchanged: same model, 4-bit quantization, batch 2, cutoff 2048 and gradient checkpointing. V0.1 trained to completion on this GPU.
- V0.2 samples are longer because of the V02 prompt, but the longest is 848 tokens. That is far below the cutoff the memory budget was sized for.
- The GPU is currently idle, at 0 MiB used.

## 6. Hyperparameters

The base model is `Qwen/Qwen2.5-7B-Instruct`, trained with SFT and QLoRA through LLaMA-Factory 0.7.1.

| | V0.1 (actual run) | **V0.2** | Why |
|---|---|---|---|
| Quantization | 4-bit NF4, double quant | same | known-working |
| Precision / template | bf16 / qwen | same | |
| LoRA | r16, α32, dropout 0.05, 7 projections | same | |
| Cutoff | 2048 | same | max sample is 848 tokens |
| Batch | 2 × accum 8 = 16 | same | |
| Optimizer | paged_adamw_8bit, grad-norm 0.3, cosine | same | |
| Learning rate | 2e-4 | **2e-4** | V0.1's problem was duration, not LR; changing both at once would confound the comparison |
| Epochs | 3.0 | **2.0** | V0.1's eval loss was best at step 100 (epoch 2.19). Train loss then fell to about 0.83–0.99 while eval barely moved, which is overfitting. V0.2 has 1.8× the rows, so 2 epochs is still 164 steps, more than V0.1's entire 135-step run. |
| Save / eval every | 50 | **20** | 8 evaluations instead of 2, so best-model retention has real resolution |
| Warmup | 4 steps | **5** | 3% of 164 |
| Weight decay | 0.0 (GUI default) | 0.0 | pinned in the CLI config so the CLI and GUI runs match |
| Best-model retention | on (eval_loss) | on (eval_loss) | the GUI enables it whenever val_size > 0 |

**Schedule:**
- 1311 training rows give 82 optimizer steps per epoch, so **164 steps** in total.
- Eval and checkpoints happen at steps 20, 40, … 160, 8 of each, followed by a final evaluation.
- The adapter written to `adapters/rupsaa-v0.2/` is the **best checkpoint by eval loss**, not the last step.

**Estimates:**
- Time: V0.1 ran at about 7.6 s per step, and V0.2 samples are longer, so expect roughly 25–35 minutes.
- Disk: about 250 MB per checkpoint, so roughly 2.3 GB in total. 294 GB is free.

**Output:** `/teamspace/studios/this_studio/rupsaa-ai/adapters/rupsaa-v0.2`. The launcher refuses any path that points at `rupsaa-v0.1`.

## 7. Known warnings

1. **The in-training eval set is a 5% resplit of train, not the frozen validation file.**
   - LLaMA-Factory 0.7.1 has no argument for a separate eval file, in either the CLI or the GUI (`data/utils.py` `split_dataset`).
   - The model therefore trains on 1311 of the 1380 train rows and evaluates on the other 69.
   - This is the same as V0.1. The frozen validation and test sets are never loaded, so they stay clean.
   - **Workaround:** after training, score the adapter or any checkpoint on the *frozen* validation split with `llamafactory-cli train configs/training/llamafactory_rupsaa_v0.2_eval_validation.yaml`, which is eval-only. Keep the test split for the single final evaluation.
2. **Validation and test contain no terminology-grounded examples.**
   - All 30 were grouped by term family and landed in train.
   - Held-out loss can't measure terminology behavior. Check it with the 10 live-behavior prompts after training.
3. **Overlap with V0.1's training set.**
   - 36 validation and 38 test records were in V0.1's training set.
   - Their ids are in the manifest (`ids_also_in_v01_train`).
   - For a fair V0.1-vs-V0.2 comparison, report the test metric on the other 38 test records as well.
4. **Three diversity WARNs.** They are documented and not blocking: skeleton `S-` 26.9%, skeleton `S|SQ` 15.6%, opening `that's a` 4.2%.
5. **`data/dataset_info.json` gained the three V0.2 registrations.** The V0.1 entries are byte-identical, but the file-level hash in `release/rupsaa-v0.1/checksums.sha256` no longer matches, so `scripts/verify_installation.py` shows a *warning* ("config edited since release"), not a failure.

Post-training evaluation: `bash scripts/posttrain_rupsaa_v02.sh` (see `data/production/evaluation/rupsaa_v0.2/README.md`). Final preflight: `data/production/reports/rupsaa_v0.2_training/PREFLIGHT.md`.

## 8. GUI instructions

1. `cd /teamspace/studios/this_studio/rupsaa-ai`
2. `bash scripts/start_llamafactory_gui.sh v0.2`
   - This verifies the frozen export hashes and renders `config/rupsaa_v0.2.yaml`.
   - It checks the config through LLaMA-Factory's own `load_args`, then starts the WebUI on port 7860.
3. In Lightning, open **only port 7860**.
4. In the WebUI **Train** tab, type `rupsaa_v0.2.yaml` in the **Config path** box and click **Load arguments**.
5. Before you press Start, check:
   - Model name `Custom`, model path `Qwen/Qwen2.5-7B-Instruct`, finetuning `lora`, quantization `4`, template `qwen`
   - Dataset dir `data`, dataset `rupsaa_v0.2_train`
   - LR `2e-4`, epochs `2.0`, cutoff 2048, batch 2, grad-accum 8
   - Val size 0.05, save steps 20, warmup 5
   - LoRA 16 / 32 / 0.05
   - Output dir `/teamspace/studios/this_studio/rupsaa-ai/adapters/rupsaa-v0.2`
6. Press **Start**.

After training, serve it with `RUPSAA_ADAPTER_PATH=adapters/rupsaa-v0.2`. The prompt version switches to v0.2 automatically.
