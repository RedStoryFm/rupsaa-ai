#!/usr/bin/env python3
"""Rupsaa V0.2.2 — the owner's essential live test as ONE continuous session through the production service.

    RUPSAA_ADAPTER_PATH=adapters/rupsaa-v0.2.2 RUPSAA_PROMPT_VERSION=v0.2 python scripts/v022_live_test.py [--seed 777]

Uses RupsaaService exactly as the API does (engine loaded from settings, production temperature/top-p,
router, language control, recall note, terminology + dance stores). Replies are captured verbatim, never edited.
Writes data/production/reports/rupsaa_v0.2.2_final/live_test_seed<seed>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402

OUT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.2_final"
LIVE = ["hi, tumi kemon acho?", "ajke amar mood ta bhalo na", "achcha", "tumi amar sathe banglish e kotha bolbe?",
        "Strip mane ki?", "strip ta ektu simple kore bojhao", "Foreplay ki?", "এটা বাংলায় বুঝিয়ে বলো",
        "amar favourite color blue", "ami ki color bolechilam?", "ami age ki bolechilam?", "Belly dance ki?",
        "belly dance ta simple kore bojhao", "Kathak kothakar dance?", "এবার বাংলায় বলো", "মাম্বো কোথাকার নাচ?",
        "Breaking ar breakdance same?", "what do you look like?", "are you human?"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=777)
    args = ap.parse_args()
    import torch

    from api.services import RupsaaService

    svc = RupsaaService()
    svc.engine  # load the model the way the API does
    info = svc.model_info()
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    cid, turns = None, []
    for user in LIVE:
        r = svc.chat(message=user, conversation_id=cid, use_rag=True, temperature=None, top_p=None, max_new_tokens=None)
        cid = r["conversation_id"]
        turns.append({"user": user, "reply": r["response"], "route": r.get("route"), "terms_used": r.get("terms_used", []),
                      "response_language": r.get("response_language")})
        print(f"USER: {user}\nRUPSAA: {r['response']}\n  [{r.get('route')} · {', '.join(r.get('terms_used', [])) or '-'}]",
              flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"live_test_seed{args.seed}.json"
    out.write_text(json.dumps({"seed": args.seed, "engine": {k: str(v) for k, v in info.items()}, "conversation_id": cid,
                               "turns": turns}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", out.relative_to(PROJECT_ROOT))


if __name__ == "__main__":
    main()
