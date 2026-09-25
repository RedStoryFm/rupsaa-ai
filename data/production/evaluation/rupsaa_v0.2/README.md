# Rupsaa V0.2 post-training evaluation suites

Evaluation only: nothing in this folder is ever training data. Run after training with `bash scripts/posttrain_rupsaa_v02.sh`.

## 1. Terminology generalisation (`terminology_generalization.jsonl`)

24 cases. Each term, and every alias, was checked to occur **nowhere** in the frozen V0.2 data (all splits, all roles), so a good score means V0.2 learned *how to use* supplied terminology rather than remembering the 30 training terms. The build refuses to write if that check fails.

- Languages: {'banglish': 9, 'bn': 5, 'en': 5, 'mixed': 5}
- Term sources: {'knowledge_store': 13, 'authored_for_eval': 11} (live owner-authored entries from `knowledge/terminology/` plus creator/dating terms authored for this eval)
- Behaviours: {'banglish_definition': 9, 'banglish_followup': 2, 'bengali_definition': 5, 'bengali_followup': 1, 'concise': 2, 'detailed': 2, 'english_definition': 5, 'grounding': 6, 'language_switch_to_banglish': 1, 'language_switch_to_bengali': 1, 'language_switch_to_english': 1, 'mixed_definition': 5, 'short_kore_bolo': 1, 'simple_kore_bolo': 1, 'typo': 3, 'unseen_alias': 3, 'unseen_term': 22}

Each case supplies the term block exactly as the runtime does (`TermRecord.to_context()` under `Reference terminology:`); the same block is kept for follow-up turns, like the runtime's FOLLOWUP carry-over. Each model is run with its own serving system prompt (V0.1: `build_system_prompt(prompt_version='v0.1')`, V0.2: `prompt_version='v0.2'`).

Automatic checks are heuristics that flag replies for review; the human review is the decision:
- expected reply script (latin / bengali / any)
- length bounds for concise/detailed requests; follow-up "short/simple" replies must be shorter
- grounding: at least one concept from the supplied definition (English, Banglish or Bengali form)
- Banglish markers after a switch to Banglish
- forbidden phrases: retrieved context, reference terminology, according to the provided, the definition says, owner's guidance, as per the reference, honestly, fair call

## 2. Held-out evaluation manifests (`eval_manifests.json`)

| | Validation | Test |
|---|---|---|
| A. Full frozen V0.2 split (absolute V0.2 evaluation) | 77 | 76 |
| B. Clean V0.1-vs-V0.2 subset (fair comparison) | 41 | 38 |
| Excluded from B: seen during V0.1 training | 36 | 38 |

record id is in V0.1's training split (V0.1 approved ids minus the records whose content is in V0.1 validation/test). Repaired or rewritten versions of a V0.1 training record keep its id and are excluded too.
The frozen splits themselves are unchanged; this is metadata only.

## 3. Live behaviour checks (`live_behavior_checks.json`)

The owner's 10 live prompts, run through the real runtime context builder (`rupsaa.rag.context_builder.build_turn_knowledge`: routing, live terminology store, memory note), document RAG off (the web UI default).

- **live-01** hi, tumi kemon acho? — Natural Banglish greeting back, asks how the user is; no fixed catchphrase.
- **live-02** achcha — Short, natural reaction/prompt to continue.
- **live-03** ajke amar mood ta bhalo na — Warm, asks what happened; no lecture.
- **live-04** Strip mane ki? — Banglish definition grounded in the Strip terminology entry, non-graphic.
- **live-05** foreplay ki? — Banglish definition grounded in the Foreplay terminology entry.
- **live-06** Strip mane ki? → eta short kore bolo — Second reply shorter, same meaning.
- **live-07** foreplay ki? → এটা বাংলায় বুঝিয়ে বলো — Second reply in natural Bengali script.
- **live-08** What does edging mean? → Banglish e explain koro — Second reply in natural Banglish.
- **live-09** amar favourite color blue → ami ki color bolechilam? — Second reply: blue, from history.
- **live-10** amar naam Rupa, ami Kolkata te thaki → ajke kaj e onek chap chilo → ami age ki bolechilam? — Third reply recalls the name and/or city from history, no invention.
