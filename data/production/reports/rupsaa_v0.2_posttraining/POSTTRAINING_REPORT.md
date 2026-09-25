# Rupsaa V0.2 — post-training evaluation

**Verdict: FAIL — not promoted.** V0.2 is a clear, measurable improvement over V0.1, but it still fails most
of the owner's own failure prompts (Banglish/Bengali coherence, Bengali-script follow-ups, recall of
earlier turns). V0.1 remains the release; V0.2 stays available as an opt-in launcher for live testing.
Nothing was retrained, merged, released or uploaded. The frozen V0.2 dataset and V0.1 are unchanged
(`scripts/v02_verify_frozen.py`: FROZEN STATE VERIFIED).

Machine-readable: `posttrain_results.json` (all losses + every generated reply), `voice_audit.json`,
`decoding_probe.json`, `live_smoke.json`, `posttraining_summary.json`. Full reply transcripts: `POSTTRAIN_REPORT.md`.

## 1. Training run

| | |
|---|---|
| Steps | 164 / 164 (2 epochs), runtime 1868 s, NVIDIA L4 |
| Best checkpoint | `checkpoint-160` (epoch 1.951), eval_loss **1.8131** on the 69-row internal val_size slice |
| Top-level adapter | byte-identical to checkpoint-160 (not the last step, 164) |
| NaN/Inf | none (392 tensors finite; all 9 checkpoints complete) |
| LR | cosine, 1.995e-4 (step 10) → 3.1e-7 (step 160); grad-norm ≈ 1.0–2.2 |
| Mean train loss | 1.558; logged train loss 2.75 → 1.15 |

Eval curve (step: loss) — 20: 2.261 · 40: 2.081 · 60: 1.950 · 80: 1.878 · 100: 1.864 · 120: 1.833 · 140: 1.817 · 160: 1.813.
Monotonic, flattening (−0.004 in the last interval). Train/eval gap widened to ≈0.66 → mild memorisation,
**no overfitting by the selection criterion** (eval loss never rose). The 1.8131 is not comparable to V0.1's 1.7037 (different slice).

## 2. Adapter integrity

Base `Qwen/Qwen2.5-7B-Instruct`, 4-bit NF4, LoRA r16/α32/dropout 0.05 on all 7 projections, attached with PEFT (not merged),
trained on `rupsaa_v0.2_train`, training commit `afe6e4e` (tag `rupsaa-v0.2-training`), no training inputs changed since.
`adapter_model.safetensors`: 161,533,192 bytes, SHA-256 `c7ca61842d58fb2b68a813a6b09f4df1fdab66717128e0112d5014235a410559`.
V0.1 adapter matches `release/rupsaa-v0.1/checksums.sha256`.

## 3–4. Held-out loss (token-weighted assistant cross-entropy; lower is better)

V0.2 and base scored with the frozen V0.2 system prompt; V0.1 with its own training prompt ("You are Rupsaa." layout).
**Prompt non-equivalence:** each model gets the prompt it was trained with, so this measures each model as served.

| set | records | V0.2 | V0.1 | base | V0.2 better than V0.1 |
|---|---|---|---|---|---|
| Frozen validation (full) | 77 | 1.561 | **1.461** | 3.278 | 41/77 |
| Frozen test (full) | 76 | 1.520 | **1.413** | 3.162 | 39/76 |
| **Clean validation** (unseen by V0.1) | 41 | **1.516** | 1.755 | 3.002 | **40/41** |
| **Clean test** (unseen by V0.1) | 38 | **1.461** | 1.672 | 2.983 | **37/38** |

The full splits favour V0.1 because 36/77 and 38/76 of those conversations (earlier versions) were in V0.1's
training set — that comparison is contaminated. On the clean subset V0.2 wins overall and in every language:

| clean test | V0.2 | V0.1 | base |
|---|---|---|---|
| banglish (9) | 3.004 | 3.538 | 5.715 |
| bn (9) | 0.744 | 0.835 | 1.327 |
| en (12) | 1.703 | 1.970 | 4.093 |
| mixed (8) | 1.486 | 1.663 | 2.994 |

Banglish loss (≈3.0) is still by far the highest of any language — consistent with the generation results below.

## 5. Generation (real router + terminology store; seeds fixed; temperature 0.8 / top-p 0.9 / rep-penalty 1.1 = `configs/inference.yaml`)

**Unseen terminology (24 cases):** automatic pass V0.2 **15/24 (62%)**, V0.1 1/24, base 6/24
(V0.2 by language: banglish 6/9, bn 2/5, en 4/5, mixed 3/5). Reading the 9 flagged V0.2 cases: 5 are real failures
(tg-09 garbled "detailed" answer; tg-11, tg-13 incoherent Bengali; tg-18 incoherent Banglish follow-up; tg-04 answered a
Banglish follow-up in English), 4 are mild/heuristic (length or script-mix flags on otherwise acceptable replies).

**Owner failure prompts (V0.2, pipeline run + live app):**

| prompt | result |
|---|---|
| hi, tumi kemon acho? | OK–weak: short Banglish, sometimes odd ("Chilo chhuti beshi, tumi ki bolo?") |
| achcha | OK: short, natural enough |
| ajke amar mood ta bhalo na | OK: asks what happened, no lecture; phrasing awkward |
| tumi amar sathe banglish e kotha bolbe? | **FAIL**: incoherent, never clearly says yes |
| Strip mane ki? | **FAIL** (live) / weak: routed to the right entry, but the Banglish is garbled; "clothing remove kora" comes through only sometimes |
| strip ta ektu simple kore bojhao | **FAIL**: garbled; follow-up now keeps the Strip entry (router fixed) |
| foreplay ki? | **Mixed**: correct content but in English (language mismatch) or garbled Banglish |
| Forplay ki? | Routing PASS (typo → Foreplay); reply **FAIL** in the pipeline run (nonsense Bengali), weak in the live app |
| এটা বাংলায় বুঝিয়ে বলো | **FAIL**: after a definition it stays in Banglish (0/12 Bengali-script in the decoding probe); once in the live app it switched to Bengali but the content was nonsense |
| amar favourite color blue → ami ki color bolechilam? | PASS (content): answers "blue"; grammar sometimes off |
| ask → ami age ki bolechilam? | **FAIL**: 0/2 in the pipeline, 0/6 in the probe, 0/1 live — deflects or confabulates |

**General suite (15 single-turn + 3 multi-turn):** English is good and coherent (difficult conversations, settling vs
realistic, chargeback, subscriber-growth multi-turn, relationship multi-turn, honest "I don't know" on exchange rates and
undocumented refund policy — no overclaiming seen). Bengali/Banglish general replies are short and often off-target
(gen-01 "তুমি কি আমাকে সাহায্য করতে পারবে?" → an unrelated question).

## 6. Voice audit (89 generated replies per model)

| | V0.2 | V0.1 | base |
|---|---|---|---|
| replies with honestly/actually/fair call/fair enough/heyy/bindaas/baby/babe/basically | **0%** | 95.5% (honestly 69, actually 61, basically 4) | 0% |
| most common opening share | 3.4% | 15.7% ("honestly eta") | 5.6% |
| repeated sentence frames (≥3) | none | none | none |
| emoji / foreign-script (CJK) replies | 0 / 0 | 0 / 0 | 3 / 7 |
| mixed-script corrupt words ("korার") | 0 | 13 | 16 |
| mean / max chars | 154 / 905 | 176 / 423 | 220 / 805 |
| questions per reply / ≥2 questions | 0.25 / 0 | 0.30 / 2 | 0.26 / 3 |

The V0.1 catchphrase tic is completely gone and no new tic replaced it. Tone is calm and non-pushy. The problem is
semantic quality in Banglish/Bengali, not voice.

## 7. Decoding probe (runtime only, no training)

12 owner prompts × 2 seeds × 3 settings (`decoding_probe.json`). temperature 0.5 / rep-penalty 1.05 gives visibly
cleaner Banglish (greetings, "Strip mane … clothing remove kora", colour recall 2/2) than the current 0.8 / 1.1;
temperature 0.3 / 1.0 starts to loop ("jate jate jate jete jete"). **No setting fixes** Bengali-script follow-ups (0/12)
or recall of earlier turns (0/6). A lower temperature is a reasonable runtime tweak but does not change the verdict.

## 8. Classification: **FAIL**

Passes: training health, integrity, train-as-serve prompt, clean-subset loss (V0.2 < V0.1 < base, every language),
catchphrase removal, English quality, terminology grounding in English, routing/RAG/memory plumbing.
Fails (core V0.2 goals, not minor): natural Banglish definitions, Bengali-script follow-ups, recall of earlier turns;
terminology auto-pass 62% (< 80% gate). Integrating it as the normal adapter would ship the same owner-reported failures.

## 9. Runtime / integration work done (kept regardless of the verdict)

Found through the evaluation's real-router runs and fixed in `rupsaa/rag/` (tests in `tests/test_v02_routing_terminology.py`):
- GENERAL-route messages now consult terminology by whole-phrase containment ("foreplay niye detail e bojhao" → Foreplay entry)
- "simple kore bojhao/bujhiye bolo" recognised as a follow-up; follow-ups also add a term the message names
- trailing filler ("… mane ki bolo to") no longer breaks definition parsing; "Tell me what X means" parsed
- one-edit typos ("stirp" → Strip) matched for single-word terms
- a follow-up with no earlier messages gets a note to ask what to explain instead of guessing
- `/model/info` now reports `prompt_version` (before and after the lazy load)

`bash scripts/start_rupsaa_v02.sh` serves V0.2 with `RUPSAA_PROMPT_VERSION=v0.2`; `bash scripts/start_rupsaa_v01.sh` is unchanged.

## 10. Live app smoke test (V0.2 via the launcher, port 5500 proxy → FastAPI)

**37/37 plumbing checks passed** (`live_smoke.json`): /health; /model/info (Qwen2.5-7B-Instruct, adapter
`adapters/rupsaa-v0.2`, adapter_loaded true, quantized true, cuda:0, prompt_version v0.2); casual turns without RAG;
memory route without RAG; Strip/Forplay routed to the right entries; follow-ups keep the entry; no `.metadata.json`
source; owner create → chat uses it immediately → edit → search → lookup tool → delete; CSV/XLSX template, preview,
commit (test rows removed); /conversation/reset clears memory; `/`, `teach.html`, `knowledge.html` and all JS served.
Quality observation (not plumbing): after an owner edit the reply did not restate the edited definition.
Temporary services were stopped; ports 5500/8000 free.

## 11. Release

Not released (verdict FAIL): no `release/rupsaa-v0.2/manifest.json`, no Hugging Face upload, `configs/release.yaml`
still points at `rupsaa-v0.1`. `scripts/release_model.py` now has a `v0.2` entry (frozen-records dataset identity,
freeze checksums preserved) so `prepare v0.2` works if a later decision approves it.

## Recommendation

Owner live-tests V0.2 (`bash scripts/start_rupsaa_v02.sh`) to confirm or overrule. For a future version the evidence points
at the data, not the recipe: more and cleaner natural Banglish definitions/explanations, Bengali-script answers to
"বাংলায় বলো" follow-ups, and multi-turn "what did I say earlier" examples that cite earlier turns.
