# Rupsaa V0.2.2 — rapid rescue diagnosis

Nothing was trained, promoted or modified. The V0.1, V0.2 and V0.2.1 adapters and all checkpoints were only read. The GPU is free.

Evidence files in this folder:

| File | Contents |
|---|---|
| `diag_results.json` | Every reply, verbatim |
| `diag_grades.json` | My grade for every reply |
| `audit_banglish_replies.json`, `audit_bengali_replies.json` | Label and reason for every training reply |
| `failure_nearest_training.json` | Nearest training examples for each R2 failure |
| `tokenization.json` | Tokenizer measurements |
| `audit_scripts/` | Scripts used for the audit |

Draft correction set: `data/production/corrective/rupsaa_v0.2.2_draft/HUMAN_REVIEW.md`.

## Verdict

**Primary root cause: base model and data together.** It is not the tokenizer alone, and not the training recipe alone.

1. **Qwen2.5-7B has almost no Banglish, and weak, byte-level Bengali.**
   - Base Qwen with the full runtime scores **1/72** on the diagnostic suite.
   - It cannot write Banglish at all. It answers Banglish in Bengali script, or in English when asked for Banglish.
   - Its own Bengali already contains the corrupted-word pattern ("মood", "চাইly", "শক্তিশালी", "মধ্য동경에ast").
   - All Banglish ability comes from our SFT.
2. **The SFT data is too small, and too templated, to teach it.**
   - There are 691 Banglish and 518 Bengali-script replies.
   - 52% of the synthetic Banglish is template-heavy (openers like "Fair,", "Notice kora eta e first step", "Sotti bolte").
   - 19 Bengali replies splice Latin Banglish clauses into Bengali script.
   - 79 user turns contain half-Bengali, half-Latin words ("korার", "ekটা").
   - There is **no** row saying what Rupsaa is, and 46 rows give it a human body or life.
3. **The ×2 duplication added template interference.** Fragments from small duplicated sets fire in the wrong places (details in section 5). This makes the text worse, but it is not the main ceiling.
4. **The tokenizer contributes to Bengali-script errors specifically.**
   - 67% of Bengali tokens are partial UTF-8 bytes.
   - The corrupted forms are *cheaper* token paths than the correct words (details in section 4).

**Language quality did not peak early.** On the same prompts and seeds, the score rises from checkpoint-40 (8%) to checkpoint-200 (28%). Validation loss and generation quality moved together. Checkpoint-200 is the best, and it is still bad.

## 1. Tracing failures to the training data

For every failure, the nearest training rows (character n-gram TF-IDF over the user turn and reply) are listed in `failure_nearest_training.json`.

**Finding: the nearest neighbours are mostly GOOD rows.** Three failing prompts have a clean example of the same prompt in the corpus:

| Failing prompt | Training example | Training answer |
|---|---|---|
| "Strip mane ki?" | rup-001519 | "Strip mane basically kapor khola…" |
| "achcha" | rup-001483 | "Achcha, bolo? Ki mone ache?" |
| "hi, tumi kemon acho?" | rup-001480 | exact prompt |

The garbled outputs are not copies of any training reply; the best similarity is only 0.2–0.35. The model assembles fragments. Each fragment can be traced:

| Failure | Fragment | Where it comes from |
|---|---|---|
| Strip → "Strip er kotha bolcho? Ki hoyechilo nijer modhhe?" | "X er kotha bolcho" | Typo-correction corrective rows (×2) |
| | "nijer modhhe" | 6 counselling rows ("Kokhon theke eta notice korcho nijer modhhe?") |
| Mood → "Sheta manush ke halka lagte pare…" | "halka lage/lagbe" | 27 weighted rows, 20 from the ×2 corrective and dance sets. The original rows are natural. |
| Achcha → "Tahole ekta chokh mukhe kotha bolleo" | "Tahole …" continuation after an acknowledgement | The corrective acknowledgement pattern ("ohh accha" → "Hmm. Tai exam er age…"), applied with no topic to continue |
| Strip simple / Belly → "jigges dhore mola ghure" | "jigges" (= ask) | 26 correct uses in training; the model uses it as filler |
| | "dujoner jonno emon kichu" | "dujoner" (24/38 weighted from ×2 intimacy definitions) plus "emon kichu" (12 rows) |
| Bengali Foreplay "সexoয়ালি", Belly "অfরিকার" | Script switch *inside a word* | Base model and tokenizer (section 4); reinforced by 19 spliced replies and 79 half-script user turns |
| Bengali Kathak "ইন্দোর", Hula "কেনিয়ার" | Record attached, facts ignored | Only 5 Bengali dance rows exist; the base's Bengali proper-noun knowledge is weak (section 6) |
| "brown skin, glasses" | See section 7 | No identity rows; 46 human-life rows |

## 2. Banglish corpus audit

I hand-read all 691 unique Banglish assistant replies (825 weighted rows). Previous PASS/STRONG labels were ignored.

| | Unique | Weighted |
|---|---|---|
| GOOD | 414 (60%) | 536 |
| QUESTIONABLE | 253 (37%) | 265 |
| BAD | 24 (3.5%) | 24 |

**By source:**

| Source | GOOD | QUESTIONABLE | BAD |
|---|---|---|---|
| Imported | 136 | 52 | 5 |
| **Synthetic** | 152 | **189** | **19** |
| V0.2.1 corrective and dance | 122 | 12 | 0 |

**BAD examples:**
- Garbled word order ("Overthinking kora kono planned jinis er cheye…").
- Wrong word ("Nirvor kore" used to mean "depends").
- Nonsense ("smile kore feri").
- Corrupted spellings ("prthmbarer jnj", "poRi/paI").
- Hindi "bhi".
- An invented user history.

**QUESTIONABLE reasons:**
- Bengali danda in Latin text: 152
- Template openers: 96
- Full English sentences: 49
- Claims a human life: 34
- Catchphrases ("Heyy", "bindaas"): 2

Hindi leakage is rare (3 replies).

## 3. Bengali corpus audit

All 555 replies in conversations labelled Bengali were hand-read.

| Label | Count | Notes |
|---|---|---|
| GOOD | 339 | Imported and corrective Bengali are natural |
| QUESTIONABLE | 160 | 150 have 4+ Latin English words inside Bengali; 16 claim a human life |
| BAD | 19 | 18 synthetic |
| Latin replies in "bn" conversations | 37 | Mislabelled Banglish |

BAD Bengali examples:
- Latin Banglish clauses spliced into Bengali script ("সে reaction niye bhoy naki conflict niye bhoy?", "Sheta একটা signal").
- Ungrammatical sentences ("সেটাই মানুষকে বেশি ভয় পায়").

**Nothing in the data teaches wrong places.** The corpus has only 5 Bengali dance rows.

## 4. Tokenization (Qwen2.5 tokenizer, CPU)

| Language | Tokens per character | Tokens per word |
|---|---|---|
| English | 0.205 | 1.21 |
| Banglish | 0.294 | 1.75 |
| **Bengali** | **1.072** | **5.96** |

- The vocabulary has 151,665 tokens. Only 47 contain a Bengali character, and none mix Bengali with Latin.
- **67%** of Bengali tokens are partial UTF-8 byte fragments.
- One sentence costs 13 tokens in English, 19 in Banglish and 68 in Bengali.

The corrupted words are shorter token paths than the correct ones:

| Correct word | Tokens | Corrupted form | Tokens |
|---|---|---|---|
| সেক্সুয়ালি | 13 | সexoয়ালি | 8 |
| শোল্ডার | 8 | শoulder | 2 |
| আফ্রিকার | 8 | অfরিকার | 7 |
| স্কাল্পচারাল | 12 | স্কulptural | 5 |

After one Bengali letter, a cheap English subword wins.

**Finding:** the tokenizer materially contributes to Bengali-script corruption. It does not explain Banglish, which tokenizes efficiently. Banglish failures are knowledge and data problems.

## 5. Weighting, interference and checkpoints

**Template frequency: training data vs outputs** (outputs from the earlier post-training runs):

| Fragment | Weighted rows (from ×2 sets) | V0.2 outputs | R2 outputs |
|---|---|---|---|
| "X er kotha bolcho" | 10 (8) | 0.0% | **4.6%**, 7× on correctly spelled prompts ("Strip mane ki?", "Belly dance ki?") |
| "dujon/dujoner" | 38 (24) | 0.7% | **5.3%** |
| "emon kichu" | 12 (0) | 0.7% | **5.3%** |
| "halka" | 27 (20) | 0.0% | 1.3% |

**Conclusion:** ×2 duplication of small, stylistically uniform sets taught surface templates that misfire. This is real interference.

**Training curve:**
- Eval loss: 2.223 (step 20) → 1.832 (step 100) → 1.799 (step 200).
- Train loss drops sharply at the start of epoch 2: 1.59 at step 100, 1.18 at step 120. The model memorises its second pass, which is the 3rd and 4th sighting of the ×2 rows.

**Checkpoint suite:**
- 9 variants × 3 runs × 12 prompts, through the production service path with the same prompts and seeds.
- Runs: seeds 777 and 888 at temperature 0.8, and seed 777 at 0.3.
- Grades: 2 = natural and correct, 1 = flawed, 0 = broken. Maximum 72.

| Variant | Score | Fully good | Broken |
|---|---|---|---|
| Base Qwen + runtime | 1 (1%) | 0 | 35/36 |
| V0.2 | 11 (15%) | 0 | 25/36 |
| R2 checkpoint-40 | 6 (8%) | 0 | 30 |
| checkpoint-60 | 11 (15%) | 2 | 27 |
| checkpoint-80 | 8 (11%) | 2 | 30 |
| checkpoint-100 | 17 (24%) | 3 | 22 |
| checkpoint-120 | 16 (22%) | 4 | 24 |
| checkpoint-160 | 18 (25%) | 2 | 20 |
| **checkpoint-200** | **20 (28%)** | 2 | **18** |

- Checkpoint-200 at seeds 777/888 reproduced the post-training owner replies exactly, so the harness is consistent.
- **The best language-quality checkpoint is checkpoint-200.** There is no early peak.
- Temperature 0.3 does not fix it. Garbling becomes loops ("kotha dhorar por kotha dhorar…"), so this is the learned distribution, not sampling noise.
- My grading is subjective (±3 points per variant). The trend and the absolute level are clear anyway.

## 6. Ablation: what SFT improves and what it damages

| | Base | V0.2 | R2 checkpoint-100 | R2 checkpoint-200 |
|---|---|---|---|---|
| Banglish possible | no (Bengali/English) | yes, garbled | yes, garbled | yes, less garbled |
| Short greeting | 0 | flawed | good at 0.3 | good at 0.3 |
| Strip / Foreplay | wrong script, corrupted | garbled, evasive | partial | partial |
| Switch to Bengali | n/a | stays Banglish / "Fair," + nonsense | switches, content garbled | switches, content garbled |
| Dance facts (Banglish) | n/a | mostly right, rambling | right when copied from the record | right when copied from the record |
| Bengali dance facts | invented | invented | wrong places ("উত্তর ভারতের কাছাকাছি") | "ইন্দোর", "উত্তর-পূর্ব" |

- **SFT improves:** it makes Banglish possible at all, and adds script switching, record-copying, memory and short greetings.
- **SFT damages:** it adds template fragments (from ×2 rows) and the "Fair,"/"Sheta" openers (V0.2 synthetic).
- **SFT never fixes:** semantic coherence in Banglish and Bengali.

## 7. Physical-identity hallucination

The cause is evidence-backed:
- 0 training rows say Rupsaa is an AI, or answer "how do you look / are you human".
- 46 rows claim a human life or body. Examples: eating biryani, drinking coffee (corrective c021-006, ×2), a winter cup of tea (c021-027, ×2), "face expressive amar", a childhood, a beach-town trip, buying a gadget.
- The system prompt never says what Rupsaa is.

The correction is block A of the draft (14 records), plus dropping or rewriting the 46 rows. **This needs an owner decision on the persona.**

## 8. Minimal V0.2.2 draft

The draft is at `data/production/corrective/rupsaa_v0.2.2_draft/`. It was built through the real runtime by `scripts/v022_build_draft.py`.

**100 records:**

| Category | Count |
|---|---|
| Identity | 14 |
| Acknowledgement | 12 |
| Greeting | 8 |
| Mood | 10 |
| Direct definition | 11 |
| Switch to Bengali | 14 |
| Dance (the 12 records never used anywhere) | 15 |
| Banglish request | 5 |
| Memory | 6 |
| Simplify | 5 |

Languages: 65 Banglish, 30 Bengali, 5 English. Lint findings: 0.

**All replies are AI-written (by me).** They are not native-reviewed, and `HUMAN_REVIEW.md` must be completed before they are frozen. The owner's diagnostic prompts are not used verbatim, so they stay a fair test.

Proposed cleaned base corpus:
- 1,545 unique conversations, single copy (no ×2).
- Drop 41 with a BAD reply; drop or rewrite 46 with human-life claims → about **1,458**.
- Mechanical fixes: remove danda from Latin text, relabel 37 Latin "bn" replies.
- Add the reviewed V0.2.2 records.

**Runtime gaps found while building** (not model problems; fix them before V0.2.2 data is frozen):
- "jinish" (vs "jinis") and "kon desher" are not recognised as cues, so no record is attached.
- 39 of 60 dance records have no Bengali-script alias. "মাম্বো কোথাকার নাচ?" gets no record, so the model answers from memory.
- These follow-up phrasings do not carry the previous record forward: "এটা বাংলা হরফে লেখো", "এবার বাংলায়", "বাংলায়", "আরও সহজ করে বলো", "ek line e bolo".
- The 18 draft records affected are flagged "RUNTIME GAP — do not train until fixed".

## 9. Training strategy

| Option | Evidence | Verdict |
|---|---|---|
| A. Fresh LoRA, cleaned corpus | Removes BAD and human-claim rows and the ×2 interference | Good |
| B. Continue V0.2 with a tiny set | A tiny set trained for many steps repeats the ×2 template problem; V0.2 already scores 15% | No |
| C. Continue R2 with a tiny set | Keeps R2's template fragments, then adds more | No |
| **D. Fresh LoRA, verified-good V0.2 rows + reviewed corrections, single copy** | Same as A, plus the reviewed identity, acknowledgement and switch data; no duplication | **Recommended** |

- **Recipe:** Qwen2.5-7B-Instruct base; fresh LoRA r16/α32; **LR 1e-4** (half of before, because epoch 2 memorised); **2 epochs**, keeping every 20-step checkpoint.
- **Checkpoint selection:** choose with *this* generation suite (`scripts/rescue_v022_diag.py`, about 10 min per checkpoint), not eval loss.
- **Expected runtime:** about 1,560 rows → about 98 steps per epoch → about 196 steps, roughly 37 min on an L4 (11.4 s/step), plus about 1 h of suite runs.
- **Honest expectation:** the clean-up removes the misfiring templates and the invented body. It is unlikely to make the 7B model's Banglish/Bengali *reliably* coherent: 1,710 rows only reached 28%. A zero-shot probe of a base with real Bengali capacity would show whether the base is the ceiling. The probe is a no-training run of this same suite on a candidate base model.

## 10. Fast shipping fallback

**Base + runtime + RAG: NOT VIABLE.** It scores 1/72 and cannot produce Banglish. Its Bengali is itself corrupted: "মood", "চাইly", "মধ্য동경에ast", "স্ক্রিন্যাল ডান্স". For Banglish questions R2 checkpoint-200 is clearly better than base.

## Next action

A native Bengali/Banglish speaker reviews `data/production/corrective/rupsaa_v0.2.2_draft/HUMAN_REVIEW.md`, marking every record KEEP, EDIT or DROP. The owner also decides the identity stance (block A). Every V0.2.2 path depends on this, and it needs no GPU.
