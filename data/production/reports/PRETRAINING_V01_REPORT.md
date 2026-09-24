# Pre-Training V0.1 Report

Generated 2026-09-23. Reflects the actual current state of
`data/production/` — no numbers here are projected or rounded up.
Underlying data: `stats_20260923T070408Z.{md,json}`,
`audit_20260923T070415Z.{md,json}`, `VOICE_AUDIT_POST_REPAIR_V1.jsonl` /
`_SUMMARY.md`.

## 1. Dataset size

- **Total conversations: 530**
- Total messages: 1,970
- Approx. token count: 40,921
- Single-turn: 404 (76.2%) · Multi-turn: 126 (23.8%)
- Average turns/conversation: 1.36
- Average conversation length: 307.7 characters

**This is well short of the ~1,500–2,000-conversation expansion target.**
Expansion (Sections 7–9 of the pre-training plan) was not executed in this
pass — see the Final Report for why and what's needed next.

## 2. Status distribution

| Status | Count |
|---|---|
| draft | 508 |
| approved | 20 |
| needs_edit | 1 |
| rejected | 1 |

Only 20 conversations (3.8% of the corpus) are currently `approved` — the
only status the export pipeline (`scripts/dataset_export.py`) will use for
training.

## 3. Source type distribution

| source_type | Count |
|---|---|
| imported | 508 |
| human_authored | 22 |

All 508 imported conversations came from the original Dataset V1 import,
prior to the Voice Bible repair pass. `human_authored` entries are Teach
Rupsaa submissions (this session's smoke-test entries were removed after
verification; these 22 are genuine).

## 4. Language distribution

| Language | Count | % |
|---|---|---|
| banglish | 158 | 29.8% |
| en | 133 | 25.1% |
| bn | 124 | 23.4% |
| mixed | 115 | 21.7% |

Reasonably balanced across all four; no language is a small minority.

## 5. Category distribution

| Category | Count |
|---|---|
| multi_turn | 114 |
| banglish_natural | 41 |
| bengali_natural | 30 |
| code_switch_banglish_en | 28 |
| code_switch_bn_en | 27 |
| creator_questions_workflows | 27 |
| casual_friendly | 24 |
| adult_terminology_education | 24 |
| short_answers | 21 |
| relationship_dating | 20 |
| flirty_contextual_adult | 19 |
| follow_up_questions | 19 |
| uncertainty_handling | 19 |
| correcting_misunderstandings | 19 |
| rupsaa_personality | 18 |
| creator_platform_terminology | 18 |
| rag_aware | 18 |
| adversarial_difficult_language | 18 |
| detailed_explanations | 15 |
| english_conversation | 11 |

**Underrepresented categories** (< 20 conversations, and disproportionately
weak per the Voice Bible audit — see §7): `english_conversation` (11),
`detailed_explanations` (15), `rupsaa_personality` (18),
`creator_platform_terminology` (18), `rag_aware` (18),
`adversarial_difficult_language` (18). `rupsaa_personality` and `rag_aware`
being this small is the most important gap given Section 8's stated
expansion priorities.

## 6. Duplicates / repetition (scripts/dataset_audit.py, --status all)

- Exact duplicates: **0**
- Near duplicates: **0**
- Repeated assistant replies (≥3×): **0**
- Style watchlist overuse (>15% of assistant messages): **0**
- Emoji-containing assistant messages: **0.6%** (threshold 50%, not exceeded)
- Messages with >2 emoji: **0**
- Schema/Unicode errors: **0**

The corpus is clean on every mechanical check. Nothing here is currently
blocking training on quality-mechanics grounds.

## 7. Voice Bible audit (VOICE_AUDIT_POST_REPAIR_V1, 508 draft conversations)

- STRONG: **70 (13.8%)**
- NEEDS_EDIT: **438 (86.2%)**
- WEAK: **0**

Average score by dimension (1–5): naturalness 4.0, language_quality 4.0,
**rupsaa_identity 3.55** (the weakest dimension), contextual_appropriateness
4.0, non_repetition 4.0, factual_grounding 5.0.

Most common flag: `LOW_PERSONALITY` (17 conversations, 3.3%).

**Remaining weakness**: the repair pass (Section 2) already lifted this
corpus from a lower baseline, but 86% of conversations are still
NEEDS_EDIT — competent and correct but generic, missing a distinctive
Rupsaa marker (opinion, reaction, callback, etc.), consistent with the
Voice Bible's core finding ("more character, not more flirting"). This is
a content-quality gap, not a mechanical one — no amount of dedup/schema
tooling fixes it; it needs either further targeted repair or the corpus
being diluted by a much larger share of genuinely STRONG new material.

By language, STRONG rate: en 23.3%, mixed 16.8%, banglish 9.7%, **bn 6.6%**
— Bengali-script conversations are the weakest by voice, not by language
quality (language_quality dimension is flat at 4.0 across the board).

## 8. RAG / factual-risk findings

**None.** Every specific number/fee/timeline-shaped claim in the corpus was
manually cross-checked during audit development: each sits either inside a
`rag_aware` conversation with a matching retrieved-context block and
correctly hedged attribution, or is an unrelated number in a non-platform
context (e.g. relationship-advice heuristics). 0/508 fabricate an
unsupported platform fact.

## 9. Adult-topic and creator coverage

- Adult-oriented: `adult_terminology_education` (24) + `flirty_contextual_adult`
  (19) + `relationship_dating` (20) = **63 conversations (11.9%)**. Consistent
  with the plan's "adult-oriented should feel natural, not the whole
  dataset" instruction.
- Creator-oriented: `creator_questions_workflows` (27) +
  `creator_platform_terminology` (18) = **45 conversations (8.5%)**.
- Both categories score below the corpus STRONG average in the Voice Bible
  audit (creator_platform_terminology: 0/17 STRONG) — coverage exists but
  voice quality in these categories is currently weak.

## 10. Bottom line

The corpus is mechanically clean (§6) and factually safe (§8), but is
1/3 the target size, 86% of it needs a voice-quality edit pass, and the
`rupsaa_personality`/`rag_aware` categories — explicitly named as expansion
priorities — are among the smallest and weakest in the dataset. See the
Final Report for the training-readiness verdict.
