# Rupsaa V0.2.1 R2 — post-training evaluation

**Verdict: FAIL for the launch quality bar — NOT READY FOR OWNER LIVE CHAT TEST.**
V0.2.1 is the best adapter so far (clear gains in memory, Bengali-script switching, dance grounding,
corrective/dance held-out loss, terminology generalisation; no catchphrases) but its Banglish/Bengali
wording is still frequently garbled and, in Bengali, sometimes contradicts the retrieved facts; the
owner's Strip prompt regressed. Nothing was promoted or deployed; production `.env` does not exist
and was not touched. All raw replies: `RAW_OUTPUTS.md`; all numbers: `posttrain_metrics.json`,
`posttrain_results.json`; production check: `production_smoke.json`.

## 1. Training

| | |
|---|---|
| completed | yes — 202/202 optimizer steps, 2 epochs (epoch 1.99), no OOM/CUDA errors in `running_log.txt` |
| data | 1,624 train / 86 internal eval examples from `exports/rupsaa_v0.2.1_r2` (dataset sha `e1332c83…54cd22`, files verified) |
| base / LoRA | Qwen/Qwen2.5-7B-Instruct, 4-bit NF4; r16/α32/0.05 on 7 projections; trainable 40,370,176 / 0.5273% |
| runtime | 2,428 s (≈40 min); mean train loss 1.492 |
| **best checkpoint (by eval loss)** | **checkpoint-200 — step 200, epoch 1.970, eval loss 1.7990, train loss (step 200 log) 1.0854** |
| final checkpoint | checkpoint-202 (not selected); top-level adapter == checkpoint-200 byte-for-byte |
| checkpoints | 20…200 + 202, all complete (weights, optimizer, scheduler, state) |

Eval curve: 20: 2.223 · 40: 2.045 · 60: 1.948 · 80: 1.874 · 100: 1.832 · 120: 1.839 · 140: 1.816 · 160: 1.804 ·
180: 1.800 · 200: 1.799. Monotone after step 120, flattening; train/eval gap ≈ 0.7 at the end (the same
shape as V0.2 — mild memorisation, no eval-loss overfitting).

## 2. Loss (token-weighted assistant cross-entropy; lower is better)

| set | n | V0.2.1 R2 | V0.2 | V0.1 | base | V0.2.1 < V0.2 |
|---|---|---|---|---|---|---|
| A. external validation | 77 | 1.563 | 1.561 | 1.461* | 3.278 | 35/77 |
| B. external test | 76 | 1.539 | 1.520 | 1.413* | 3.162 | 28/76 |
| F. clean validation (unseen by V0.1) | 41 | 1.529 | 1.516 | 1.755 | 3.002 | 15/41 |
| F. clean test (unseen by V0.1) | 38 | 1.474 | 1.461 | 1.672 | 2.983 | 17/38 |
| C. corrective held-out | 21 | **1.744** | 2.051 | 2.315 | 3.095 | **19/21** |
| D. dance held-out | 12 | **1.052** | 1.502 | 1.746 | 2.297 | **12/12** |

\* V0.1 trained on earlier versions of ~half of A/B, so only the clean rows (F) compare it fairly.
Reading: on general held-out conversation V0.2.1 ≈ V0.2 (within 0.01–0.02, not better); on the behaviours
the corrective and dance data targeted it is clearly better. Lower loss is not taken as "good" on its own —
see the generation results.

## 3. Terminology generalisation (E — 24 unseen terms, fixed reference block)

| | overall | banglish | bn | en | mixed |
|---|---|---|---|---|---|
| **V0.2.1** | **75%** | 7/9 | **4/5** | 4/5 | 3/5 |
| V0.2 | 62.5% | 6/9 | 2/5 | 4/5 | 3/5 |
| base | 25% | 0/9 | 5/5 | 0/5 | 1/5 |

## 4. Owner's live conversation — one session (exact replies in RAW_OUTPUTS.md §owner_live)

| turn | V0.2.1 (seed 777 / 888) | V0.2 | attribution |
|---|---|---|---|
| hi, tumi kemon acho? | ok / odd | ok | model |
| ajke amar mood ta bhalo na | garbled / ok ("Ki hoyeche?") | ok-ish | model |
| achcha | nonsense / nonsense | wandering | model |
| banglish e kotha bolbe? | echoes the question / garbled | echoes | model (directive attached) |
| Strip mane ki? | **evades** ("Ki hoyechilo nijer modhhe?") / **gibberish** | **correct** | **model** (record attached both runs) |
| strip … simple kore | vague / gibberish | ok | model |
| Foreplay ki? | partly right / garbled | garbled | model (record attached) |
| এটা বাংলায় বুঝিয়ে বলো | **Bengali script** 2/2, content **wrong** (invented acts, "সexo" corruption) | stayed Banglish 2/2 | script: runtime+model fixed; content: model |
| ami ki color bolechilam? | **"Blue."** 2/2 | **wrong** (repeats an earlier message) | fixed |
| ami age ki bolechilam? | **names the real fact (favourite colour blue)** 2/2 | deflects | fixed (recall note + model) |
| Belly dance ki? | correct origin + torso/hip / mixed-script ("অfরিকার") | correct | model quality varies |
| belly dance simple | repetitive ("toratar, toratar") / garbled | repeats | model |
| Kathak kothakar dance? | **North India, correct** 2/2 | wrong ("kothakar thakte pare") | dance RAG + model |
| এবার বাংলায় বলো | Bengali; **"ইন্দোর" (Indore) — wrong** / garbled | stayed Banglish | model |
| Breaking ar breakdance same? | correct; seed 888 excellent (origin + moves) | vague | ok |

Runtime/RAG attached the right record on **every** terminology/dance turn (14/14 V0.2.1 runs).

## 5. Behaviour summary (V0.2.1 vs V0.2, same current runtime)

| | V0.2.1 | V0.2 |
|---|---|---|
| English | good, coherent, honest ("I don't have that documented") | good |
| Banglish | often ungrammatical / semantically empty on casual and definition turns; some good answers | similar |
| Bengali script | now produced when asked; content often wrong or invented (Hula → "Kenya", Kathak → "Indore", Garba with Gujarati script and invented details) | rarely produced |
| memory (fact / generic recall) | **works** (color 2/2, generic 2/2, smoke "shiuli") | fails |
| terminology | records always attached; answers: Strip regressed, Foreplay mixed | Strip correct this run |
| capability honesty | invents a human body when asked about itself ("brown skin, glasses") — persona overclaim | similar |
| catchphrases (9 phrases, 184 / 168 replies) | **0** | 2 (actually, fair enough) |
| most common opening | 2.7% ("belly dance …") | 3.0% |
| replies ending in "?" | 22% avg questions/reply; 0/15 on dance held-out | 26% |
| mixed-script corruption | **5 words** ("সexo" ×2, "অf", "স্কulptural", "শoulder") | 0 |
| emoji / foreign script | 0 / 0 | 0 / 0 |
| script matches request (service-path turns) | 145/152 (95%) | 130/136 (96%) |

Earlier evaluation for reference: V0.1 catchphrases in 95.5% of replies, 13 mixed-script words; V0.2 0% / 0.

## 6. Dance

| | result |
|---|---|
| retrieval (runtime) | 60/60 records, 366/366 queries (`dance_retrieval_check.json`); every dance held-out turn 15/15 attached |
| dance held-out (12, never trained) | English excellent (tap, Kecak, tango vs milonga, Kizomba); Banglish mostly faithful (Flamenco, Dabke, Lindy Hop, Waacking); **Bengali unreliable: Hula → "কেনিয়ার" (record: Hawaii), Odissi "দেশভাগের", Garba Gujarati script + invented "ভাইদের সাথে খেলা"**; Butoh correctly says steps aren't recorded |
| unseen showcase (7 dances, never trained) | Belly Dance, Kathak, Voguing, Breaking, Haka answered from the record (Haka very short); Bhangra Banglish ok; ভাংড়া (Bengali) garbled ("পুণয়ের") |
| invented choreography | none detected (0 step flags; Butoh/Gumboot-style requests answered with "not recorded") |
| **runtime bug found & fixed** | "Ballet kothay originate korechilo?" attached **no** record ("ballet" is an everyday-word name and "originate" wasn't a dance cue) → the model invented history ("sheikh Abdul Samad"). Fixed in `rupsaa/rag/dance.py` (origin words count as dance context unless the question is about a longer phrase, e.g. "breaking news er origin ki?"); tests added; 0 false positives on 2,414 messages; live re-check through the production API: record attached, answer "Italy … France ar Russia" — correct |

## 7. Failure attribution

- **RUNTIME/RAG:** 1 — the Ballet origin phrasing (fixed and re-verified). Terminology (Strip, Foreplay,
  typo "Forplay", 24-term suite) always received the correct record.
- **MODEL:** Banglish grammar/semantics on casual and definition turns; Bengali-script content (wrong facts
  despite the right record, mixed-script corruption); Strip evasion/gibberish; "achcha"; echoing
  "banglish e kotha bolbe?"; persona overclaiming a human body.
- **BOTH:** none remaining (Bengali switching and recall were runtime+model and are now fixed).
- The system prompt was **not** changed to mask any model problem.

## 8. Production integration (safe mode, private ports 5599/8099, env-only config, then stopped)

`scripts/start_rupsaa_production.sh` with `RUPSAA_ENV=production`, adapter `adapters/rupsaa-v0.2.1`, pinned
`RUPSAA_ADAPTER_SHA256`, random owner key: config check OK (SHA verified) → `/ready` 200 → smoke test
**PASSED 22/22** (`production_smoke.json`): /health, /ready, /model/info (adapter `rupsaa-v0.2.1`, prompt v0.2,
quantized, cuda:0, no server paths), English/Banglish/Bengali chat in the right script, same-session memory,
terminology + dance retrieval, owner endpoints 401 without key and 200 with it (read-only), /rag/reindex 401,
conversation reset. Extra: 70 KB body → 413; parallel burst of 20 with limit 14/min → 4×200, 16×429;
/health stayed responsive during generation; session isolation confirmed with the real model (a foreign
id gets a new conversation that does not know "blue"). Instance stopped; ports free; GPU 0 MiB; no `.env` written.

## 9. Candidate adapter (for production `.env` ONLY if the owner approves)

| | |
|---|---|
| adapter path | `adapters/rupsaa-v0.2.1` |
| checkpoint source | checkpoint-200 (best eval loss) — top-level adapter is byte-identical |
| adapter SHA-256 | `eb42339c9c448aa428e0a0c79a5d96a0883df228a3b29e3523a23d4de9afba15` (161,533,192 bytes) |
| base model | Qwen/Qwen2.5-7B-Instruct (4-bit NF4, not merged) |
| prompt version | v0.2 (inferred from the adapter name) |
| dataset SHA-256 | `e1332c83b522cc57bd3240a28e517edda1cd757a929afcf89b155118d254cd22` (rupsaa_v0.2.1_r2) |
| training tag / commit | `rupsaa-v0.2.1-r2-training` → `00422c5` (evaluation run from `e464df8` + the dance-routing fix) |
| previous known-good for rollback | `adapters/rupsaa-v0.2`, sha `c7ca6184…a410559` |

## 10. Recommendation

**NOT READY FOR OWNER LIVE CHAT TEST.** Reason in one line: in the owner's own sequence, 2 of 2 runs still
garble or evade core Banglish/Bengali answers (Strip, Foreplay-in-Bengali, "achcha"), and Bengali answers
can state facts that contradict the retrieved record (Kenya/Indore). V0.2.1 should be kept as the current best
candidate (it strictly improves on V0.2 in memory, switching, dance and held-out loss); promotion stays
blocked on Banglish/Bengali quality, which — per the V0.2.1 diagnosis — is limited by the 7B base model's
Bengali and the amount of native-quality Banglish data, not by the runtime.
