# Knowledge V1 — import and real retrieval benchmark

Run date: 2026-10-01.

No training happened, and Gemma, the adapter, the serving prompt and the temperature are unchanged. Everything here
is knowledge data plus retrieval-layer code.

## Import

| | |
|---|---|
| Staging pack | `data/staging/knowledge_v1/`. All 4 checksums verified before anything was written: JSONL, CSV, XLSX and the eval file. |
| Pack contents | 358 records each in JSONL, CSV and XLSX; 209 private eval queries in a separate file that is never imported. |
| Pre-import backup | `backups/rupsaa-knowledge-20261001T160020Z.tar.gz`, which is git-ignored. |
| Imported to General Knowledge | 352 records, from the canonical JSONL through the real importer. The comparison against staging found 0 field differences across ids, `approved_by`, `verified`, `source_type` and all 129 sources. |
| Merged into Terminology | 6 records, one canonical active concept each. Production ids are kept (see below). |
| Approval state | `source_type: import`, `verified: false`, `approved_by: ""` (not owner-reviewed), `enabled: true`. Nothing is marked owner-approved. |
| 5 earlier GK test records | Kept and enabled (harmless). `approved_by` was corrected to blank, because the owner never reviewed them. |
| Totals | 40 Terminology + 60 Dance + 357 General Knowledge = **457 active concepts**. |

**The six overlaps.** The production Terminology id is kept in each case. Staging aliases, content and sources are
merged in. The merged content keeps its own provenance in `merged_from`: import, unverified and not approved.
Previous versions are in `knowledge/terminology/.history/`.

- consent → `term-consent`. The definition adopts the fuller staging summary, which contains the old one-liner. The
  "applies in marriage" guidance is added.
- foreplay → `term-foreplay`; aftercare → `term-aftercare`; edging → `term-edging`. Definitions are kept and the
  staging details are appended.
- bondage → `term-handcuffs_bondage`. Same scope (restraint with cuffs, ropes and similar), so the record keeps its
  title and gains safety basics.
- oral sex → `term-oral_play`. The scope was resolved deliberately as one concept, retitled "Oral Play / Oral Sex":
  - the definition covers mouth-on-body play generally, with oral sex (genitals or anus) as the specific meaning;
  - the STI facts are added.
- Aliases deliberately **not** merged, because they are ordinary-language false positives: `অনুমতি`, `পরবর্তী যত্ন`,
  `tying up`, `restraints` and `বন্ধন`.

## Importer fixes (with regression tests)

- **Approval.** A blank `approved_by` stays blank, and the store no longer defaults it to `owner`. The only accepted
  values are `""` and `owner`.
  - Records the owner creates in the Knowledge Manager or Teach page, or confirms in Teacher Mode, are
    `owner`-approved.
  - Toggling or editing a record never approves it.
- **Sources.**
  - CSV and XLSX now carry `sources` as a JSON-array cell; JSON and JSONL stay lossless. Import → export →
    re-import keeps them in every format.
  - A pre-existing export bug wrote `'` into every **empty** CSV/XLSX cell, which corrupted round trips. It is fixed.
  - The Knowledge Manager form keeps each source's title, domain and retrieved_at when a record is edited.
- **IDs.**
  - A valid supplied id is kept, and one is generated only when the record has none.
  - Unsafe ids are rejected.
  - A duplicate id in the same file is rejected.
  - An existing id is treated as an update and keeps the id.
  - A new id reusing an existing title or alias is a conflict.
- `.jsonl` import is supported.
- The Terminology schema gained `sources`, `source_type`, `verified`, `approved_by`, `merged_from` and `revision`,
  with backups on update and delete.

## Duplicate check after import

- 0 duplicate ids, 0 duplicate titles, 0 alias collisions across all three stores, and no same-title records in
  different categories.
- None of the 6 overlap `gk-*` records is active.
- Semantic near-duplicates (e5 cosine > 0.93):
  - pre-existing pairs of related Terminology entries;
  - Ejaculation ~ Semen and Sperm, which are distinct concepts.
- The pack's intentionally removed bare aliases (`ed`, `pan`, `prep`, `choking`, `plank`, `pe`, `ace`, `hinge`,
  `missionary`, `spanking` …) are not aliases anywhere. Some remain record **titles**, such as Plank (Fitness), where
  the match is correct.

## Benchmark method

- The benchmark runs the private 209-query set through `RupsaaService.chat`, Rupsaa's real pipeline:
  - the real router, follow-up state and priority rules;
  - the real stores and the multilingual-e5 embedder;
  - the UI default `use_rag=False`.
- Only Gemma is stubbed, and the web provider only records.
- Expected answers are never given to the retriever. Follow-ups replay their context turn first.
- Top-1 counts as correct when the first retrieved concept is an expected id or an accepted production id.
- A negative is correct when it retrieves nothing (where the query requires that) or nothing in a forbidden adult or
  Terminology/Dance class.

## Results

| Metric | Before fixes | After fixes |
|---|---|---|
| Positive queries | 169 | 169 |
| Top-1 accuracy | 61.5 % (104) | **88.2 % (149)** |
| Top-3 accuracy | 62.7 % | 88.2 % |
| Positive recall (any result) | 64.5 % | 89.3 % |
| Wrong concept | 5 | 2 |
| No result | 60 | 18 |
| Negative queries | 40 | 40 |
| Negatives correctly rejected | 40 (100 %) | **40 (100 %)** |
| False-positive rate | 0 % | **0 %** |

Fixes changed 45 queries from failing to passing, and 0 from passing to failing.

Positive Top-1 by language:

| Language | Before | After |
|---|---|---|
| English (55) | 43.6 % | 92.7 % |
| Banglish (79) | 68.4 % | 82.3 % |
| Bengali (33) | 75.8 % | 97.0 % |
| Mixed (2) | 50 % | 50 % |

All-query accuracy after fixes, by category:

| Category | Accuracy |
|---|---|
| Terminology | 100 % |
| Adult Terminology | 95.2 % |
| Sexual Education | 86.2 % |
| Relationships | 85.2 % |
| Other General Knowledge | 86.4 % |
| Dating | 70.0 % |
| Negatives | 100 % |

## Retrieval-layer fixes

These are small systematic fixes. No eval query was used as an alias, no threshold was lowered, and no answers are
hardcoded.

1. **Lookup gate.**
   - *Before:* General Knowledge was only consulted for messages that looked like a question **and** had no personal
     pronoun. That missed topic phrases, single-word topics and personal questions (43 queries).
   - *Now:* Curated knowledge is consulted for everything except small talk, memory questions and follow-ups. The
     strict guards still decide.
2. **Short messages (≤ 3 words, not a question).** These match only when the whole message *is* a title or alias, or
   a typo of one. A common word inside them never matches, which protects against things like "breaking news".
3. **Specificity.** When one matched name contains another, the longer, more specific one wins, including GK over
   Terminology.
4. **Bengali endings.** -এর, -ে, -তে, -কে, -দের … are tolerated for whole-word name matches.
5. **Follow-ups.**
   - New router patterns: "explain/say it in <language>" requests, "aro detail(s) e bolo"-style more-detail
     requests, and "X meaning" without "?".
   - A short question that names no topic of its own carries the active topic. Fresh/current, small talk and
     identity questions never do.
6. **Ranking among name hits.**
   - Name hits are ordered by semantic similarity.
   - A semantic match that passes **every** existing guard (score ≥ 0.85 **and** name coverage) outranks a phrase hit
     only when it is clearly closer (margin ≥ 0.03).
   - Exact names are never overridden.
7. **False-positive protection.** Kitchen and cooking context blocks phrase hits on Terminology words, in the same
   way the existing programming-context guard works: "coffee grind" and "ek spoon chini" no longer reach adult
   entries.

Thresholds are unchanged: `SEMANTIC_MIN_SCORE` is still 0.85, and name coverage is still required. Every
adult-forbidden negative scores below 0.86. Several of them, such as "choking on food" at 0.857, are only rejected
by the name-coverage guard, so loosening it was rejected.

## Remaining failures (20 of 209)

| Type | Count | What it means |
|---|---|---|
| language/script issue | 6 | Colloquial Banglish phrasing far from any alias; e5 scores are 0.80–0.85, under the threshold. |
| threshold too strict | 5 | A correct top semantic hit fails the name-coverage guard, or a short non-question message (deliberately exact-only). |
| alias gap | 4 | The colloquial way of naming the concept isn't an alias yet. |
| embedding miss | 3 | The correct record is ranked 2nd or lower semantically. |
| semantic collision | 1 | A broader record's name hit wins over the more specific concept. |
| follow-up context issue | 1 | An elliptical follow-up carried the previous concept rather than the related one expected. |

Most of these are alias/data gaps for owner curation: the colloquial Banglish wording for a concept. They should be
fixed by the owner reviewing aliases, never by copying eval questions.

## False-positive probes (real pipeline)

None of these attaches adult knowledge:

| Probe | Result |
|---|---|
| strip whitespace | none |
| PAN card | none |
| Ed Sheeran | none |
| choking on food | none |
| plank exercise | Fitness "Plank" (correct, not adult) |
| breaking news | none |
| popping a balloon | none |
| locking a door | none |
| house price | none |

Also clean: the Banglish variants, "coffee grind kivabe kori", "ek spoon chini", "start from scratch", greetings and
mood talk.

## Files

- `METRICS.json` — aggregates before, after the routing fixes and after; committed.
- `RESULTS.json` — per-query results; git-ignored because it contains the private eval queries.
- `FAILURES.json` — per-query failures; git-ignored for the same reason.
- To reproduce: `python scripts/eval_knowledge_v1.py --label after`. It reads the frozen eval file and never writes
  it anywhere tracked.
