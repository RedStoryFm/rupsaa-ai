""""Teach Rupsaa" submission handling — the owner-only tool for manually
authoring conversation examples through the web UI.

This is intentionally a thin layer over the EXISTING production dataset
pipeline (schema, normalize, dedup, repetition, store) — it does not define
a second dataset format or a second validation path. Every example saved
here is a normal DatasetStore-backed draft, identical in shape to anything
scripts/dataset_import.py would produce, and flows through the same
audit/review/export tooling afterward.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rupsaa.dataset.config import load_dataset_config
from rupsaa.dataset.dedup import char_ngrams, conversation_text, fingerprint, jaccard_similarity
from rupsaa.dataset.normalize import normalize_messages
from rupsaa.dataset.repetition import assistant_messages
from rupsaa.dataset.schema import ConversationRecord, derive_conversation_length, validate_record
from rupsaa.dataset.store import DatasetStore
from rupsaa.dataset.taxonomy import LANGUAGES, is_valid_category

DEFAULT_SYSTEM_PROMPT = "You are Rupsaa."

# UI-facing language labels -> (language, language_mix) stored on the record.
LANGUAGE_OPTIONS = {
    "Bengali": ("bn", None),
    "Banglish": ("banglish", None),
    "English": ("en", None),
    "Bengali + English": ("mixed", "bn_en"),
    "Banglish + English": ("mixed", "banglish_en"),
}


@dataclass
class TeachTurn:
    user: str
    rupsaa: str


@dataclass
class TeachSubmission:
    turns: list[TeachTurn]
    language_label: str
    category: str
    subcategory: str | None = None
    tone: str | None = None
    notes: str = ""


@dataclass
class TeachResult:
    success: bool
    conversation_id: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _messages_from_turns(turns: list[TeachTurn]) -> list[dict]:
    messages = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}]
    for turn in turns:
        messages.append({"role": "user", "content": turn.user})
        messages.append({"role": "assistant", "content": turn.rupsaa})
    return messages


def submit_teach_example(store: DatasetStore, submission: TeachSubmission) -> TeachResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not submission.turns:
        return TeachResult(success=False, errors=["at least one USER/RUPSAA turn is required"])

    for i, turn in enumerate(submission.turns):
        if not turn.user or not turn.user.strip():
            errors.append(f"turn {i + 1}: USER message is empty")
        if not turn.rupsaa or not turn.rupsaa.strip():
            errors.append(f"turn {i + 1}: RUPSAA response is empty")

    if submission.language_label not in LANGUAGE_OPTIONS:
        errors.append(f"unknown language '{submission.language_label}' (allowed: {list(LANGUAGE_OPTIONS)})")

    if not is_valid_category(submission.category):
        errors.append(f"unknown category '{submission.category}'")

    if errors:
        return TeachResult(success=False, errors=errors)

    language, language_mix = LANGUAGE_OPTIONS[submission.language_label]
    if language not in LANGUAGES:
        errors.append(f"internal error: resolved language '{language}' not in taxonomy")
        return TeachResult(success=False, errors=errors)

    messages = normalize_messages(_messages_from_turns(submission.turns))
    cfg = load_dataset_config()
    record_id = store.generate_id(cfg["ids"]["prefix"], cfg["ids"]["padding"])

    record = ConversationRecord(
        id=record_id,
        messages=messages,
        language=language,
        language_mix=language_mix,
        category=submission.category,
        subcategory=(submission.subcategory or None),
        tone=(submission.tone or None),
        conversation_length=derive_conversation_length(messages, cfg["conversation_length_bins"]),
        source_type="human_authored",  # always — never trusts client input for this
        quality_status="draft",
        notes=submission.notes or "",
    )

    schema_errors = validate_record(record)
    if schema_errors:
        return TeachResult(success=False, errors=schema_errors)

    # Duplicate / near-duplicate check against the existing corpus (all
    # statuses — no point teaching something already approved or already
    # sitting in drafts).
    existing = [loc.record for loc in store.list_all(None)]
    new_fp = fingerprint(record)
    if any(fingerprint(r) == new_fp for r in existing):
        errors.append("this exact conversation already exists in the production dataset")
        return TeachResult(success=False, errors=errors)

    near_cfg = cfg["near_duplicate"]
    new_shingles = char_ngrams(conversation_text(record), near_cfg["ngram_size"])
    for r in existing:
        sim = jaccard_similarity(new_shingles, char_ngrams(conversation_text(r), near_cfg["ngram_size"]))
        if sim >= near_cfg["similarity_threshold"]:
            warnings.append(f"near-duplicate of existing conversation {r.id} (similarity {sim:.2f})")
            break  # one is enough to warn about

    # Repeated-reply check: would this push an assistant reply already used
    # elsewhere over the repetition threshold?
    new_reply_texts = [" ".join(m.split()).lower() for m in assistant_messages(record)]
    existing_reply_texts = [" ".join(m.split()).lower() for r in existing for m in assistant_messages(r)]
    min_count = cfg["thresholds"]["repeated_reply_min_count"]
    for reply in new_reply_texts:
        count = existing_reply_texts.count(reply) + 1
        if count >= min_count:
            warnings.append(f"this reply text would be repeated {count} times across the corpus (\"{reply[:60]}...\")")

    store.save_new(record)
    return TeachResult(success=True, conversation_id=record.id, warnings=warnings)
