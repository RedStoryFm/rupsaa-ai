#!/usr/bin/env python3
"""Build the Rupsaa V0.2.1 corrective records from the hand-written source.

    python scripts/v021_build_corrective.py

Train-as-serve: every conversation is replayed turn by turn through the REAL
runtime (rupsaa.rag.context_builder.build_turn_knowledge with the live
terminology store, the recall note, the language control), carrying state the
way api/services.py does. The record's single system prompt is the one the app
would send on the FINAL turn (LLaMA-Factory 0.7.1 uses one system prompt per
record); the per-turn routes are kept in `runtime_trace` for review.

Fails if a conversation's final turn does not attach exactly its expect_terms.
Writes data/production/corrective/rupsaa_v0.2.1/corrective_records.jsonl.
Does not touch the frozen V0.2 dataset; nothing is exported for training here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from rupsaa.conversation.language_control import directive_for  # noqa: E402
from rupsaa.personality.system_prompt import build_system_prompt  # noqa: E402
from rupsaa.rag.context_builder import build_turn_knowledge  # noqa: E402
from rupsaa.rag.dance import DanceStore  # noqa: E402
from rupsaa.rag.terminology import TerminologyStore  # noqa: E402

CORR_DIR = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.1"
SOURCE = CORR_DIR / "source_conversations.py"
OUT = CORR_DIR / "corrective_records.jsonl"


@dataclass
class Msg:
    role: str
    content: str


def load_source(path: Path = SOURCE) -> list[dict]:
    spec = importlib.util.spec_from_file_location("v021_source", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CONVERSATIONS


def replay(conv: dict, store: TerminologyStore, dance: DanceStore | None = None) -> dict:
    """Run a conversation through the runtime exactly like RupsaaService.chat does."""
    history: list[Msg] = []
    previous_terms, language_state = None, None
    trace, k = [], None
    for user, assistant in conv["turns"]:
        k = build_turn_knowledge(user, use_rag=False, rag_query=None, terminology=store, previous_terms=previous_terms,
                                 history_messages=len(history), history_truncated=False, history=history,
                                 language_state=language_state, dance=dance)
        trace.append({"user": user, "route": k.route, "terms_used": k.terms_used, "requested_language": k.language})
        if k.terms_used:
            previous_terms = k.terms_used
        elif k.route not in ("followup", "memory"):
            previous_terms = None
        language_state = k.language_state
        history += [Msg("user", user), Msg("assistant", assistant)]
    system = build_system_prompt(prompt_version="v0.2", terminology_context=k.terminology_context,
                                 conversation_note=k.conversation_note,
                                 language_directive=directive_for(k.language_state if k.language else None),
                                 dance_context=k.dance_context)
    messages = [{"role": "system", "content": system}]
    for user, assistant in conv["turns"]:
        messages += [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]
    return {"id": conv["id"], "category": conv["category"], "language": conv["language"],
            "source_type": "v021_corrective_handwritten", "review_status": "pending_owner_review",
            "messages": messages, "runtime_trace": trace}


def build(convs: list[dict], store: TerminologyStore, dance: DanceStore | None = None) -> tuple[list[dict], list[str]]:
    records, errors = [], []
    seen = set()
    for conv in convs:
        if conv["id"] in seen:
            errors.append(f"{conv['id']}: duplicate id")
        seen.add(conv["id"])
        rec = replay(conv, store, dance)
        final = set(rec["runtime_trace"][-1]["terms_used"])
        want = set(conv.get("expect_terms", []))
        if final != want:
            errors.append(f"{conv['id']}: final turn attaches {sorted(final)}, expected {sorted(want)}")
        records.append(rec)
    return records, errors


DANCE_SOURCE = CORR_DIR / "dance_conversations.py"
DANCE_OUT = CORR_DIR / "dance_records.jsonl"
DANCE_HOLDOUT_OUT = CORR_DIR / "dance_holdout_records.jsonl"


def load_dance_source(path: Path = DANCE_SOURCE) -> tuple[list[dict], list[dict]]:
    spec = importlib.util.spec_from_file_location("v021_dance_source", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DANCE_TRAIN, mod.DANCE_HOLDOUT


def build_all() -> tuple[dict[Path, list[dict]], list[str]]:
    """Corrective + dance train + dance held-out, all through the runtime with the live dance store."""
    store = TerminologyStore(PROJECT_ROOT / "knowledge/terminology")
    dance = DanceStore(PROJECT_ROOT / "knowledge/dance")
    corrective, errors = build(load_source(), store, dance)
    train, holdout = load_dance_source()
    dance_train, e2 = build(train, store, dance)
    dance_hold, e3 = build(holdout, store, dance)
    for r in dance_train + dance_hold:
        r["source_type"] = "v021_dance_handwritten"
    for r in dance_hold:
        r["review_status"] = "held_out_never_train"
    ids = [r["id"] for r in corrective + dance_train + dance_hold]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    return ({OUT: corrective, DANCE_OUT: dance_train, DANCE_HOLDOUT_OUT: dance_hold},
            errors + e2 + e3 + [f"duplicate id {d}" for d in dupes])


def main() -> None:
    outputs, errors = build_all()
    if errors:
        print("BUILD ERRORS:\n  " + "\n  ".join(errors))
        sys.exit(1)
    for path, records in outputs.items():
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        print(f"{len(records)} records -> {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
