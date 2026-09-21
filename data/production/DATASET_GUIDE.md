# Rupsaa Dataset v1 — Production Guide

This is the guide for writing, importing, reviewing, and exporting the real
Rupsaa training dataset (target: ~5,000–15,000 curated conversations). It
covers the taxonomy, metadata, quality bar, anti-repetition rules, and the
full command workflow.

This is separate from `data/examples/starter_conversations.jsonl`, which is
a small pipeline-verification set and is never modified by anything in this
directory.

---

## 1. How this workspace is organized

```
data/production/
├── drafts/      newly imported conversations, and anything marked NEEDS_EDIT
├── approved/    conversations cleared for training export
├── rejected/    conversations rejected, with a reason in "notes"
├── exports/     train.jsonl / validation.jsonl / test.jsonl generated from approved/
└── reports/     audit + stats reports (Markdown + JSON), timestamped
```

Every conversation is one JSON file, named `<id>.json` (e.g. `rup-000042.json`),
living in exactly one of `drafts/`, `approved/`, `rejected/`. There are four
review statuses but three physical directories — `draft` and `needs_edit`
both live in `drafts/`, distinguished by the `quality_status` field inside
the file:

| quality_status | physical directory |
|---|---|
| `draft` | `drafts/` |
| `needs_edit` | `drafts/` |
| `approved` | `approved/` |
| `rejected` | `rejected/` |

## 2. The 20 categories

Every conversation gets exactly one `category` (the full list with
descriptions lives in `rupsaa/dataset/taxonomy.py` — this table must match
it):

| category | what belongs here |
|---|---|
| `bengali_natural` | Natural conversation written in Bengali script |
| `banglish_natural` | Natural conversation written in Banglish (Bengali in Latin letters) |
| `english_conversation` | Natural conversation written in English |
| `code_switch_bn_en` | Bengali script + English mixed within a turn |
| `code_switch_banglish_en` | Banglish + English mixed within a turn |
| `casual_friendly` | Everyday small talk, not topic-specific |
| `rupsaa_personality` | Establishes/reinforces Rupsaa's identity and voice |
| `flirty_contextual_adult` | Playful/flirty between adults, contextual, never mechanical |
| `relationship_dating` | Relationship/dating advice, venting, dynamics |
| `adult_terminology_education` | Plain factual explanations of adult/sexual-health terms |
| `creator_platform_terminology` | Definitions of creator-platform jargon (PPV, chargeback, etc.) |
| `creator_questions_workflows` | Practical creator questions: pricing, verification, growth |
| `short_answers` | Deliberately short, punchy responses |
| `detailed_explanations` | Longer, structured explanations when depth is warranted |
| `follow_up_questions` | Rupsaa asks a genuinely useful clarifying question |
| `uncertainty_handling` | Rupsaa correctly admits uncertainty instead of guessing |
| `correcting_misunderstandings` | Rupsaa gracefully corrects a factual/contextual error |
| `multi_turn` | 3+ exchange conversations requiring context tracking |
| `rag_aware` | Grounded use of retrieved context, including "no match" cases |
| `adversarial_difficult_language` | Deliberately awkward/slangy/hard-to-parse user phrasing |

Use `subcategory` (free text) for finer distinctions within a category,
e.g. `category: creator_questions_workflows`, `subcategory: pricing`.

## 3. Metadata fields

```json
{
  "id": "rup-000042",
  "language": "banglish",
  "language_mix": "banglish_en",
  "category": "code_switch_banglish_en",
  "subcategory": "work_stress",
  "tone": "empathetic",
  "conversation_length": "short",
  "source_type": "human_authored",
  "quality_status": "draft",
  "notes": "",
  "created_at": "2026-09-21T18:20:00+00:00",
  "updated_at": "2026-09-21T18:20:00+00:00",
  "messages": [
    {"role": "system", "content": "You are Rupsaa."},
    {"role": "user", "content": "ajke mon ta kharap"},
    {"role": "assistant", "content": "ki hoyeche bolo to?"}
  ]
}
```

| field | values | notes |
|---|---|---|
| `id` | `rup-000001`, ... | auto-assigned on import if missing |
| `language` | `bn`, `banglish`, `en`, `mixed` | primary language tag |
| `language_mix` | free text, e.g. `bn_en` | optional, for code-switch categories |
| `category` | one of the 20 above | required |
| `subcategory` | free text | optional |
| `tone` | e.g. `casual`, `warm`, `playful`, `flirty_contextual`, `informative`, `serious`, `empathetic`, `direct`, `curious`, `reassuring` | optional but encouraged |
| `conversation_length` | `short`/`medium`/`long` | auto-derived from turn count if omitted |
| `source_type` | `human_authored`, `human_edited`, `imported`, `synthetic_reviewed` | be honest — this matters for later quality audits |
| `quality_status` | `draft`, `needs_edit`, `approved`, `rejected` | set by the review workflow, not by you when authoring |
| `notes` | free text | **required** when `quality_status: rejected` |
| `messages` | list of `{role, content}` | exactly what the QLoRA pipeline consumes |

You do **not** need to write all of this by hand. You can author plain
conversations (just `messages`, optionally with `category`) and supply the
rest as `--category`/`--language`/`--tone` defaults on import — see §5.

## 4. What makes a HIGH-QUALITY Rupsaa conversation

**Write like a real person, not a template.** The single biggest risk with
a dataset this size is that it starts to sound machine-generated *because
it's too consistent*. Vary these deliberately, conversation to conversation:

- **Openings.** Don't start every reply the same way. Avoid "Aww", "Haha",
  "Obviously" as a reflexive first word across many examples.
- **Sentence length.** Mix short punchy replies with longer flowing ones.
  Real texting isn't uniform.
- **Vocabulary.** Don't reuse the same adjectives/verbs across unrelated
  conversations. If you catch yourself typing "sotti bolchi" or "honestly"
  for the fifth time, change it.
- **Bengali/Banglish spelling.** Bengali written in Latin script doesn't
  have one canonical spelling — "bhalo"/"valo", "acho"/"achho" are both
  fine. Don't force every contributor into identical transliteration; real
  users won't be consistent either.
- **Response structure.** Not every reply needs a question at the end. Not
  every reply needs an emoji. Not every reply needs to open with
  acknowledgment before answering.
- **Emoji usage.** Use sparingly and only where it adds something. Most
  replies should have zero emoji. See the anti-repetition rules below.
- **Directness vs. softness.** Rupsaa should sometimes just answer
  directly, and sometimes soften/hedge — vary this based on the actual
  conversational context, not a fixed formula.
- **Explanation style.** For `detailed_explanations`, vary between
  numbered steps, prose paragraphs, and a mix — don't make every long
  answer a 5-point numbered list.

**A good conversation is specific, not generic.** "How are you?" /
"I'm good, how are you?" teaches nothing. Give the user message real
content and the assistant reply something that responds to that specific
content.

**For `adult_terminology_education`**: definitional and factual, the way a
knowledgeable, non-judgmental friend would explain it. Not clinical/sterile,
not explicit erotica.

**For `flirty_contextual_adult`**: the flirtation should read as responding
to *this specific message*, not as a generic flirty template that could be
copy-pasted into any conversation.

**For `rag_aware`**: include a `Retrieved context:` block in the system
message (see the example in the seed batch) and make sure the assistant
reply is actually grounded in it — including the "context doesn't answer
this" case, which needs coverage too, not just successful grounding.

## 5. Anti-repetition rules (checked by `dataset_audit.py`)

Configured in `configs/dataset_production.yaml`, section `style_watchlist`
and `thresholds`. None of these words/emoji are forbidden — Rupsaa should
use them sometimes, naturally. The audit flags **overuse**, not usage:

- **Pet names** (`baby`, `babe`, `jaan`, `jaanu`, `sona`, `sweetheart`,
  `cutie`): flagged if any one appears in more than **15%** of all
  assistant messages in the audited set.
- **Filler words** (`hehe`, `haha`, `obviously`): same 15% threshold.
- **Emoji** (`💕`, `😘`, `😉`, `😏`, `❤️`, `🥰`): same 15% threshold per
  specific emoji, PLUS:
  - no single assistant message should contain more than **2** emoji total
  - no more than **50%** of all assistant messages should contain *any*
    emoji at all
- **Repeated exact replies**: the same assistant reply (normalized
  whitespace, case-insensitive) appearing **3+ times** across the dataset
  is flagged.
- **Near-duplicate conversations**: conversations that are >85% similar
  (character 5-gram Jaccard) are flagged for review — usually means two
  contributors wrote near-identical examples.

When the audit flags something, it does not auto-reject — a human decides
whether it's actually a problem (e.g. two similar conversations in
different languages are fine; two near-identical English ones probably
aren't).

## 6. Workflow

```
write conversations (JSONL, plain or with metadata)
        │
        ▼
scripts/dataset_import.py    → normalizes, validates, assigns ids, writes to drafts/
        │
        ▼
scripts/dataset_audit.py     → duplicate/near-dup/repetition/style checks + report
        │
        ▼
scripts/dataset_review.py    → approve / reject / needs-edit, per conversation
        │
        ▼
scripts/dataset_report.py    → coverage report: which categories/languages are thin
        │
        ▼
scripts/dataset_export.py    → approved/ → train.jsonl/validation.jsonl/test.jsonl
                                (validated against the existing QLoRA pipeline's
                                 own validator before being called done)
```

### Authoring format

The simplest way to write conversations is plain JSONL, one per line, just
like `data/examples/starter_conversations.jsonl`:

```json
{"category": "banglish_natural", "language": "banglish", "tone": "casual", "messages": [{"role": "system", "content": "You are Rupsaa."}, {"role": "user", "content": "ajke mon bhalo na"}, {"role": "assistant", "content": "ki hoyeche bolo to?"}]}
```

Any field you omit falls back to whatever you pass as a CLI default on
import (`--category`, `--language`, `--tone`, etc.) — but `category` must
be resolvable one way or the other, and must be a real taxonomy slug (see
§2), not a free-text label.

### Commands

**Import** a batch of newly written conversations into `drafts/`:

```bash
python scripts/dataset_import.py --input my_batch.jsonl --source-type human_authored
```

Per-record fields win over CLI defaults. One bad record in a batch is
skipped and reported — it never blocks the rest of the import. Exits
non-zero if anything failed, so check output before assuming a clean import.

**Audit** for duplicates, near-duplicates, repetition, and style overuse:

```bash
python scripts/dataset_audit.py                       # audits draft + approved
python scripts/dataset_audit.py --status all
python scripts/dataset_audit.py --category relationship_dating
```

Schema/Unicode errors are hard failures (non-zero exit). Everything else
(duplicates, near-dups, style overuse) is a warning for you to act on.

**Review** — list, inspect, and decide:

```bash
python scripts/dataset_review.py list --status draft
python scripts/dataset_review.py list --category flirty_contextual_adult --language banglish
python scripts/dataset_review.py show rup-000042
python scripts/dataset_review.py approve rup-000042 --notes "good variation, passed audit"
python scripts/dataset_review.py reject rup-000043 --notes "too close to rup-000012, redo"
python scripts/dataset_review.py needs-edit rup-000044 --notes "reply too long for this category"
python scripts/dataset_review.py to-draft rup-000043    # undo a decision
```

**Report** — see coverage gaps by category/language/tone:

```bash
python scripts/dataset_report.py                 # approved only
python scripts/dataset_report.py --status draft   # see what's queued
```

Watch the "Categories with ZERO approved examples" output — that's your
todo list for what to write next.

**Export** approved conversations for training:

```bash
python scripts/dataset_export.py
```

Writes `data/production/exports/{train,validation,test}.jsonl`, strips all
production metadata down to `{"messages": [...]}`, and re-validates the
output with the existing pipeline's own `scripts/validate_dataset.py`
logic before declaring success. This never touches `data/train.jsonl` or
`data/examples/` — to actually train on the export, either point
`configs/training.yaml`'s `data.train_path`/`data.validation_path` at
`data/production/exports/`, or copy the files into `data/` yourself when
you're ready.

## 7. Scaling toward 5,000–15,000

Do not generate thousands of examples synthetically and call it done. The
intended process is: humans (or a human reviewing LLM-assisted drafts)
write real conversations in batches, run them through import → audit →
review, and only approved ones count toward the total. Use
`scripts/dataset_report.py` regularly to check category/language balance —
a dataset that's 90% English `casual_friendly` isn't ready no matter how
large the raw count is.

If you use an LLM to help draft candidate conversations, import them with
`--source-type synthetic_reviewed` (only after a human has actually read
and edited them — don't import raw unreviewed LLM output as
`synthetic_reviewed`), and expect a higher rejection/needs-edit rate. The
audit and review workflow exists specifically to keep synthetic volume from
degrading dataset quality.
