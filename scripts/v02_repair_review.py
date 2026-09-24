#!/usr/bin/env python3
"""Human review of V0.2 triage / repair proposals (never approves anything).

Reads the triage produced by scripts/v02_dataset_diagnosis.py and records
YOUR decisions in data/production/v0.2_workspace/review_decisions.jsonl.
Records, quality_status, approvals and the frozen V0.1 snapshot/export are
never touched — building a V0.2 candidate set from accepted decisions is a
separate, later step.

Usage:
    python scripts/v02_repair_review.py summary
    python scripts/v02_repair_review.py next                       # next undecided, Banglish/mixed/bn first
    python scripts/v02_repair_review.py next --language banglish --class REPAIR
    python scripts/v02_repair_review.py show rup-000811
    python scripts/v02_repair_review.py decide rup-000811 accept   [--note "..."]
    python scripts/v02_repair_review.py decide rup-000811 keep-original
    python scripts/v02_repair_review.py decide rup-000811 reject   --note "incoherent reply 2"
    python scripts/v02_repair_review.py decide rup-000811 edit --reply 1 "Bhalo achi! Tumi?" [--reply 3 "..."]
    python scripts/v02_repair_review.py sheet [--limit 60]          # Markdown review sheet (original vs proposal)

Decisions: accept (take the proposal), keep-original, reject, edit (your own
text for the given assistant reply numbers, 1-based, applied on top of the
proposal). The latest decision per record wins.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import PROJECT_ROOT, default_base_dir  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402

TRIAGE = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_preparation/triage.jsonl"
DECISIONS = PROJECT_ROOT / "data/production/v0.2_workspace/review_decisions.jsonl"
SHEET = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_preparation/REPAIR_REVIEW_SHEET.md"
LANG_PRIORITY = {"banglish": 0, "mixed": 1, "bn": 2, "en": 3}
CLASS_PRIORITY = {"HUMAN_REVIEW": 0, "REPAIR": 1, "REJECT": 2, "KEEP": 3}
ACTIONS = ("accept", "keep-original", "reject", "edit")


def load_triage(path: Path = TRIAGE) -> list[dict]:
    if not path.exists():
        sys.exit(f"{path} not found — run: python scripts/v02_dataset_diagnosis.py")
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def load_decisions(path: Path = DECISIONS) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.exists():
        for line in open(path, encoding="utf-8"):
            d = json.loads(line)
            out[d["record_id"]] = d  # latest wins
    return out


def original_messages(record_id: str) -> list[dict]:
    loc = DatasetStore(default_base_dir()).load(record_id)
    if loc is None:
        sys.exit(f"record {record_id} not found")
    return loc.record.messages


def assistant_turns(messages: list[dict]) -> list[int]:
    return [i for i, m in enumerate(messages) if m.get("role") == "assistant"]


def render(entry: dict) -> str:
    orig = original_messages(entry["record_id"])
    prop = entry.get("proposed_messages") or orig
    lines = [
        f"=== {entry['record_id']}  [{entry['classification']}]  {entry['language']} / {entry['category']} / "
        f"{entry['source_type']} / status={entry['quality_status']}",
        f"reasons: {'; '.join(entry['reasons'])}",
    ]
    for issue in entry["issues"]:
        lines.append(f"  ! {issue['code']} (msg {issue['turn_index']}): {issue['detail']}")
    if entry.get("residual_issues"):
        lines.append(f"  residual after proposal: {entry['residual_issues']}")
    reply_no = 0
    for i, m in enumerate(orig):
        if m["role"] == "system":
            continue
        if m["role"] == "user":
            lines.append(f"\nUSER: {m['content']}")
            continue
        reply_no += 1
        new = prop[i]["content"]
        if new == m["content"]:
            lines.append(f"RUPSAA [{reply_no}]: {m['content']}")
        else:
            lines.append(f"RUPSAA [{reply_no}] original: {m['content']}")
            lines.append(f"RUPSAA [{reply_no}] proposed: {new}")
    return "\n".join(lines)


def cmd_summary(args) -> None:
    triage = load_triage()
    decisions = load_decisions()
    print("classification:", dict(Counter(t["classification"] for t in triage)))
    by_lang = Counter((t["language"], t["classification"]) for t in triage)
    for lang in sorted(LANG_PRIORITY, key=LANG_PRIORITY.get):
        print(f"  {lang:9}", {c: by_lang.get((lang, c), 0) for c in CLASS_PRIORITY})
    print(f"decisions recorded: {len(decisions)}", dict(Counter(d["action"] for d in decisions.values())))
    pending = [t for t in triage if t["classification"] in ("REPAIR", "HUMAN_REVIEW") and t["record_id"] not in decisions]
    print(f"pending REPAIR/HUMAN_REVIEW decisions: {len(pending)}")


def _queue(args) -> list[dict]:
    triage = load_triage()
    decisions = load_decisions()
    q = [t for t in triage if t["record_id"] not in decisions]
    q = [t for t in q if t["classification"] in ((args.klass,) if args.klass else ("REPAIR", "HUMAN_REVIEW"))]
    if args.language:
        q = [t for t in q if t["language"] == args.language]
    if args.source:
        q = [t for t in q if t["source_type"] == args.source]
    return sorted(q, key=lambda t: (LANG_PRIORITY.get(t["language"], 9), CLASS_PRIORITY[t["classification"]], t["record_id"]))


def cmd_next(args) -> None:
    q = _queue(args)
    if not q:
        print("nothing pending for this filter")
        return
    print(f"({len(q)} pending)\n")
    print(render(q[0]))


def cmd_show(args) -> None:
    for t in load_triage():
        if t["record_id"] == args.record_id:
            print(render(t))
            return
    sys.exit(f"{args.record_id} not in triage")


def record_decision(record_id: str, action: str, note: str = "", edits: dict[int, str] | None = None,
                    triage: list[dict] | None = None, path: Path = DECISIONS) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    entry = next((t for t in (triage or load_triage()) if t["record_id"] == record_id), None)
    if entry is None:
        raise ValueError(f"{record_id} not in triage")
    if action == "accept" and not entry.get("proposed_messages"):
        raise ValueError(f"{record_id} has no proposal to accept (classification {entry['classification']})")
    if action == "edit" and not edits:
        raise ValueError("edit needs at least one --reply N TEXT")
    decision = {
        "record_id": record_id,
        "action": action,
        "note": note,
        "edits": {str(k): v for k, v in (edits or {}).items()},
        "classification": entry["classification"],
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(decision, ensure_ascii=False) + "\n")
    return decision


def cmd_decide(args) -> None:
    edits = {int(n): text for n, text in (args.reply or [])}
    d = record_decision(args.record_id, args.action, args.note or "", edits)
    print(f"recorded: {d['record_id']} -> {d['action']} ({DECISIONS.relative_to(PROJECT_ROOT)})")


def cmd_sheet(args) -> None:
    q = _queue(args)[: args.limit]
    lines = [
        "# V0.2 repair review sheet",
        "",
        "Generated by `scripts/v02_repair_review.py sheet` — undecided REPAIR / HUMAN_REVIEW records, "
        "Banglish → mixed → Bengali → English. Proposals are mechanical (filler removal + script-mix "
        "transliteration); they do NOT fix meaning. Record decisions with `decide`; nothing here is approved.",
        "",
    ]
    for t in q:
        lines += ["```", render(t), "```", ""]
        orig = original_messages(t["record_id"])
        prop = t.get("proposed_messages") or orig
        for i in assistant_turns(orig):
            if prop[i]["content"] != orig[i]["content"]:
                diff = difflib.ndiff(orig[i]["content"].split(), prop[i]["content"].split())
                removed = [w[2:] for w in diff if w.startswith("- ")]
                lines.append(f"- msg {i}: removed/changed `{' '.join(removed)}`")
        lines.append("")
    SHEET.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {len(q)} record(s) to {SHEET.relative_to(PROJECT_ROOT)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("summary").set_defaults(fn=cmd_summary)
    for name, fn in (("next", cmd_next), ("sheet", cmd_sheet)):
        sp = sub.add_parser(name)
        sp.add_argument("--language", choices=list(LANG_PRIORITY))
        sp.add_argument("--class", dest="klass", choices=list(CLASS_PRIORITY))
        sp.add_argument("--source", choices=["imported", "synthetic_curated", "human_authored"])
        if name == "sheet":
            sp.add_argument("--limit", type=int, default=60)
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("show")
    sp.add_argument("record_id")
    sp.set_defaults(fn=cmd_show)
    sp = sub.add_parser("decide")
    sp.add_argument("record_id")
    sp.add_argument("action", choices=ACTIONS)
    sp.add_argument("--note")
    sp.add_argument("--reply", nargs=2, action="append", metavar=("N", "TEXT"), help="edit: new text for assistant reply N (1-based)")
    sp.set_defaults(fn=cmd_decide)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
