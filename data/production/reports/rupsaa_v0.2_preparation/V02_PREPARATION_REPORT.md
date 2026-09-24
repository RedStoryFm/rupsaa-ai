# Rupsaa V0.2 preparation report

**Date:** 2026-09-23

**Scope:** diagnosis, tooling and runtime fixes only. Nothing was trained. No record, approval, the frozen V0.1 snapshot/export, the V0.1 evaluation outputs, the V0.1 adapter or its checkpoints were changed.

**Reproduce:**

```
python scripts/v02_dataset_diagnosis.py        # all machine-readable files in this folder
python scripts/v02_repair_review.py summary     # human review queue
python -m pytest -q                             # 234 tests
```

| File | What it holds |
|---|---|
| `phrase_frequency.json` | Catchphrase rates by corpus, language, category, source, status and prior audit recommendation; raw counts for the V0.1 train export |
| `diversity_full_corpus.json`, `diversity_v01_approved.json`, `diversity_v01_train.json` | Output of the new corpus gate |
| `openings_templates.json` | Top openings, transitions and sentence skeletons, by language and source |
| `language_quality.json` | Bengali/Banglish/code-switch defect counts by language × source |
| `triage.jsonl`, `triage_summary.json` | KEEP / REPAIR / REJECT / HUMAN_REVIEW per record, with mechanical proposals |
| `projected_after_repairs.json` | What the corpus gate would say if KEEP plus every REPAIR proposal were accepted (hypothetical) |
| `REPAIR_REVIEW_SHEET.md` | The first 80 undecided repairs, original vs proposal |

---

## 1. V0.1 dataset root cause

**What went wrong:** "honestly" appears in **863 of 1,129 (76%)** assistant replies in the V0.1 train split, and "actually" in 703 (62%). The LoRA learned exactly that.

**Why the audit let it through.** It was a feedback loop in the tooling, not a single bad example:

1. **The scorer rewarded the tic.**
   - `voice_audit.py` listed `honestly`, `actually`, `genuinely`, `obviously` and `basically` as *personality markers*.
   - One marker raised identity from 3 to 4, and two markers raised it to 5. STRONG required every dimension to be at least 4.
   - In practice, a reply without a marker could not be STRONG.
2. **The generation guide taught writers to game the scorer.**
   - `V01_SYNTHETIC_GENERATION_GUIDE.md` said: *"Decide on 2 distinct personality markers before writing the reply"*.
   - "Honestly … actually" is the cheapest way to hit two markers, which explains the "Honestly X actually" sandwich pattern.
3. **The audit selected for the tic.**
   - Records rated **STRONG contain "honestly" 76.9%** of the time. **NEEDS_EDIT records contain it 12.5%** of the time.
   - The most common NEEDS_EDIT note was "competent … but no distinctive Rupsaa marker present".
   - All 838 bulk-approved records were STRONG, so the approval step concentrated the tic.
4. **Nothing measured the corpus as a whole.**
   - Every check was per record.
   - The only frequency check, the style watchlist, covered pet names, "hehe/haha/obviously" and emojis, not "honestly" or "actually". It also only *warned*; nothing gated export.
   - The repeated-opener check needed an identical first four words used 8 or more times. "Honestly, <anything>" varies from the second word, so it never fired.
5. **Source effect.**
   - Synthetic replies: 70.6% "honestly" and 57.8% "actually".
   - Imported replies: 14.6% and 12.5%.
   - Human-authored replies: 8.7% and 0%.
   - The synthetic batches introduced the tic, and the audit then preferred them.

## 2. Phrase frequency

These figures cover the full corpus: 1,479 records (858 approved, 620 drafts, 1 rejected) and 2,074 assistant replies.

| Phrase | Corpus | V0.1 train (n=1,129) | Synthetic | Imported | Human |
|---|---|---|---|---|---|
| honestly | 51.1% | **863** | 70.6% | 14.6% | 8.7% |
| actually | 41.9% | **703** | 57.8% | 12.5% | 0% |
| genuinely | 7.8% | 108 | 9.5% | 4.7% | 0% |
| obviously | 1.6% | 31 | 2.2% | 0.6% | 0% |
| sotti bolte | 1.3% | 12 | | | |
| fair enough / fair call | 0.05% / 0 | 1 / 0 | | | |

**Openings**
- 26.1% of all replies start with "honestly". Among approved replies it's 38.5%.
- Next most common: "that's" 5.5%, "sheta" 3.7%, "fair" 3.6%.
- Frequent two-word openings: "honestly that's", "honestly eta", "fair actually", "sheta actually", "sheta honestly".

**By language** ("honestly" / "actually"):
- English: 62% / 36%
- Bengali: 55% / 44%
- Banglish: 42% / 47%
- Mixed: 40% / 41%

**English fillers inside Bengali-script replies:** "honestly" appears in 55% of Bengali replies. That's a phrase↔language correlation, now gated per language group.

**By category:** "honestly" ranges from 70% (english_conversation) down to 14% (code_switch_banglish_en). No category was immune.

**Response skeletons**
- The top synthetic skeleton is `F-`: "<Filler> X - Y." in one sentence, used by 356 synthetic replies.
- Imported replies are more varied; their top skeleton is `S|SQ`, a statement followed by a question.
- After filler removal, `S-` (one sentence with a dash aside) is still 27.5% of the projected corpus. That's a structural monoculture a filler fix can't solve.

## 3. Bengali / Banglish quality

**Method, stated honestly**
- Automated, named heuristics (`rupsaa/dataset/language_quality.py`) cover the *mechanical* defects.
- Semantic coherence, contradictions and whether follow-ups make sense were judged by reading about 60 stratified records: Banglish, Bengali and mixed; imported and synthetic; KEEP, REPAIR, REJECT and HUMAN_REVIEW.
- That reading was done by Claude, not a native speaker. Native-speaker review is still required.

Records with at least one assistant turn showing the defect:

| Defect (dimension) | Banglish syn. | Banglish imp. | Bengali syn. | Bengali imp. | Mixed syn. | Mixed imp. |
|---|---|---|---|---|---|---|
| n records | 248 | 154 | 265 | 121 | 113 | 113 |
| Mixed-script word, e.g. `korার` (malformed transliteration) | 73 | 30 | 11 | 0 | 27 | 16 |
| Other-script letters, e.g. Cyrillic `kичhu` | 2 | 1 | 0 | 0 | 0 | 0 |
| Script switch inside a reply | 16 | 7 | 1 | 1 | 0 | 1 |
| Reply script doesn't mirror the user | 0 | 0 | 1 | 0 | 20 | 13 |
| English filler in a Bengali-script reply | – | – | 169 | 24 | 46 | 18 |
| Opens with English filler (English frame on Bengali syntax) | 143 | 4 | 196 | 16 | 70 | 9 |
| Two or more fillers in one reply (excessive filler) | 144 | 8 | 148 | 2 | 68 | 7 |
| Bare counter-question, doesn't answer | 0 | 1 | 0 | 1 | 0 | 0 |
| English calque, "sheta worth X kora" (soft signal) | 5 | 1 | 0 | 0 | 10 | 0 |

**What reading found**
- **Most KEEP/REPAIR Banglish and Bengali is understandable.** Once the fillers are removed, it reads naturally enough, e.g. rup-000811, rup-000538, rup-000415, rup-000146.
- **The worst V0.1 behaviour wasn't copied from the data.** The word-salad replies (e.g. "Sheta honestly beshirer boro, actually") don't appear in the corpus. The model produced them by combining the tic with weakly represented Banglish.
- **Recurring defects that do exist in the data:**
  - English-syntax calques ("worth reconsider kora", "Sheta make sense").
  - Occasional misspellings ("hasbo kano").
  - Whole-sentence alternation between English and Bengali script in mixed records (rup-000459).
  - Answers that dodge the question slightly (rup-001082).
- **These are HUMAN_REVIEW problems.** No heuristic can reliably fix them.
- **Imported data is markedly cleaner than synthetic** on every dimension except mixed-script words.

**The V0.1 memory failure also has a data cause.** The train set has **zero** examples of answering a recall question from real history. The only three "you said earlier…" records are single-turn, with no earlier turn in context, so the model learned to answer generically.

## 4. KEEP / REPAIR / REJECT / HUMAN_REVIEW

| | KEEP | REPAIR | HUMAN_REVIEW | REJECT |
|---|---|---|---|---|
| **All (1,479)** | **508** | **854** | **110** | **7** |
| Banglish | 143 | 212 | 48 | 3 |
| Mixed | 63 | 110 | 52 | 3 |
| Bengali | 152 | 229 | 8 | 0 |
| English | 150 | 303 | 2 | 1 |
| Synthetic | 184 | 680 | 81 | 4 |
| Imported | 305 | 174 | 27 | 2 |
| Human-authored | 19 | 0 | 2 | 1 (already rejected) |
| Currently approved | 54 | 725 | 75 | 4 |

**Rules**
- **Human-authored** records are never auto-repaired: clean → KEEP, anything flagged → HUMAN_REVIEW.
- **REPAIR** means a *mechanical* proposal exists and leaves no defect: "honestly" removed everywhere; other fillers removed where they're pure filler; short mixed-script suffixes transliterated.
- **HUMAN_REVIEW** means one real defect remains after the mechanical repair, or the record has a prior factual-risk flag.
- **REJECT** means two or more severe defects remain.

**Caveats**
- REPAIR is not approval. Proposals remove tics; they don't fix meaning.
- **If** KEEP plus every REPAIR proposal were accepted, the corpus would be 1,362 records (453 en / 381 bn / 355 banglish / 173 mixed). It would pass the gate with 5 warnings: "honestly" 0%, "actually" 2%.
- That projection says nothing about semantic quality, and the skeleton warning (27.5%) remains.

**Review workflow:** `scripts/v02_repair_review.py` provides `summary`, `next`, `show`, `decide accept|keep-original|reject|edit` and `sheet`. It orders Banglish, then mixed, then Bengali, then English, and stores decisions in `data/production/v0.2_workspace/review_decisions.jsonl`. It never touches records or approvals.

## 5. Audit improvements

**New corpus gate: `rupsaa/dataset/diversity.py`**
- Thresholds live in `configs/dataset_production.yaml`, under `diversity`.
- It measures, over all assistant replies and per language group:
  - watchlist catchphrase share: WARN above 4%, BLOCK above 8%
  - any content n-gram, watchlisted or not: 1-gram 10% / 20%, 2-gram 3% / 6%, 3-gram 2% / 4%
  - first-word openings: 8% / 15%
  - first-two-word openings: 3% / 6%
  - sentence skeletons: 15% / 30%
  - synthetic-vs-other source correlation (warn only)
- Words are not banned; only their share is capped. A 2.5% "honestly" rate passes (tested).
- **The V0.1 train set now fails with 15 BLOCK issues.**

**Where it's enforced**
- **`scripts/dataset_audit.py` exits 1 on any BLOCK.** Pass `--allow-diversity-failures` for diagnosis runs only.
- **`scripts/dataset_export.py` refuses to export on BLOCK.** An override exists for historical and diagnostic exports only, and writes `diversity_report.json` with `training_ready: false`. **A corpus like V0.1 can no longer be exported as training-ready.**

**`voice_audit.py`:** phrases or openings the corpus overuses earn **no** personality credit. They raise `CATCHPHRASE_OVERUSE` / `REPETITIVE_OPENING` and cannot score STRONG. Without corpus context, the scoring is unchanged, so existing tests still pass.

**Also:** fixed a crash in `dataset_audit.py` when the style watchlist reported overuse (it treated `PhraseUsage` as a dict).

**New `language_quality.py`:** the Bengali/Banglish defect detectors in §3, plus the triage and the mechanical repair proposals.

**Recommendation:** retire the "2 personality markers" instruction in `V01_SYNTHETIC_GENERATION_GUIDE.md` for V0.2 generation. I left that file untouched as a historical record.

## 6. Terminology architecture

**Components**
- `rupsaa/rag/terminology.py` stores one JSON file per term in `knowledge/terminology/`.
- Schema: `id, term, aliases[], category, definition, details, answer_guidance, languages[], example_queries[], tags[], created_at, updated_at, enabled`.
- Categories: adult_terminology, creator_platform, dating_relationships, slang, general.

**Editing**
- **Owner UI:** `web/knowledge.html` → **Terminology** tab: create, edit, delete, search, and "Test a chat message".
- **API:** `GET/POST /owner/terminology`, `GET/PUT/DELETE /owner/terminology/{id}`, `GET /owner/terminology/lookup?message=` and `GET /owner/terminology/meta`. All sit behind the same `X-Owner-Key` gate as the other owner tools.

**Lookup**
- Deterministic, no embedding model:
  1. Exact normalized match of the extracted term against the term and its aliases.
  2. Example-query match.
  3. Whole-phrase alias containment.
  4. Conservative fuzzy match (≥ 0.85, for typos).
- Aliases carry the cross-language mapping (`strip`, `stripping`, `স্ট্রিপ`).
- Edits are read from disk on the next message: no reindex, no restart, **no retraining**.
- Alias clashes between terms are rejected, and ids are path-safe.

**Seed record:** one record, *Strip / Stripping*, was created from your example to verify the flow end to end. Edit or delete it in the UI.

## 7. RAG routing architecture

`rupsaa/rag/router.py` is a rule-based classifier (English, Banglish and Bengali regexes). It takes microseconds and makes no extra LLM call. `rupsaa/rag/context_builder.py` is now the single path used by both the API and the terminal chat.

| Route | Examples | Knowledge used |
|---|---|---|
| MEMORY | "ami age ki bolechilam?", "What did I say first?" | History, plus a one-line factual note; **no RAG** |
| FOLLOWUP | "এটা বাংলায় বুঝিয়ে বলো", "eta short kore bolo" | The previous turn's terms, carried over; no documents |
| TERMINOLOGY | "Strip mane ki?", "what does X mean?", "X বলতে কী বোঝায়?" | Terminology entry; documents only as a strict fallback |
| KNOWLEDGE | payout / policy / fee / identity questions | Documents (and any terms mentioned) |
| CASUAL | "kemon acho?", greetings, moods | Nothing |
| GENERAL | everything else | Documents only if they pass the strict filter |

**Retrieval fixes**
- `.metadata.json` was indexed as a document whose text was `{}`. It scored about 0.80 against *every* query.
  - The loader now skips hidden files.
  - Results are filtered with `is_hidden_source` as a second line of defence.
  - The index was rebuilt: 6 chunks. A backup of the old index is in `cache/knowledge_index_backup_pre_v02/`.
- **A higher threshold was measured and rejected.** multilingual-e5 scores casual chat *higher* than real questions ("Hi Rupsaa, kemon acho?" 0.841 vs "withdrawal minimum koto?" 0.798).
  - Instead, the router decides whether retrieval is eligible at all.
  - Within a retrieval, chunks more than `relative_margin` (0.04) below the best are dropped.
  - Strict routes also require keyword overlap between question and chunk.
- The document RAG toggle still gates documents. Terminology is consulted for definition questions regardless.
- The API response gains `route` and `terms_used`. Both are optional, and older clients are unaffected.

## 8. Conversation-memory findings and fix

**Trace**

| Stage | Finding |
|---|---|
| Frontend conversation ID | Correct: the ID is taken from each response and cleared on reset |
| API history | Stored correctly |
| Prompt construction and role order | system → history → user, via the tokenizer's chat template: correct |
| Truncation | 20-message cap, previously silent |

**Live reproduction on V0.1 (before the fix)**
- With RAG **off**: "ami ki color bolechilam?" → "blue" (worked).
- With RAG **on**: "What did I say first?" → *"I don't remember exactly what came before"*.
  - The sources were `.metadata.json` plus three `rupsaa_identity.md` chunks.
  - The RAG instruction ("if the retrieved context doesn't answer the question, say so") made the model deny having the history.

**Fixes**
- MEMORY-routed messages never get documents or terminology.
- They get one factual line instead: "The user is asking about something said earlier in this conversation. The conversation so far is above — answer from it directly."
- The conversation now tracks `dropped_messages`, so a "first message" question beyond the cap is answered honestly ("too far back").
- Memory was **not** put into RAG.

**Live result after the fix (same V0.1 adapter, RAG toggle on)**
- "What did I say first?" → *'I think you said "my favourite colour blue"'*
- "ami ki color bolechilam?" → *"…Your actual favorite was blue, right?"*
- Neither retrieved anything.

**Remaining data cause (§3):** V0.2 data needs multi-turn examples that answer recall questions from the actual history.

## 9. System-prompt mismatch

Training used `"You are Rupsaa."`; the app sends a persona prompt of about 300 tokens. The V0.1 evaluation ran both, 24 comparable replies each:

| | Avg length | "honestly" | Lists | Emoji | Script mirrored |
|---|---|---|---|---|---|
| V0.1 + production persona | 200 | 22/24 | 0 | 0 | 24/24 |
| V0.1 + training prompt | 259 | 20/24 | 1 | 0 | 23/24 |
| Base + production persona | 613 | 1/24 | 7 | **23/24** | 21/24 |
| Base + training prompt | 1,439 | 0/24 | 16 | 0 | 19/24 |

**Findings**
- **It doesn't conflict with the adapter:** the V0.1 behaviour is nearly identical under both prompts.
- **It doesn't cause or fix the tic:** that comes from the weights.
- **It largely duplicates what the adapter learned.** The only measurable gain is slightly better script mirroring and brevity, for about 300 extra prompt tokens every turn.
- **For base Qwen it backfires on emoji:** 23/24 replies used emoji despite "use emojis sparingly".
- **No runtime bug was found, so I made no persona change.** The only prompt additions are the terminology block and the memory note, which are routing-specific and short.

**Recommended V0.2 strategy: train as you serve**
1. Define one canonical V0.2 system prompt: a compact core of about 60–100 tokens with identity, language mirroring and brevity. Leave out the negative "never do X" lists.
2. Use that exact prompt in every V0.2 training record and at runtime.
3. Format RAG-aware and terminology training records with the *exact runtime blocks* ("Reference terminology: …", "Retrieved context: …") and the memory note, so the model learns what these blocks mean.
4. Keep behavioural shaping in the data, not the prompt.

## 10. Tests

**234 passed, 0 failed.** That's 158 pre-existing tests plus 76 new ones. No test loads the 7B model or the embedding model.

**New files**
- `tests/test_v02_routing_terminology.py`
- `tests/test_v02_dataset_quality.py`

**Coverage**
- Casual messages bypass RAG.
- Terminology routing, and alias retrieval in Bengali, Banglish and English.
- Fuzzy typos; disabled terms are not retrieved.
- CRUD, conflicts and path-safety; edits are live without a reindex.
- Metadata files are never returned as sources; the loader skips dotfiles.
- Low-confidence and irrelevant retrieval is suppressed; knowledge questions still use documents.
- Memory through the real service: "amar favourite color blue" → "ami ki color bolechilam?" and "What did I say first?" both use history with no RAG call.
- Follow-up term carry-over and reset.
- Owner API CRUD and auth; the chat schema stays backward compatible.
- A V0.1-shaped corpus (863/1129) is never training-ready.
- Repetitive openings are blocked; natural usage is allowed; per-language correlation is detected.
- The voice audit gives no credit for overused phrases.
- Bengali/Banglish detectors and repairs; triage classes; human-authored records are never auto-repaired.
- The export gate refuses; the V0.1 adapter config is compatible; the frozen V0.1 split counts are unchanged.

## 11. Recommended next step before V0.2 training

1. **Human review:** `scripts/v02_repair_review.py`. Priority order:
   1. the 48 Banglish and 52 mixed HUMAN_REVIEW records
   2. a native-speaker pass over the 212 Banglish REPAIR proposals (and a sample of the Bengali ones)
   3. the 7 REJECTs
2. **Targeted new data**, which the triage can't create:
   - multi-turn **memory-recall** examples answered from real history
   - **follow-up reformulation** ("এটা বাংলায় বুঝিয়ে বলো", "short kore bolo")
   - **terminology answers** grounded in the runtime "Reference terminology" block, in all three languages
   - varied response **structures**, to break the `S-` skeleton (27.5%)
   - more natural Banglish written from scratch, not translated
3. **Fix the prompt:** freeze the canonical V0.2 system prompt (§9) and rebuild records in that exact format.
4. **Only then:** build a V0.2 candidate set from accepted decisions, run `dataset_audit.py` (it must exit 0), approve deliberately (no bulk approval), snapshot, and export. The export gate enforces diversity.
5. **Evaluation for V0.2:** add memory, follow-up and terminology cases to `scripts/evaluate_v01.py`'s suite, and track tic rate as a tracked metric, not an anecdote.

---

## Appendix: live verification (V0.1 adapter, after the runtime fixes)

`bash scripts/start_rupsaa_v01.sh`, then chat through the web proxy on 5500 with the RAG toggle on.

| Message | Route | Knowledge | Reply (abridged) |
|---|---|---|---|
| Strip mane ki? | terminology | term-strip_stripping | "…jokhon kono kichu wear korার cheye remove korার dorkar…" — meaning partly right, Banglish garbled |
| what does stripping mean? | terminology | term-strip_stripping | "just removing clothing, often deliberately — casual undressing, a stage act, or an intimate performance…" ✓ |
| স্ট্রিপ মানে কী? | terminology | term-strip_stripping | Semantically wrong Bengali ✗ |
| এটা বাংলায় বুঝিয়ে বলো | followup | term carried over | Poor Bengali ✗ |
| Hi Rupsaa, kemon acho? | casual | none | ✓ (no sources) |
| What did I say first? | memory | none | "you said 'my favourite colour blue'" ✓ |
| How do payouts work for creators? | knowledge | creator_platform_faq.md, rupsaa_identity.md | "$20 minimum, monthly, 1st business day" ✓ grounded |

**Interpretation**
- Routing, retrieval and memory now behave correctly.
- The adapter's Bengali/Banglish answer quality and the "honestly" tic remain. They're weight-level problems, and the dataset work above exists to fix them in V0.2.
