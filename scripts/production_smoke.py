#!/usr/bin/env python3
"""Production smoke test for a RUNNING Rupsaa instance (run after the approved adapter is loaded).

    OWNER_API_KEY=... python scripts/production_smoke.py --base http://127.0.0.1:5500/api \\
        --expect-adapter rupsaa-v0.2.1 [--expect-prompt v0.2] [--wait 600] [--out report.json]

Non-destructive: only reads owner data (never creates/edits/deletes). Hard checks decide the exit
code; model-wording checks (right script, remembered fact) are reported as warnings unless --strict.

Checks: /health, /ready (waits for the model), /model/info (adapter/prompt, no server paths in
production), English / Banglish / Bengali chat, same-conversation memory, terminology retrieval,
dance retrieval, owner endpoints rejected without the key (and /rag/reindex), one authorized
read-only owner call, conversation reset.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BN = re.compile(r"[ঀ-৿]")


class HttpClient:
    """Tiny JSON client; tests pass a FastAPI TestClient-backed object with the same .call()."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body=None, headers=None, timeout: int = 300):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        try:
            return status, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return status, {"raw": raw[:200].decode(errors="replace")}


def run(client, owner_key: str | None, expect_adapter: str | None, expect_prompt: str | None,
        wait_seconds: int = 0, strict: bool = False) -> dict:
    hard, soft = [], []

    def check(name, ok, detail="", quality=False):
        (soft if quality else hard).append({"check": name, "pass": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else ('WARN' if quality else 'FAIL')}] {name}: {detail}", flush=True)
        return ok

    def chat(msg, cid=None):
        s, r = client.call("POST", "/chat", {"message": msg, "conversation_id": cid})
        return s, (r if isinstance(r, dict) else {})

    s, h = client.call("GET", "/health")
    check("health", s == 200 and h.get("status") == "ok",
          {k: h.get(k) for k in ("ready", "model_loaded", "terminology_entries", "dance_entries", "environment")})
    deadline = time.monotonic() + wait_seconds
    while True:
        s, rd = client.call("GET", "/ready")
        if s == 200 or time.monotonic() >= deadline:
            break
        time.sleep(5)
    check("ready (model loaded)", s == 200, rd)

    s, info = client.call("GET", "/model/info")
    check("model/info: adapter loaded + quantized", s == 200 and info.get("adapter_loaded") is True and info.get("quantized") is True,
          {k: info.get(k) for k in ("base_model_id", "adapter_name", "prompt_version", "device", "environment")})
    if expect_adapter:
        check("model/info: expected adapter", info.get("adapter_name") == expect_adapter, info.get("adapter_name"))
    if expect_prompt:
        check("model/info: expected prompt version", info.get("prompt_version") == expect_prompt, info.get("prompt_version"))
    if info.get("environment") == "production":
        leaked = [k for k in ("adapter_path", "configured_adapter_path") if str(info.get(k) or "").startswith("/")]
        check("model/info: no server paths exposed", not leaked, leaked)

    s, r = chat("Hi Rupsaa! How is your day going?")
    check("chat: English", s == 200 and bool(r.get("response")), (r.get("response") or r)[:120] if isinstance(r.get("response"), str) else r)
    check("chat: English reply in Latin script", not BN.search(r.get("response", "")), "", quality=True)
    s, r = chat("ajke ki korle bhalo lagbe bolo to?")
    check("chat: Banglish", s == 200 and bool(r.get("response")), (r.get("response") or "")[:120])
    check("chat: Banglish reply in Latin script", not BN.search(r.get("response", "")), "", quality=True)
    s, r = chat("আজ তোমার দিন কেমন কাটছে?")
    check("chat: Bengali", s == 200 and bool(r.get("response")), (r.get("response") or "")[:120])
    check("chat: Bengali reply in Bengali script", bool(BN.search(r.get("response", ""))), "", quality=True)

    s, r1 = chat("amar priyo phool holo shiuli")
    cid = r1.get("conversation_id")
    s, r2 = chat("ami kon phool er kotha bolechilam?", cid)
    check("memory: same conversation + memory route", s == 200 and r2.get("conversation_id") == cid and r2.get("route") == "memory",
          {"route": r2.get("route")})
    check("memory: reply recalls the fact", "shiuli" in (r2.get("response") or "").lower(), (r2.get("response") or "")[:120], quality=True)

    s, r = chat("Strip mane ki?")
    check("terminology retrieval", s == 200 and "term-strip_stripping" in (r.get("terms_used") or []), r.get("terms_used"))
    s, r = chat("Kathak kothakar dance?")
    check("dance retrieval", s == 200 and "dance-kathak" in (r.get("terms_used") or []), r.get("terms_used"))

    s, _ = client.call("GET", "/owner/terminology")
    check("owner: list rejected without key", s in (401, 503), s)
    s, _ = client.call("GET", "/owner/dance?q=kathak")
    check("owner: dance list rejected without key", s in (401, 503), s)
    s, _ = client.call("POST", "/rag/reindex")
    check("owner: /rag/reindex rejected without key", s in (401, 503), s)
    if owner_key:
        s, d = client.call("GET", "/owner/dance?q=kathak", headers={"X-Owner-Key": owner_key})
        check("owner: authorized read-only call", s == 200 and d.get("count", 0) >= 1, {"status": s, "count": d.get("count")})
    else:
        check("owner: authorized read-only call", False, "OWNER_API_KEY not provided to the smoke test")

    s, rs = client.call("POST", "/conversation/reset", {"conversation_id": cid})
    s2, r3 = chat("ami kon phool er kotha bolechilam?", cid)
    check("conversation reset", s == 200 and rs.get("reset") is True and r3.get("conversation_id") != cid,
          {"old": cid, "new": r3.get("conversation_id")})

    hard_ok = all(c["pass"] for c in hard)
    soft_ok = all(c["pass"] for c in soft)
    return {"pass": hard_ok and (soft_ok or not strict), "hard_pass": hard_ok, "quality_pass": soft_ok,
            "checks": hard, "quality_checks": soft}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5500/api")
    ap.add_argument("--expect-adapter")
    ap.add_argument("--expect-prompt")
    ap.add_argument("--wait", type=int, default=600, help="seconds to wait for /ready")
    ap.add_argument("--strict", action="store_true", help="model-wording checks also fail the run")
    ap.add_argument("--out")
    args = ap.parse_args()
    report = run(HttpClient(args.base), os.getenv("OWNER_API_KEY"), args.expect_adapter, args.expect_prompt,
                 args.wait, args.strict)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    print("SMOKE TEST PASSED" if report["pass"] else "SMOKE TEST FAILED")
    sys.exit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
