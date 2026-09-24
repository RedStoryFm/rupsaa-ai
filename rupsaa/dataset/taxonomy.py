"""Rupsaa Dataset v1 taxonomy.

Every production conversation is tagged with exactly one `category` from
CATEGORIES below (plus a free-text `subcategory` for finer distinctions).
This is the single source of truth for allowed categories — scripts and
tests validate against this dict, not a hard-coded list duplicated
elsewhere.
"""

from __future__ import annotations

# slug -> human-readable description of what belongs in this category.
CATEGORIES: dict[str, str] = {
    "bengali_natural": "Natural conversation written in Bengali script (বাংলা).",
    "banglish_natural": "Natural conversation written in Banglish (Bengali in Latin script).",
    "english_conversation": "Natural conversation written in English.",
    "code_switch_bn_en": "Code-switching between Bengali script and English within a message or turn.",
    "code_switch_banglish_en": "Code-switching between Banglish and English within a message or turn.",
    "casual_friendly": "Everyday casual/friendly small talk, not tied to a specific topic.",
    "rupsaa_personality": "Conversations that establish or reinforce Rupsaa's identity, voice, and self-references.",
    "flirty_contextual_adult": "Playful/flirty exchanges between adults, contextually appropriate, never mechanical.",
    "relationship_dating": "Relationship and dating discussion: advice, venting, dynamics, communication.",
    "adult_terminology_education": "Plain, factual explanations of adult/sexual-health terminology and concepts.",
    "creator_platform_terminology": "Definitions and explanations of creator-platform-specific terms (PPV, chargeback, etc.).",
    "creator_questions_workflows": "Practical creator questions: pricing, verification, workflows, growth, policy.",
    "short_answers": "Deliberately short, punchy conversational responses.",
    "detailed_explanations": "Longer, structured explanations when the user wants depth.",
    "follow_up_questions": "Conversations where Rupsaa asks a genuinely useful clarifying/follow-up question.",
    "uncertainty_handling": "Conversations where Rupsaa correctly expresses uncertainty instead of guessing.",
    "correcting_misunderstandings": "Rupsaa correcting a factual or contextual misunderstanding, gracefully.",
    "multi_turn": "Longer multi-turn conversations (3+ exchanges) that require tracking context.",
    "rag_aware": "Conversations demonstrating grounded use of retrieved context, including 'no match' cases.",
    "adversarial_difficult_language": "Deliberately awkward, adversarial, slangy, or hard-to-parse user phrasing, to test robustness.",
}

LANGUAGES = {"bn", "banglish", "en", "mixed"}

TONES = {
    "casual", "warm", "playful", "flirty_contextual", "informative",
    "serious", "empathetic", "direct", "curious", "reassuring",
}

SOURCE_TYPES = {
    "human_authored", "human_edited", "imported", "synthetic_reviewed",
    # LLM-generated during dataset expansion, not yet human-reviewed —
    # distinct from synthetic_reviewed so review status stays honest and
    # source_type can be used for later weighting/filtering.
    "synthetic_curated",
}

# quality_status values. Physical storage only has three directories
# (drafts/, approved/, rejected/) — both "draft" and "needs_edit" live in
# drafts/, distinguished by this field. See rupsaa/dataset/store.py.
QUALITY_STATUSES = {"draft", "approved", "rejected", "needs_edit"}

STATUS_TO_DIR = {
    "draft": "drafts",
    "needs_edit": "drafts",
    "approved": "approved",
    "rejected": "rejected",
}

CONVERSATION_LENGTHS = {"short", "medium", "long"}


def is_valid_category(category: str) -> bool:
    return category in CATEGORIES


def describe_taxonomy() -> str:
    lines = [f"- {slug}: {desc}" for slug, desc in CATEGORIES.items()]
    return "\n".join(lines)
