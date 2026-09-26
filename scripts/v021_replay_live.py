#!/usr/bin/env python3
"""Replay the owner's live V0.2 test conversation through the REAL running app.

    python scripts/v021_replay_live.py --label before --runs 3
    python scripts/v021_replay_live.py --label after --runs 3

Each run is one fresh conversation through the web proxy (/api/chat, RAG
toggle on like the UI), turn by turn, exactly as the owner typed it. Writes
data/production/reports/rupsaa_v0.2.1_preparation/live_replay_<label>.json.
Sampling is not seeded by the API, so several runs are recorded.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402

OUT_DIR = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation"

OWNER_SEQUENCE = [
    "hi, tumi kemon acho?",
    "ajke amar mood ta bhalo na",
    "achcha",
    "tumi amar sathe banglish e kotha bolbe?",
    "Strip mane ki?",
    "strip ta ektu simple kore bojhao",
    "Forplay ki?",
    "এটা বাংলায় বুঝিয়ে বলো",
    "amar favourite color blue",
    "ami ki color bolechilam?",
    "ami age ki bolechilam?",
]

# The owner's exact live outputs (V0.2 app, before the runtime fixes).
OWNER_LIVE_OUTPUTS = [
    "Bhalo achi tumi ki bhabcho?",
    "Ki dekhle shune tumi niye sobcheye beshi mood down hoye jai?",
    "Just express korar dorkar nai, tai bolte pari - ekta somoy kokhono shobcheye beshi mood down hoyeo hoye jai।",
    "Sheta niye concern na kore amar sathe, tumi amake comfortable feel koro. Kotha bolte chao?",
    "Simple term - strip mane kichu niye kichu remove kora, typically bishoyer jonno. Tumi shunte chai ki emon kichu?",
    "Strip mane gradually ar often seductive diye kichu niye kichu remove kora - eta othak kori je tomar situation er upor "
    "depend kore. Eta always performative na, sometimes just a normal thing, sheta difference thakte pare context er upor।",
    "Foreplay mane kichu sex e bishoy der jonno kichu make karar effort - physical onno der jonno, emotional intimacy, nijer "
    "mood er modhhe ekta build-up create kora. Shobar onno der jonno o shomoy, eta manush er bhoy gulo reduce kore dujon e "
    "mone hote pare।",
    "Foreplay mane kichu sex e bishoy der jonno kichu physical ar emotional activity - body part der jonno remove kora, nijer "
    "mood er modhhe relax kora, jate onno der interest upor rakho, ei ekta build-up create kora. Tumi keno ask korcho, "
    "interest ache ki?",
    "Blue ekta very grounding color, calm feeling ashar - shudhu ekta fun fact!",
    "Blue - tumi emon kichu onek baar bolche, ekdom forget korechilo।",
    "Sorry, ami memory er sathe completely full. Ki bolechile?",
]


def post(api: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(api + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default="http://127.0.0.1:5500")
    ap.add_argument("--label", required=True)
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    api = args.web + "/api"
    runs = []
    for n in range(args.runs):
        cid, turns = None, []
        for msg in OWNER_SEQUENCE:
            r = post(api, "/chat", {"message": msg, "conversation_id": cid, "use_rag": True})
            cid = r["conversation_id"]
            turns.append({"user": msg, "reply": r["response"], "route": r.get("route"), "terms_used": r.get("terms_used"),
                          "rag_used": r.get("rag_used"), "sources": [s["source_filename"] for s in r.get("sources", [])],
                          "response_language": r.get("response_language")})
            print(f"[{args.label} {n + 1}] {msg}\n    -> [{r.get('route')} {r.get('terms_used')} lang={r.get('response_language')}] "
                  f"{r['response']}", flush=True)
        post(api, "/conversation/reset", {"conversation_id": cid})
        runs.append({"conversation_id": cid, "turns": turns})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"live_replay_{args.label}.json"
    out.write_text(json.dumps({"label": args.label, "created_at": datetime.now(timezone.utc).isoformat(),
                               "sequence": OWNER_SEQUENCE, "owner_live_outputs": OWNER_LIVE_OUTPUTS, "runs": runs},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
