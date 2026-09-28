# Rupsaa V0.3 (Gemma 3 12B) — Banglish root cause (analysis only; no training, no data changes)

**Evidence:**
- `banglish_rootcause.json`:
  - official `google/gemma-3-12b-it` loaded once (4-bit NF4, bf16); "base" = adapter disabled, "trained V1" = adapter enabled
  - the real runtime system prompts for the 5 failing prompts
  - greedy decoding plus T=0.8 samples with seeds 1–3
  - Strip-answer log-likelihoods and tokenizer splits
- A targeted check of the frozen `rupsaa_v0.2.2` train split.
- The live tests (`live_test_final*.json`).

## Findings
1. **The base-model prior is Hindi-romanised.**
   - Base Gemma prefers "Strip mane **kapde** uthano" (mean log-prob −4.05) over "kapor khola" (−6.74).
   - It leaks Devanagari ("धीरे") and "kapad".
   - It avoids Banglish for definitions: 4 of 5 Strip answers are in Bengali script.
   - Its casual replies are English-heavy with emojis, and one sample was garbage ("Ami valobasha", "goshto pete nite").
2. **Fine-tuning moved the preference in the right direction, but only by a thin margin.**
   - With the V1 adapter, "kapor khola" is ranked first (−0.97).
   - The Hindi variants stay close behind: "kapde uthano" −1.19, "kapde khola" −1.29, "kapro ferotwa" −1.58.
   - So greedy decoding still produced "kapde ulta fela".
   - Casual Banglish improved clearly: every greedy/seeded greeting and mood reply was natural and concise.
3. **The data is clean but sparse where it matters.**
   - The frozen split has no "kapde" and no intra-word script mixing, and only "thoda" ×2 as Hindi.
   - All 3 Strip replies say "kapor khola", but "kapor" occurs just **3×** in 1,530 Latin replies.
   - There are **0** examples like "mood bhalo na".
   - Spelling is inconsistent (bhalo 46 / valo 18).
   - 66 of 1,538 replies to Latin-script users (4.3%) mix Bengali script in.
4. **The tokenizer disadvantages Banglish.**
   - Banglish words fragment, and the pieces overlap Hindi romanisation: `kapor`→k|apor, `kapde`→kap|de, `bhalo achi`→b|halo|▁ach|i.
   - Bengali script tokenises cleanly (`ভালো`, `▁আছি`).
5. **Decoding amplifies the problem but doesn't cause it.**
   - Sampling at T=0.8 adds tail forms ("kapot gulo kata", "kapro ferotwa").
   - The Hindi "kapde" also appears under greedy decoding.
   - The runtime bugs (fp16 NaN, missing end-of-turn stop, v0.1 prompt) are fixed and were not the cause.
