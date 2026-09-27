#!/usr/bin/env python3
"""Build the Rupsaa V0.2.2 DRAFT correction set + its human-review file (never trains, never freezes).

    python scripts/v022_build_draft.py

Replays data/production/corrective/rupsaa_v0.2.2_draft/source_conversations.py through the real
runtime (same code path as the V0.2.1 corrective builder) and writes, in that folder:
  draft_records.jsonl   runtime system prompt + turns + runtime_trace, review_status=pending_native_review
  HUMAN_REVIEW.md       every record, every turn, with KEEP / EDIT / DROP boxes and the lint findings
Lints (from the V0.2.2 rescue audit): Latin letters inside Bengali-script replies, Bengali danda in Latin
text, template openers, the typo template on correctly spelled input, human-life claims, the owner's
exact diagnostic prompts. Lint findings are listed for the reviewer; they are not the review.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from rupsaa.rag.dance import DanceStore  # noqa: E402
from rupsaa.rag.terminology import TerminologyStore  # noqa: E402
from scripts.v021_build_corrective import build, load_source  # noqa: E402

DIR = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.2_draft"
OWNER_DIAGNOSTIC = {"hi, tumi kemon acho?", "ajke amar mood ta bhalo na", "achcha", "Strip mane ki?", "Foreplay ki?",
                    "এটা বাংলায় বুঝিয়ে বলো", "Belly dance ki?", "Kathak kothakar dance?", "এবার বাংলায় বলো",
                    "tumi dekhte kemon?", "tumi amar sathe banglish e kotha bolbe?", "strip ta ektu simple kore bojhao"}
BN = re.compile(r"[ঀ-৿]")
TEMPLATE = re.compile(r"^(fair\b|sotti bolte|notice kora|interesting (question|thought))|nijer modhhe|emon kichu\?|er kotha bolcho",
                      re.I)
HUMAN = re.compile(r"\b(khaisi|kheyechi|amar chul|amar chokh|coffee khai|cha khai)\b|আমার চুল|চা খেতে", re.I)


def lint(user: str, reply: str) -> list[str]:
    out = []
    if BN.search(reply) and re.search(r"[A-Za-z]", reply):
        out.append("Latin letters inside a Bengali-script reply")
    if not BN.search(reply) and "।" in reply:
        out.append("Bengali danda in Latin text")
    if TEMPLATE.search(reply):
        out.append("template phrase from the audit")
    if HUMAN.search(reply):
        out.append("human-life claim")
    if user in OWNER_DIAGNOSTIC:
        out.append("uses an owner diagnostic prompt verbatim")
    return out


def main() -> None:
    store = TerminologyStore(PROJECT_ROOT / "knowledge/terminology")
    dance = DanceStore(PROJECT_ROOT / "knowledge/dance")
    convs = load_source(DIR / "source_conversations.py")
    records, errors = build(convs, store, dance)
    # a record whose final turn does not get its expected knowledge is a RUNTIME gap, not a data error:
    # it is kept for review and flagged (training it as-is would teach facts without the record in the prompt)
    gaps = {e.split(":")[0]: e.split(": ", 1)[1] for e in errors if "final turn attaches" in e}
    fatal = [e for e in errors if "final turn attaches" not in e]
    if fatal:
        print("BUILD ERRORS:\n  " + "\n  ".join(fatal))
        sys.exit(1)
    lines = ["# Rupsaa V0.2.2 DRAFT correction set — HUMAN REVIEW (native Bengali/Banglish speaker)", "",
             f"{len(records)} records, all **drafted by Claude (AI)** from the rescue diagnosis. Nothing here is frozen or trained.",
             "Read every reply aloud. Mark each record KEEP / EDIT (write the fix) / DROP. Judge: would a Kolkata/Dhaka",
             "20-something actually text this? Is every fact exactly the record's? Is the Bengali natural, not translated?", "",
             "Owner decision needed first: records d022-001…012, 099, 100 make Rupsaa say plainly that it is an AI with no body.",
             "If the persona should not say this, DROP that block and tell me the intended answer instead.", ""]
    lint_total = 0
    for conv, rec in zip(convs, records):
        rec["source_type"] = "v022_draft_ai_written"
        rec["review_status"] = "pending_native_review"
        trace = rec["runtime_trace"]
        lines.append(f"## {rec['id']} · {rec['category']} · {rec['language']}")
        if rec["id"] in gaps:
            rec["runtime_gap"] = gaps[rec["id"]]
            lines.append(f"**RUNTIME GAP — do not train until fixed:** {gaps[rec['id']]}")
        for (user, reply), t in zip(conv["turns"], trace):
            found = lint(user, reply)
            lint_total += len(found)
            lines.append(f"- USER: {user}  \n  RUPSAA: {reply}  \n  _runtime: {t['route']} · "
                         f"{', '.join(t['terms_used']) or '-'} · {t['requested_language'] or 'mirror'}_"
                         + (f"  \n  **lint: {'; '.join(found)}**" if found else ""))
        lines += ["", "- [ ] KEEP  - [ ] EDIT: ______  - [ ] DROP", ""]
    (DIR / "draft_records.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    (DIR / "HUMAN_REVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    by = {}
    for r in records:
        by[r["category"]] = by.get(r["category"], 0) + 1
    langs = {}
    for r in records:
        langs[r["language"]] = langs.get(r["language"], 0) + 1
    print(json.dumps({"records": len(records), "by_category": by, "by_language": langs, "lint_findings": lint_total,
                      "runtime_gaps": gaps}, indent=1))


if __name__ == "__main__":
    main()
