# Rupsaa V0.2.1 — training plan (PLAN ONLY — nothing trained)

> Updated 2026-09-26 after the final data review and freeze — numbers below are final; see PRETRAINING_REPORT.md.

**Status:** the corrective data has been reviewed and frozen as `rupsaa_v0.2.1`
(`data/production/exports/rupsaa_v0.2.1/V021_TRAINING_MANIFEST.json`). **Training is blocked on the
owner's explicit approval** — nothing has been trained.

## Recommendation: B — retrain from base on frozen V0.2 train + corrective data (×2)

| | A) continue V0.2 adapter, low LR, corrective only | **B) retrain from base, V0.2 + corrective ×2** |
|---|---|---|
| steps | 141 records → ~8 steps/epoch at batch 16 | 98 steps/epoch, 196 total (V0.2 had 164) |
| narrowing / overfitting | high: V0.2's own run already showed a widening train/eval gap (~0.66) at epoch 2 on 1,380 rows; 139 rows would be memorised within a few epochs | corrective data is 17.0% of rows; the 1,380 V0.2 rows keep everything else anchored |
| keeps V0.2's gains (no catchphrases, English quality) | yes, in principle | yes — same data + same recipe; verified by the same evaluation suites |
| learns the new runtime blocks (language directive, recall note) | only from 141 rows | same rows, but in the context of all other behaviour |
| evidence it's needed | the ablation shows the V0.2 LoRA did not damage base skills — there is nothing to "repair" in place | — |
| reproducibility | adapter-on-adapter lineage, two datasets | one frozen dataset → one adapter |
| cost | ~5 min | ~40 min on the L4 |

A is cheaper, but with so few rows the realistic outcome is a model that parrots the corrective
replies and drifts elsewhere. B is the safer choice. A remains a fallback experiment only if B's
evaluation shows the corrective share is too weak.

## Settings

| | |
|---|---|
| Base / starting point | `Qwen/Qwen2.5-7B-Instruct` (fresh LoRA; **not** the V0.2 adapter) |
| Data | frozen V0.2 train (1,380, unchanged, verified against its manifest) + 141 corrective records ×2 = **1,662 rows**; 21 corrective records held out (stratified, never trained) |
| Validation / test | frozen V0.2 validation (77) and test (76) — unchanged, so V0.2.1 is directly comparable to V0.2 |
| Method | SFT + QLoRA, LoRA r16 / α32 / dropout 0.05 on all 7 projections, 4-bit NF4 + double quant, bf16 |
| LR / schedule | **2e-4**, cosine, warmup 6 steps (same as V0.2) |
| Epochs | **2** (V0.2's eval loss still fell at epoch 2 without rising; more epochs risk memorising the corrective rows) |
| Batch | 2 × grad-accum 8 = 16; cutoff 2048 |
| Checkpointing | eval + save every 20 steps, best eval_loss retained |
| Output | `adapters/rupsaa-v0.2.1` (serves with `RUPSAA_PROMPT_VERSION=v0.2`, inferred from the name) |
| Config | `configs/training/llamafactory_rupsaa_v0.2.1.yaml` |

Why the recipe is unchanged: V0.2 training was healthy (monotonic eval loss, best at step 160/164,
finite weights). The failures are about data coverage, so only the data changes — which keeps the
comparison with V0.2 clean.

## Steps after approval

1. Start training (owner): CLI `llamafactory-cli train configs/training/llamafactory_rupsaa_v0.2.1.yaml`
   from the rupsaa-ai root, or GUI `bash scripts/start_llamafactory_gui.sh v0.2.1` → Config path
   `rupsaa_v0.2.1.yaml` → Load arguments → Start.
2. Evaluate with the same pipeline as V0.2 (clean-subset loss, 24 unseen terms, live checks,
   supplementary checks, voice audit) **plus** the 21 corrective held-out cases
   (`corrective_holdout.jsonl`) and the owner's 11-turn live sequence (`scripts/v021_replay_live.py`),
   with the runtime fixes in place.

## Pass criteria for V0.2.1 (proposed)

- clean-test loss ≤ V0.2 overall and in Banglish (no regression from the added data)
- catchphrase rate stays ~0%; question-ending rate on direct answers ≤ 15%
- owner live sequence: Bengali-script **and on-topic** reply to "এটা বাংলায় বুঝিয়ে বলো" in ≥ 2/3 runs;
  generic recall names the right earlier message(s) in ≥ 2/3; Strip/Forplay definitions judged
  correct and natural Banglish by the owner in ≥ 2/3
- corrective holdout: script correct 100%, meaning correct by human read

## Honest expectation

The corrective set targets behaviours with ~0–5 training examples today (switching, recall,
acknowledgements, direct answers), so those should improve clearly. General Banglish fluency is
limited by the 7B base model (the ablation shows base Qwen's Banglish is poor); 141 extra
conversations will help but will not make it native-level. If V0.2.1 still falls short on fluency,
the next lever is more high-quality Banglish data at scale or a base model with stronger Bengali —
not more epochs.
