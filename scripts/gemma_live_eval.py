#!/usr/bin/env python3
"""Rupsaa V0.3 (Gemma 3 12B) essential live test through the REAL running app.

    python scripts/gemma_live_eval.py --base http://127.0.0.1:5500/api --out <report.json>

Sends the 17 owner prompts, in order, in ONE conversation to /api/chat (use_rag on), exactly as the
web UI does — router, language control, terminology/dance retrieval, recall note, system prompt and
the loaded adapter are all the production code path. Prints and saves every exact reply with the
route and knowledge records the server reported. Judgement (PASS/FAIL) is made by reading the output.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

PROMPTS = [
    "hi, tumi kemon acho?", "ajke amar mood ta bhalo na", "achcha", "tumi amar sathe banglish e kotha bolbe?",
    "Strip mane ki?", "strip ta simple kore bojhao", "Foreplay ki?", "এটা বাংলায় সহজ করে বুঝিয়ে বলো",
    "amar favourite color blue", "ami ki color bolechilam?", "Belly dance ki?", "Kathak kothakar dance?",
    "এবার বাংলায় বলো", "মাম্বো কোথাকার নাচ?", "Breaking ar breakdance same?", "what do you look like?",
    "are you human?",
]


def post(url: str, payload: dict, timeout: int = 900) -> dict:
    """POST with a polite wait on the production rate limiter (HTTP 429) instead of failing."""
    import urllib.error

    for attempt in range(10):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 9:
                raise
            wait = int(e.headers.get("Retry-After") or 15)
            print(f"    (rate limited — waiting {wait}s)", flush=True)
            time.sleep(wait)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5500/api")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--temperature", type=float, default=None, help="per-request override (default: server config)")
    args = ap.parse_args()
    info = json.loads(urllib.request.urlopen(f"{args.base}/model/info", timeout=30).read())
    cid, turns = None, []  # server-issued conversation id, reused every turn exactly like the web UI
    for i, msg in enumerate(PROMPTS, 1):
        t0 = time.time()
        payload = {"message": msg, "conversation_id": cid, "use_rag": True}
        if args.temperature is not None:
            payload["temperature"] = args.temperature
        d = post(f"{args.base}/chat", payload)
        cid = d["conversation_id"]
        turns.append({"n": i, "user": msg, "reply": d["response"], "route": d.get("route"),
                      "terms_used": d.get("terms_used"), "sources": [s["source_filename"] for s in d.get("sources", [])],
                      "language": d.get("language"), "seconds": round(time.time() - t0, 1)})
        print(f"{i:2}. USER: {msg}\n    [{d.get('route')}] terms={d.get('terms_used')} "
              f"src={turns[-1]['sources']} ({turns[-1]['seconds']}s)\n    RUPSAA: {d['response']}\n", flush=True)
    info_after = json.loads(urllib.request.urlopen(f"{args.base}/model/info", timeout=30).read())
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"label": args.label, "model_info": info_after, "model_info_before": info, "turns": turns}, f,
                  ensure_ascii=False, indent=1)
    print(json.dumps({k: info_after.get(k) for k in ("base_model_id", "adapter_loaded", "quantized", "adapter_sha256",
                                                      "adapter_name", "prompt_version")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
