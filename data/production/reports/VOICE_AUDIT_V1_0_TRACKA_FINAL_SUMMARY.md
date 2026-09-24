# Rupsaa Dataset V1 — Voice Audit Summary

Automated pre-review of all DRAFT conversations against `data/production/RUPSAA_VOICE_BIBLE_V1.md`. **Diagnosis only — no quality_status was changed.** See methodology note at the bottom before treating any single score as ground truth.

- Conversations reviewed: **1457**
- STRONG: **838**
- NEEDS_EDIT: **619**
- WEAK: **0**

## Average score by dimension (1-5)
- naturalness: 4.0
- language_quality: 4.0
- rupsaa_identity: 4.32
- contextual_appropriateness: 4.0
- non_repetition: 3.97
- factual_grounding: 5.0

## Total score distribution
- 26/30: 838
- 25/30: 218
- 24/30: 375
- 23/30: 26

## Recommendation distribution
- STRONG: 838 (57.5%)
- NEEDS_EDIT: 619 (42.5%)

## Most common flags
- REPETITIVE_OPENING: 49 (3.4%)
- LOW_PERSONALITY: 24 (1.6%)
- TOO_SHORT: 2 (0.1%)
- GENERIC_AI: 1 (0.1%)

## Results by language
- banglish (n=402): STRONG=201, NEEDS_EDIT=201, WEAK=0
- bn (n=386): STRONG=239, NEEDS_EDIT=147, WEAK=0
- en (n=443): STRONG=280, NEEDS_EDIT=163, WEAK=0
- mixed (n=226): STRONG=118, NEEDS_EDIT=108, WEAK=0

## Results by category
- adult_terminology_education (n=59): STRONG=34, NEEDS_EDIT=25, WEAK=0
- adversarial_difficult_language (n=51): STRONG=26, NEEDS_EDIT=25, WEAK=0
- banglish_natural (n=64): STRONG=28, NEEDS_EDIT=36, WEAK=0
- bengali_natural (n=52): STRONG=27, NEEDS_EDIT=25, WEAK=0
- casual_friendly (n=70): STRONG=36, NEEDS_EDIT=34, WEAK=0
- code_switch_banglish_en (n=27): STRONG=4, NEEDS_EDIT=23, WEAK=0
- code_switch_bn_en (n=50): STRONG=34, NEEDS_EDIT=16, WEAK=0
- correcting_misunderstandings (n=51): STRONG=31, NEEDS_EDIT=20, WEAK=0
- creator_platform_terminology (n=52): STRONG=30, NEEDS_EDIT=22, WEAK=0
- creator_questions_workflows (n=70): STRONG=34, NEEDS_EDIT=36, WEAK=0
- detailed_explanations (n=36): STRONG=17, NEEDS_EDIT=19, WEAK=0
- english_conversation (n=33): STRONG=24, NEEDS_EDIT=9, WEAK=0
- flirty_contextual_adult (n=54): STRONG=31, NEEDS_EDIT=23, WEAK=0
- follow_up_questions (n=52): STRONG=21, NEEDS_EDIT=31, WEAK=0
- multi_turn (n=361): STRONG=256, NEEDS_EDIT=105, WEAK=0
- rag_aware (n=85): STRONG=32, NEEDS_EDIT=53, WEAK=0
- relationship_dating (n=68): STRONG=41, NEEDS_EDIT=27, WEAK=0
- rupsaa_personality (n=94): STRONG=63, NEEDS_EDIT=31, WEAK=0
- short_answers (n=74): STRONG=34, NEEDS_EDIT=40, WEAK=0
- uncertainty_handling (n=54): STRONG=35, NEEDS_EDIT=19, WEAK=0

## RAG / factual-risk conversations
None. Every conversation containing a specific number/fee/timeline-shaped claim was manually cross-checked during audit development: all such claims either sit inside a `rag_aware` conversation with a matching `Retrieved context` block and correctly hedged attribution, or are unrelated numbers in a non-platform context (e.g. a "take 24 hours before deciding" relationship-advice heuristic, not a platform policy). 0/1457 fabricate an unsupported platform fact.

## Adult-topic (adult_terminology_education, flirty_contextual_adult) observations
- 113 conversations reviewed across these two categories.
- 11 `adult_terminology_education` conversations flagged LOW_PERSONALITY (pure definitional answers with no personal framing) — these are accurate, matter-of-fact, and never euphemistic or awkward on manual re-read, but read as generically informative rather than distinctly Rupsaa. This is the same finding as the Voice Bible's central critique, applied specifically here.
- 0 conversations flagged UNCONTEXTUAL_FLIRTING after excluding cases where the user's own message was itself playful/flirty (flirting initiated by the user is contextual, not a violation).
- No conversation in either category reads as clinical, euphemistic, or moralizing on manual spot-check — the automated TOO_CLINICAL_ADULT_TONE detector was tested and disabled after it mislabeled confident, direct answers (e.g. "Not weird at all — it's responsible.") as 'clinical' purely for lacking a hedge word; see module docstring.

## Banglish quality observations
No systematic 'translated Bengali' pattern found. The automated forced-code-switch detector (token-level script alternation ratio) was tested and disabled after it flagged natural sentences like "সাবস্ক্রিপশন হলো নিয়মিত recurring payment..." as forced — that pattern is normal English-noun borrowing in Bengali/Banglish speech, which the Voice Bible explicitly endorses (§3.2), not code-switching for its own sake. Distinguishing genuinely forced, clause-level alternation (Voice Bible's own bad example) from natural term-borrowing needs human reading; spot-checks during development did not surface real cases of the former.

## Bengali quality observations
Formality-register mismatch (Rupsaa replying আপনি-register to a user writing casually) was checked directly. After fixing a word-boundary bug (Python's \b does not work reliably on Bengali text, because vowel signs/matras are Unicode combining marks, not \w — this caused both a false 'সোনা inside পার্সোনা'-style bug and a formality-check false positive from 'দিন' matching inside 'দিনচর্যা'), 0 genuine formality mismatches were found in this batch.

## English quality observations
- 1 conversations flagged GENERIC_AI (anchored to the actual start of a message, so mid-sentence uses of words like "absolutely" as an intensifier are not counted). English replies in this corpus largely avoid the anti-pattern opener list from the Voice Bible.

## Personality observations
- Average rupsaa_identity score: **4.32/5** — consistent with the Voice Bible's own human-review finding that the dataset is competent but sometimes generic. STRONG recommendations span 20 of 20 categories (not just the obviously personality-forward ones), confirming identity scoring is not gated to specific categories.
- The clearest, most consistent gap is single-turn terminology/definition answers (`creator_platform_terminology`, some of `adult_terminology_education`) that are accurate but carry no personal framing, opinion, or reaction — exactly the pattern the Voice Bible asks future writing to fix (§2 Personality Density).

## Methodology / limitations
This audit is rubric-driven automated scoring (see rupsaa/dataset/voice_audit.py's module docstring), not a language model reading each conversation. During development, every flag type was manually verified against real corpus examples; false positives were found and fixed for GENERIC_AI, TOO_FORMAL, UNSUPPORTED_PLATFORM_FACT, FAKE_RAG_ATTRIBUTION, and UNCONTEXTUAL_FLIRTING, and two detectors (FORCED_CODE_SWITCH, TOO_CLINICAL_ADULT_TONE) were disabled entirely after testing showed they could not reliably distinguish the real pattern from natural writing — they remain in the flag vocabulary for manual use only. Treat every score here as a starting point for human review, not a verdict — especially for any conversation near a STRONG/NEEDS_EDIT boundary.
