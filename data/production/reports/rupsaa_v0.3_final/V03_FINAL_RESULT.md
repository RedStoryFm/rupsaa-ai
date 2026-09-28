# Rupsaa Gemma FINAL — corrective run result (2026-09-28)

**RESULT: PASS — READY FOR OWNER LIVE TEST.** This was the last training run; no further training.

## Dataset `rupsaa_v0.3_final` (frozen)
Built by `scripts/v03_build_final.py`; see `VALIDATION.json` and `V03_FINAL_MANIFEST.json`.

- **SHA-256:** `6eedeb105c5ebd069d59aca751a4df849767a192ad96944c6de79fbe87fbdc69`
- **Base:** the frozen Gemma V1 corpus `rupsaa_v0.2.2` (1,556 conversations). The V1 files are unchanged.
- **Total:** 1,804 conversations.
- **Added:** 248 conversations in natural Banglish:
  - 117 definitions (terminology and dance, including 13 Strip conversations)
  - 80 casual/emotional
  - 51 vocabulary, memory and follow-up
- **Modified:** 135 V1 conversations:
  - 69 hand rewrites of Banglish replies that mixed Bengali script into a reply to a Banglish message (66 found earlier, plus 3 more replies written entirely in Bengali script)
  - 77 replies with spellings made consistent (valo→bhalo, somoy→shomoy, thoda→ektu, …)

| Validation check | Result |
|---|---|
| Banglish replies (Latin script) | 1,867 |
| Replies containing "kapor" | 3 → 24 ("kapor khola" 18) |
| Devanagari / other foreign-script letters | 0 |
| Bengali script mixed into replies to Banglish messages | 0 |
| Known Hindi words ("kapde", "thoda", …) | 0 |
| Language-switch turns added | 33 |
| Exact duplicates | 0 |
| Owner test prompts used verbatim | 0 |
| Overlap with held-out prompts | 0 |
| Gemma chat template | prefix-consistent |
| Loss masking | assistant-only (verified) |
| Truncated conversations | 0 (max length 551 / 2048) |

Every new conversation was replayed through the real runtime, so it carries exactly the system prompt the app sends. Definition turns were verified to attach the owner's terminology or dance record.

## Training
- **Recipe:** unchanged from V1 — `google/gemma-3-12b-it`, QLoRA 4-bit NF4 with double quantization, bf16, LoRA r16 / α32 / dropout 0.05, LR 1e-4 cosine, 2 epochs, cutoff 2048. Same system prompt, chat template and loss masking.
- **Batching:** micro batch 4 × grad accumulation 4 = effective batch 16 (NVIDIA RTX PRO 6000 Blackwell, 96 GB).
- **Run:**
  - 216 steps in 551 s (9.2 min), at 2.55 s/step including evaluations
  - peak VRAM 57.7 GiB
  - mean train loss 1.899
- **Eval loss** (monotonic, no overfitting):

  | Step | 20 | 60 | 100 | 140 | 180 | 200 |
  |---|---|---|---|---|---|---|
  | Eval loss | 2.488 | 2.097 | 1.945 | 1.926 | 1.893 | 1.892 |

- **Selected checkpoint:** the final adapter (step 216).
  - **SHA-256:** `3c79e394578261cdb04033867a9d6a96bb20784d5b0fc9d78d20e1b057724f05`
  - **Location:** `adapters/rupsaa-v0.3-gemma3-final`

## Live test
Real production app, temperature 0.55. Results files: `live_original17.json`, `live_stress17.json`, `live_bengali.json`, `live_strip5.json`.

| Area | Result |
|---|---|
| Strip (11 answers in total) | Every answer says "kapor khola", most as "dhire dhire kapor khola". No "kapde", "kapro" or "ferotwa", no Devanagari, no mixed script. |
| Banglish | Understandable and natural in most replies; no Hindi leakage. |
| Bengali | Coherent: foreplay, simplified follow-up, Kathak, mambo. |
| RAG and dance facts | Correct: belly dance, Kathak, mambo, Breaking. |
| Terminology | Strip and Foreplay are correct and understandable. |
| Memory | "Blue" recalled in both runs. |
| Language switching | Banglish → Bengali → Banglish works; follow-ups carry the right record. |
| Identity | AI, no body; "I exist as text". |

Awkward phrasing appeared in about 4 of 38 Banglish replies:
- "Ami okhane achi, jodi kono jaygay jigges korechile bolo"
- "Gaan chhowa"
- Strip run 4: "shiddhanto ta eta e"
- Minor malformed words: "expressibo", "ghurnai"

Identity: one of two runs said "an AI created by Google" (base-model identity showing through).

None of these is recurring word salad, Hindi leakage, a factual error or broken switching. Watch them in the owner live test.

## Comparison with Gemma V1
Gemma V1 failed on Banglish:
- Strip came out as "kapde uthano", "kapro ferotwa" or "kapde ulta fela" in 3 of 4 runs.
- Casual replies included word salad and Hindi "kapde".

Both are fixed.
