#!/usr/bin/env python3
"""Base-model selection, step 1 (project environment, no model): the exact per-turn system prompt the Rupsaa
runtime would send for the 16-prompt session — router, language control, recall note, terminology + dance
stores, V0.2 prompt. Every candidate model receives these SAME prompts.
Writes data/production/reports/base_model_selection/contexts.json."""

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

PROMPTS = ["hi, tumi kemon acho?", "ajke amar mood ta bhalo na", "achcha", "tumi amar sathe banglish e kotha bolbe?",
           "Strip mane ki?", "Foreplay ki?", "এটা বাংলায় সহজ করে বুঝিয়ে বলো", "Belly dance ki?", "Kathak kothakar dance?",
           "এবার বাংলায় বলো", "মাম্বো কোথাকার নাচ?", "Breaking ar breakdance same?", "amar favourite color blue",
           "ami ki color bolechilam?", "what do you look like?", "are you human?"]


@dataclass
class Msg:
    role: str
    content: str


def main():
    ts, ds = TerminologyStore(PROJECT_ROOT / "knowledge/terminology"), DanceStore(PROJECT_ROOT / "knowledge/dance")
    history, prev, lang_state, out = [], None, None, []
    for i, user in enumerate(PROMPTS):
        k = build_turn_knowledge(user, use_rag=False, rag_query=None, terminology=ts, previous_terms=prev,
                                 history_messages=len(history), history_truncated=False, history=history,
                                 language_state=lang_state, dance=ds)
        if k.terms_used:
            prev = k.terms_used
        elif k.route not in ("followup", "memory"):
            prev = None
        lang_state = k.language_state
        system = build_system_prompt(prompt_version="v0.2", terminology_context=k.terminology_context,
                                     conversation_note=k.conversation_note,
                                     language_directive=directive_for(k.language_state if k.language else None),
                                     dance_context=k.dance_context)
        out.append({"turn": i + 1, "user": user, "route": k.route, "records": k.terms_used,
                    "requested_language": k.language, "system": system})
        history += [Msg("user", user), Msg("assistant", "<model reply>")]  # recall note lists user messages only
    p = PROJECT_ROOT / "data/production/reports/base_model_selection/contexts.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for t in out:
        print(t["turn"], t["user"], t["route"], t["records"], t["requested_language"])


if __name__ == "__main__":
    main()
