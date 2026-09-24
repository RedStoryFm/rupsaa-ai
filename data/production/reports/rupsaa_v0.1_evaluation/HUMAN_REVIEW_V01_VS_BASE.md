# Rupsaa V0.1: base vs V0.1 evaluation (human review)

Date: 2026-09-23. No automatic quality score is given here, because no existing evaluator defines one. The only numeric metric is held-out loss, which measures how closely the model's replies match the dataset. It does not measure quality.

## Setup

**Models compared**
- A = `Qwen/Qwen2.5-7B-Instruct` on its own.
- B = A plus `adapters/rupsaa-v0.1`.
- B is loaded in 4-bit NF4 and is **not merged** into the base model.
- For A, the run uses the same loaded weights with the LoRA switched off (`PeftModel.disable_adapter()`). So the only difference between A and B is the adapter.

**Adapter attach check**
- 196 LoRA modules attached (28 layers × 7 projections).
- Switching the adapter on or off changes the next-token logits by up to 15.8 on a probe prompt, so the adapter is clearly active.

**Prompts**
- The prompts are the existing `scripts/evaluate.py` suite, unchanged: 16 single-turn cases and 3 multi-turn cases (9 turns).
- None of the prompts match train, validation or test data. The highest fuzzy similarity is 0.81: "chargeback" vs a training prompt about "churn rate", which is a different question.
- Nothing was cherry-picked: every output is included in `generation_comparison.json`.

**Generation**
- Identical for A and B: `configs/inference.yaml` settings (temperature 0.8, top_p 0.9, top_k 50, repetition penalty 1.1, max 512 new tokens), with the same sampling seed per case.
- There is one sample per case and condition, so individual replies are noisy. Read the patterns across cases, not single lines.

**Two system prompts**
- `production`: the app's `build_system_prompt()` persona (what users actually get).
- `training`: `"You are Rupsaa."`, the system prompt used in every V0.1 training record.
- Every single-turn case also ran with context from the RAG pipeline (`production+rag`, `training+rag`), because the pipeline returned context above `min_score` for all 15 of them (see the RAG finding below).

The essential-boundary case was blocked by `essential_boundaries` before generation, for both A and B, as designed.

## Held-out test split (43 records, never trained on)

Assistant-token cross-entropy, the same quantity as LLaMA-Factory's `eval_loss`:

| | loss | perplexity |
|---|---|---|
| Base | 3.345 | 28.35 |
| **Rupsaa V0.1** | **1.515** | **4.55** |

The adapter has lower loss on **43/43** records, and in every language and category.

| language | n | base | V0.1 |
|---|---|---|---|
| bn | 16 | 2.00 | 0.95 |
| mixed | 6 | 3.14 | 1.32 |
| en | 9 | 4.64 | 2.00 |
| banglish | 12 | 6.73 | 3.05 |

Banglish is still by far the hardest language for the adapter. Full per-record and per-category results are in `held_out_test_loss.json`.

## Where V0.1 clearly improves

- **Persona and naturalness (English).** Base replies are long, list-heavy assistant answers averaging 855 characters. V0.1 replies average 224 characters: short, conversational, and usually ending in one relevant follow-up question.
  - Examples: the difficult-conversation, settling-vs-realistic and consent cases.
  - English is where V0.1 is strongest.
- **Identity with the training prompt.** With `"You are Rupsaa."`, base invents a persona ("a character from the folklore of Bengal", "mythology of Tripura", "spirit of prophecy"). V0.1 never does.
- **Uncertainty.** V0.1 says plainly that it can't predict next month's exchange rate. Base hedges at length, and with the training prompt it answers in character as a "spirit of prophecy".
- **RAG-aware and no-doc refund policy.** V0.1 says it doesn't have the policy and suggests checking the source; it does not invent terms.
- **Creator workflows.** The chargeback and payout answers are correct, concise and practical. The detailed-response case still gives a proper step-by-step answer (217–340 tokens), so the adapter did not remove the ability to go long when asked.
- **Adult terminology education.** The consent answer is direct, non-preachy and accurate ("each specific action… enthusiastic and reversible").
- **Multi-turn (English).** The creator-troubleshooting and relationship threads stay coherent across 3 turns, build on the earlier turns, and don't repeat the base model's list dumps.
- **Short answers.** "kemon acho?" gets a one-liner.

## Regressions and problems (important)

1. **Verbal tic: "Honestly … actually".**
   - Across all 78 replies per model: 69 V0.1 replies contain "honestly", 55 of them *start* with it, and 41 contain "actually". Base has 1 of 78.
   - The cause is the training data, not the training run: 863 of 1,129 assistant turns in `train.jsonl` contain "honestly", 439 start with it, and 703 contain "actually".
   - This breaks the Voice Bible's own rule ("never repeated as a tic"). **Fix it in the data for V0.2, not with prompts.**
2. **Bengali-script and Banglish coherence is weak.**
   - Bengali-script answers are often semantically wrong. "তুমি কি আমাকে সাহায্য করতে পারবে?" ("can you help me?") gets "কখনই না…" ("never…").
   - The tic words are also inserted into Bengali script.
   - Banglish replies are frequently word-salad and don't answer the question. Examples: the advice case, and the creator-income case ("eta eishob nijer context emon na…").
   - Base Bengali is also poor (garbled script, drifting into formal আপনি), so this isn't a clear regression in quality. But V0.1 **does not yet deliver the Bengali/Banglish goal**. It matches the test-loss picture: Banglish is the highest-loss language.
3. **Mixed-language mirroring is inconsistent.**
   - In the language-switching thread, V0.1 answers the Bengali-script turn in mixed script.
   - Its Banglish turns are grammatically broken ("tui eta feel kori naki somoy?"), including a switch to the informal তুই/"tui".
4. **Contextual flirting became cold or dismissive in one condition.** Under the training prompt, "do I have a chance with you?" got "Nah, honestly — that's not even worth pursuing…". Under the production prompt the reply was fine but flat ("depends on who 'you' even means"). Neither is playful.
5. **Memory questions get deflected.** Live API check: after "kemon acho?", the follow-up "ar ami ki bolechilam first e?" ("what did I say first?") got "Honestly forget it, I don't keep track…". The history *was* sent, so this is a behaviour regression, not a plumbing bug.
6. **Minor overclaims.**
   - "I can tell you what today's rate is": there is no live data.
   - "Would you rather I look up the most current official wording": there is no browsing.
   - "someone I was chatting with sent a gif": an invented personal experience.
7. **Train/inference system-prompt mismatch.** Training used `"You are Rupsaa."`; the app sends the long persona. Both conditions show the same patterns, so it isn't the main issue. It's still worth aligning in V0.2: either train with the production prompt or serve the training one.
8. **The adapter shipped is checkpoint-100, not step 135.**
   - `load_best_model_at_end` kept the best-eval checkpoint: eval loss 1.761 at step 50, then 1.704 at step 100.
   - Training loss fell to about 0.83–0.99 in epoch 3 while eval loss barely moved, which looks like overfitting of the small dataset's style (including the tic).

## RAG finding (reported only; architecture unchanged)

- The pipeline returned context for **all 15** allowed prompts, including "kemon acho?".
- Scores are about 0.80–0.83 against `min_score` 0.72, which is too low a threshold for e5 embeddings.
- `.metadata.json` from `knowledge/documents` is indexed and returned as a "source".
- With context attached, V0.1's answers stayed grounded and didn't invent citations. The live `/chat` call with `use_rag: true` worked and returned sources.

## Bottom line

V0.1 is a real, measurable step toward Rupsaa's style:
- held-out loss 3.34 → 1.51, better on 43/43 records
- much better persona, brevity, uncertainty handling, and English conversation

It is **not** ready as the Bengali/Banglish voice. The "honestly/actually" tic and weak Bengali/Banglish coherence are the top V0.2 data fixes, both coming from the dataset rather than the training setup.

## Files

- `evaluation_results.json`: everything (load check, test loss, generations)
- `held_out_test_loss.json`: per-record, per-language and per-category test loss
- `generation_comparison.json`: all A/B generations for every condition
- `run.log`: raw run log
- Reproduce: `python scripts/evaluate_v01.py`
