# Rupsaa V0.2.1 — pre-training report (R2 freeze)

**Status: R2 frozen (`rupsaa_v0.2.1_r2`, sha `e1332c83b522cc57bd3240a28e517edda1cd757a929afcf89b155118d254cd22`),
preflight passed. NOT TRAINED — owner approval required.**

R2 **supersedes** the first V0.2.1 freeze (`5e54c8f24aad837f3d037cb661806316969a169aeca0cfe1da282a1c654e5543`,
tag `rupsaa-v0.2.1-training`) **before any training** — the owner added Dance Knowledge to this cycle.
The first freeze's files are left byte-identical (`release/rupsaa-v0.2.1/SUPERSEDED.json`); it must not be trained.
V0.1, V0.2, the frozen V0.2 parent and all earlier reports/checkpoints are untouched.

## Dance knowledge (RAG, owner-editable)

| | |
|---|---|
| owner source | `data/owner/dance_knowledge_owner_60.txt` (verbatim, sha `75a3aee6…1977`) |
| supplied / parsed / stored / enabled | **60 / 60 / 60 / 60** (`dance_import_report.json`); name, origin, description byte-identical to the owner text |
| derived | aliases only from the owner's names (slash parts, hyphen/space/accent forms, "X dancing") + Bengali-script name spellings for 21 dances (retrieval only — please review); category/tags only when the description says it ("ballroom dance", "street dance", …) |
| choreography fields | all empty — nothing invented; the prompt tells Rupsaa step-by-step isn't recorded |
| storage | `knowledge/dance/dance-*.json`; Knowledge page → Dance tab (edit/import/test), live without retraining |
| retrieval (`dance_retrieval_check.json`) | **366/366** queries pass, 60/60 dances (definition, origin, "tell me about", lowercase, every alias, Bengali names, 28 typos), all 9 owner representative queries; **0** false positives on 20 ordinary-chat negatives and on all 2,414 user messages of the frozen V0.2 + corrective data |
| false-positive guard | a passing mention of a name that is also an everyday word ("breaking point", "polka dots", "salsa sauce") only counts when the message talks about dancing or names another dance |

## Dance conversations (hand-written, grounded only in the owner's records)

| | train | held-out (never trained) |
|---|---|---|
| conversations | **24** | **12** |
| Banglish / Bengali / English (final reply) | 11 / 5 / 8 | 5 / 3 / 4 |
| language switch / mixed | 4 (Banglish→English, Banglish→Bengali, English→Banglish, mixed-script question) | 3 |
| tasks | definition, origin, simplify, detail, comparison (5), alias, typo, follow-up/"tell me more", casual, "teach me the steps" → steps not recorded | definition, origin, typo, simplify, language switch, comparison, steps-not-recorded |
| dances | 28 different dances | 13 dances, none of them in training |

The owner's showcase dances (Belly Dance, Ballet, Kathak, Voguing, Breaking, Haka, Bhangra) are in **neither**
set, so the owner's own live tests measure generalisation. Every reply was read against its record(s);
an automatic faithfulness gate also rejects any origin place not in the attached entry and any step instructions.

## Gates (all pass)

| gate | result |
|---|---|
| catchphrases (honestly/actually/fair call/fair enough/heyy/bindaas/baby/babe/basically/oh dear/anything more) | 0 replies (198 records, 314 replies) |
| diversity | top first token 2.5%, top opening bigram 1.0%, top sentence frame 3.2%; 0 exact / 0 near-duplicate replies; 0 emoji |
| questions | 9.6% of replies end with "?"; 5.3% on direct answers/definitions/dance answers |
| scripts | 237 Latin-script / 77 Bengali-script replies, every one in the expected script; 0 mixed-script corruption |
| dance faithfulness | 0 flags (tested: a planted wrong origin and planted steps are both caught) |
| leakage | PASS — held-out (21 + 12) vs 165 training records and the frozen V0.2 splits: no exact/near-duplicate turn, no shared term/dance/concept; all records vs the benchmark prompts (owner live sequence, live + supplementary checks, 24 unseen terms, owner dance queries) and all frozen validation/test turns |
| train-as-we-serve | every corrective + dance row equals the runtime rebuild today; the reviewed 162 corrective records are byte-identical to the first freeze |

## R2 training set

| | |
|---|---|
| base V0.2 (unchanged) | 1,380 |
| corrective train | 141 × 2 = 282 rows |
| dance train | 24 × 2 = 48 rows |
| **total rows** | **1,710** (19.3% corrective + dance) |
| internal train / eval (val_size 0.05, seed 42) | **1,624 / 86** — the 86 eval positions hold only single-copy V0.2 rows (incl. V0.2's own 69); 0 corrective/dance rows |
| external validation / test | 77 / 76 (frozen V0.2, byte-identical) |
| corrective held-out / dance held-out | 21 / 12 |
| unique training conversations | 1,545; 2,460 weighted assistant replies |
| dance knowledge in the freeze | 60 records hashed + copied (`snapshots/rupsaa_v0.2.1_r2_training/dance_knowledge/`) — served by RAG, not trained |

Weighting stays ×2 (same as the first freeze): the dance rows are behaviour examples like the corrective
ones; 48 rows (2.8%) teach the format without turning the 60 facts into a LoRA target.

## Training (prepared, not run)

Recipe unchanged: Qwen/Qwen2.5-7B-Instruct, fresh QLoRA (4-bit NF4 + double quant, bf16), LoRA r16/α32/0.05
on the 7 projections, batch 2 × accum 8, 2 epochs, lr 2e-4 cosine (warmup 6), cutoff 2048, eval/save every 20,
best checkpoint by eval loss. **1,624 rows → 812 batches → 101 steps/epoch → 202 steps, ≈ 38–41 min on the L4.**

- CLI: `configs/training/llamafactory_rupsaa_v0.2.1.yaml` → R2 export only
- GUI: `bash scripts/start_llamafactory_gui.sh v0.2.1` → Config path `rupsaa_v0.2.1.yaml` (dry run verified against R2 hashes)
- LLaMA-Factory preflight (`smoke_check.json`): 22/22 — 1,710 rows tokenized, split 1,624/86, planned eval rows,
  202 steps, V0.2 prompt in every row, prompt tokens identical to the runtime (1,710/1,710), dance block in all
  48 dance rows, labels = assistant turns, max 848 tokens, frozen dance copy == live store
- immutability: SHA manifests + `release/rupsaa-v0.2.1-r2/checksums.sha256` (154 files) + tag
  `rupsaa-v0.2.1-r2-training`. (Read-only file modes are best-effort: the studio's storage resets modes.)

Command (owner only, after approval):
```
cd /teamspace/studios/this_studio/rupsaa-ai && llamafactory-cli train configs/training/llamafactory_rupsaa_v0.2.1.yaml
```

---

# (Superseded) first V0.2.1 freeze — kept for the record


**Status: dataset frozen as `rupsaa_v0.2.1`, preflight passed. NOT TRAINED — owner approval required.**
V0.1 and V0.2 (adapters, datasets, reports, checkpoints) are untouched; the frozen V0.2 dataset is
reused byte-for-byte.

## 1. Corrective data review

Every one of the corrective conversations was read in full (not only scored). Per-record status and
reason: `data/production/corrective/rupsaa_v0.2.1/REVIEW_LOG.json`, also shown on every record in
`CORRECTIVE_DATA_REVIEW.md`.

| | |
|---|---|
| reviewed | 162 (160 existing + 2 added) |
| kept unchanged | 94 |
| rewritten | 66 — of which 6 replaced with new content |
| removed | 0 |
| added | 2 (multi-message summary recall: Banglish, English) |
| final corrective total | **162** → **141 train** + **21 held-out** |

What the rewrites fixed (examples, all in REVIEW_LOG.json):
- **meaning errors:** c021-012 said "eat without finishing your earlier work" (meant "eat first, work later").
- **unnatural Banglish / transliterated English structure:** "tumi ki te okay ar ki te okay na", "manush ta
  nijeke dekha hocche bole feel kore", "Tumi ki niye bojhano jacche na mone korcho?", "kaoke kache chai,
  dure thaki, na bhoy pai hariye jawar", "porishkar-porichchhonnota ar safer-sex", "kintu tara kore na".
- **wrong word:** "ghar" (house) for neck → "ghaar"; "fol" → "result"; "mittha bola" → "mitthe kotha bola".
- **house-style consistency:** hyphenated emphatics (eta-i, duto-i, bolle-o → etai, dutoi, bolleo),
  genitive on English words (intimacy-r → intimacy er), reduplication (tara-tari → taratari),
  kaoke/khheyal/duijon → kauke/kheyal/dujon, assistant "Accha" → "Achcha".
- **benchmark separation:** c021-048 was a trivial paraphrase of the owner's "tumi amar sathe banglish e kotha
  bolbe?"; c021-001 contained the eval prompt "kemon acho?"; c021-150 used the exact prompt
  "ami age ki bolechilam?"; c021-057 used the exact prompt "achcha" — all replaced/rephrased.
- **external-eval contamination:** c021-070's reply "Bolo, shunchi." was word-for-word a frozen
  **validation** target, and c021-023's user turn equalled a validation user turn — both changed.
- **held-out integrity:** c021-138 (neck kissing) duplicated train c021-111; c021-103 (ghosting) shared a
  concept with train c021-037; c021-087 (situationship) and c021-096 (toxic) already occur in the frozen
  V0.2 train set; two held-out switch commands were near-copies of trained ones — all replaced.

The data was written by Claude (an AI). The review applies `BANGLISH_STYLE_GUIDE.md`; a native
speaker's read (the owner's) remains the final judge of naturalness.

## 2. Coverage (training subset, 141 conversations)

| behaviour | train | held-out |
|---|---|---|
| greetings + casual Banglish | 18 | 2 |
| casual Bengali script | 10 | 2 |
| explicit + multi-turn language switching (Banglish↔Bengali↔English, sticky "from now on") | 21 | 3 |
| short acknowledgements (accha/hmm/ok/bujhlam/thik ache/আচ্ছা/বুঝলাম/হুম/okay/got it) in context | 14 | 2 |
| emotional-context follow-ups | 12 | 2 |
| direct explanations | 10 | 2 |
| simplify / shorten / detail / example follow-ups | 10 | 2 |
| terminology-grounded answers (reference block from the store) | 18 | 2 |
| typo terminology | 7 | 1 |
| recall: generic, first-message, earlier-message, factual, several-message summary, no-history | 16 | 2 |
| English conversation | 5 | 1 |

Memory examples teach reading the history (different names, places, facts in every record; the
recall note only lists the user's own messages). Terminology examples use 20 different store entries
through the runtime's reference block; Strip, Foreplay and the 24 unseen evaluation terms never appear.

## 3. Languages

| | Banglish | Bengali | English | switch conversations |
|---|---|---|---|---|
| corrective, final reply (all 162) | 85 | 46 | 31 | 24 |
| corrective train (141) | 74 | 39 | 28 | 21 |
| corrective held-out (21) | 11 | 7 | 3 | 3 |
| assistant replies (all corrective) | 201 Latin-script | 69 Bengali-script | — | — |
| frozen V0.2 train (1380) | 389 | 360 | 422 | + 209 mixed |

## 4. Corpus audit (`corrective_checks.json`) — all gates pass

| check | result | gate |
|---|---|---|
| catchphrases honestly/actually/fair call/fair enough/heyy/bindaas/baby/babe/basically | 0 replies | 0 |
| emoji | 0% | 0 |
| mixed-script corruption / foreign script | 0 / 0 | 0 |
| exact / near-duplicate replies (≥0.85) | 0 / 0 | 0 |
| most common first token | "tahole" 3.0% | ≤ 10% |
| most common opening bigram | "ki hoyeche" 1.1% | ≤ 6% |
| most common sentence skeleton | 2.0% | ≤ 5% |
| replies ending with "?" | 11.1% overall, 7.1% on direct answers/definitions/acks/recall | ≤ 25% / ≤ 10% |
| definitions opening with the meaning ("X mane …") | 17/40 (the rest open with a direct answer in another form) | report |
| reply length (chars) | p10 27 · median 78 · p90 157 · max 309 | report |
| Banglish house style | bhalo 22/0 valo · sheta 22/0 seta · shomoy 18/0 somoy · shobcheye 3/0 sobcheye | report |

Explained warning: sentences with no function words ("Good morning!", "Darun!") are excluded from the
skeleton-concentration metric — they carry no repeated frame; before the exclusion that bucket read 8.8%.

## 5. Leakage (`LEAKAGE_REPORT.md`) — PASS

Held-out vs corrective train and vs the frozen V0.2 train/validation/test: no exact or near-duplicate
(≥0.80) user or assistant turn, no shared terminology entry, no shared definition concept. All 162
corrective records vs 133 benchmark prompts (owner's 11-turn live sequence, 10 live checks, 29
supplementary checks, 24 unseen-terminology cases), the 24 unseen terms + Strip/Foreplay, and all frozen
validation/test turns (which contain the clean V0.1-vs-V0.2 subsets): no exact or ≥0.90 match. Short
strings (<12 chars) are compared exactly. Three short user commands also exist in the frozen V0.2 train
set ("এটা বাংলায় বলো", "banglish e bolo", "love bombing ki?") with different replies — informational only;
they are in training, not in any evaluation set.

## 6. Final training set (frozen)

| | |
|---|---|
| name | `rupsaa_v0.2.1` (export `data/production/exports/rupsaa_v0.2.1/`, snapshot `data/production/snapshots/rupsaa_v0.2.1_training/`, read-only) |
| dataset SHA-256 | `5e54c8f24aad837f3d037cb661806316969a169aeca0cfe1da282a1c654e5543` (definition in the manifest) |
| parent | `rupsaa_v0.2` `96e0125e39ab2754c8540a29b6d3fee0a3132d46ae72adb9a4c3c7dcd067da33`, unmodified |
| unique base conversations | 1,380 (frozen V0.2 train, every row exactly once, unchanged) |
| corrective unique (train) | 141 |
| weighted corrective rows | 282 (×2, exact duplicate rows; `train_row_map.jsonl` lists every row) |
| total training rows | **1,662** (17.0% corrective); 2,402 weighted assistant replies |
| internal eval (LLaMA-Factory `val_size` 0.05, seed 42) | 1,578 train / 84 eval — the 84 positions hold only single-copy V0.2 rows (all 69 of V0.2's own internal-eval rows + 15), **0 corrective rows**, so duplicated examples can't sit on both sides |
| external validation / test | frozen V0.2 77 / 76, byte-identical, never loaded by the training config |
| corrective held-out | 21 (`corrective_holdout.jsonl`), never duplicated or trained |
| preserved eval sets | clean V0.1-vs-V0.2 subsets and the 24 unseen-terminology cases unchanged |
| prompt version | v0.2 (`V02_SYSTEM_PROMPT` sha `ef1d8fd4…26a4`) |
| sources | base: 909 synthetic_curated / 452 imported / 19 human_authored; corrective: 162 v021_corrective_handwritten |
| created | see `V021_TRAINING_MANIFEST.json` (`created_at`, `git_head_at_freeze`) |

## 7. Train-as-we-serve (`smoke_check.json`, LLaMA-Factory 0.7.1's own pipeline, tokenizer only)

21/21 checks passed: all 1,662 rows tokenized, none dropped; every system turn starts with the V0.2
runtime prompt (no qwen default, no bare "You are Rupsaa."); every corrective row is exactly what the
runtime builds today (terminology block ×92 rows, language directive ×36, recall note ×24 + no-history
note ×4 survive formatting); labels are exactly the assistant turns; prompt tokens are identical to
`tokenizer.apply_chat_template` (the runtime path) in 1,662/1,662 rows; max 848 tokens, nothing
truncated at 2,048; the internal eval slice is exactly the planned V0.2 rows.

## 8. Training configuration (prepared, not run)

| | |
|---|---|
| base | `Qwen/Qwen2.5-7B-Instruct` — fresh LoRA (no `adapter_name_or_path`) |
| method | SFT + QLoRA, 4-bit NF4 + double quant, bf16, gradient checkpointing, paged_adamw_8bit |
| LoRA | r 16 / α 32 / dropout 0.05 on q,k,v,o,gate,up,down (same as V0.2) |
| batch | 2 × grad-accum 8 = 16 |
| schedule | lr 2e-4 cosine, warmup 6, **2 epochs** |
| steps | 1,578 rows → 789 batches → **98 steps/epoch → 196 steps** |
| eval/save | every 20 steps, best checkpoint by eval_loss |
| cutoff | 2048 |
| output | `adapters/rupsaa-v0.2.1` (absent; cannot be the V0.1/V0.2 directory) |
| estimated runtime | ~37–40 min on the L4 (V0.2: 11.4 s/step × 196 ≈ 37 min + 10 evals) |
| CLI | `configs/training/llamafactory_rupsaa_v0.2.1.yaml` |
| GUI | `bash scripts/start_llamafactory_gui.sh v0.2.1` → Config path `rupsaa_v0.2.1.yaml` → Load arguments (dry run verified; Data dir `data/production/exports/rupsaa_v0.2.1`) |

Serving afterwards needs no prompt change: the adapter name `rupsaa-v0.2.1` infers prompt v0.2.

## 9. Reproducibility and safety

- frozen hashes: V0.2.1 export + snapshot == manifest (and `release/rupsaa-v0.2.1/checksums.sha256`,
  23 files); V0.2 `release/rupsaa-v0.2/checksums.sha256` all OK; `scripts/v02_verify_frozen.py`: FROZEN STATE VERIFIED (V0.1 protected paths clean)
- adapter output path: fresh `adapters/rupsaa-v0.2.1`, `overwrite_output_dir: false`, V0.1/V0.2 refused by the GUI launcher and the smoke check
- secret scan + large-file check: `scripts/repo_audit.py` (see git section of the final report)
- full test suite (see final report)
- release record: `release/rupsaa-v0.2.1/TRAINING_FREEZE.json` (dataset, prompt, recipe, environment)

## 10. Exact command (DO NOT RUN until the owner approves)

```
cd /teamspace/studios/this_studio/rupsaa-ai && llamafactory-cli train configs/training/llamafactory_rupsaa_v0.2.1.yaml
```
