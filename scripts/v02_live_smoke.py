#!/usr/bin/env python3
"""Live smoke test of a RUNNING Rupsaa app (V0.2): API + web proxy + owner tools.

    bash scripts/start_rupsaa_v02.sh &            # in another shell
    python scripts/v02_live_smoke.py [--web http://127.0.0.1:5500] [--out <json>]

Goes through the web server's /api proxy (what the browser uses) and checks:
/health, /model/info (V0.2 adapter, 4-bit, prompt v0.2), real chats, same-
conversation memory, terminology routing through the real router + store,
casual turns without RAG, no .metadata.json sources, owner terminology
create/edit/search/lookup/delete being live without a restart, CSV/XLSX
import preview + commit, /conversation/reset, and the static pages.
A temporary test term is created and always deleted again.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402

TEST_TERM = "Moonfold"  # invented; not in the dataset or the terminology store


def call(base: str, method: str, path: str, body=None, raw: bytes | None = None, ctype: str | None = None,
         timeout: int = 600):
    data, headers = None, {}
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    elif raw is not None:
        data, headers["Content-Type"] = raw, ctype
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            status = r.status
            kind = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        payload, status, kind = e.read(), e.code, e.headers.get("Content-Type", "")
    return status, (json.loads(payload) if "json" in kind and payload else payload)


def multipart(field: str, filename: str, content: bytes, extra: dict | None = None) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in (extra or {}).items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
              f"Content-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default="http://127.0.0.1:5500")
    ap.add_argument("--out", type=Path, default=PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_posttraining/live_smoke.json")
    args = ap.parse_args()
    api = args.web + "/api"
    checks, chats, quality = [], [], []  # quality = model-wording observations, not plumbing checks

    def check(name, ok, detail=""):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)

    def chat(msg, cid=None, use_rag=True):
        t = time.time()
        s, r = call(api, "POST", "/chat", {"message": msg, "conversation_id": cid, "use_rag": use_rag})
        r = r if isinstance(r, dict) else {"error": str(r)}
        chats.append({"user": msg, "status": s, "seconds": round(time.time() - t, 1), **r})
        print(f"  USER: {msg}\n  RUPSAA [{r.get('route')} {r.get('terms_used')} rag={r.get('rag_used')}]: {r.get('response')}", flush=True)
        return s, r

    for _ in range(120):
        try:
            if call(api, "GET", "/health", timeout=5)[0] == 200:
                break
        except Exception:
            pass
        time.sleep(2)
    s, h = call(api, "GET", "/health")
    check("GET /health", s == 200 and h.get("status") == "ok", h)

    s, info0 = call(api, "GET", "/model/info")
    check("GET /model/info before load: configured V0.2 adapter + prompt v0.2",
          s == 200 and info0.get("configured_adapter_exists") and info0["configured_adapter_path"].endswith("rupsaa-v0.2")
          and info0.get("prompt_version") == "v0.2", info0)

    s, r = chat("hi, tumi kemon acho?")
    cid = r.get("conversation_id")
    check("casual greeting: 200, casual route, no RAG sources", s == 200 and r.get("route") == "casual"
          and not r.get("rag_used") and not r.get("sources"), r.get("route"))

    s, info = call(api, "GET", "/model/info")
    check("GET /model/info after load", s == 200 and info.get("adapter_loaded") is True and info.get("quantized") is True
          and str(info.get("adapter_path", "")).endswith("rupsaa-v0.2") and info.get("prompt_version") == "v0.2"
          and info.get("base_model_id") == "Qwen/Qwen2.5-7B-Instruct" and "cuda" in str(info.get("device")), info)

    s, r = chat("achcha", cid)
    check("'achcha' casual, no RAG", s == 200 and r.get("route") == "casual" and not r.get("sources"), r.get("route"))

    s, r = chat("amar favourite color blue", cid)
    s, r = chat("ami ki color bolechilam?", cid)
    check("same-conversation memory: memory route, no RAG, answer mentions blue",
          r.get("route") == "memory" and not r.get("rag_used") and "blue" in r.get("response", "").lower(), r.get("response"))

    s, r = chat("Strip mane ki?", cid)
    check("terminology route retrieves term-strip_stripping, no documents",
          r.get("route") == "terminology" and "term-strip_stripping" in r.get("terms_used", []) and not r.get("sources"), r.get("terms_used"))
    s, r = chat("strip ta ektu simple kore bojhao", cid)
    check("follow-up keeps the Strip entry", r.get("route") == "followup" and "term-strip_stripping" in r.get("terms_used", []), r.get("terms_used"))
    s, r = chat("এটা বাংলায় বুঝিয়ে বলো", cid)
    check("Bengali follow-up keeps the Strip entry", r.get("route") == "followup" and "term-strip_stripping" in r.get("terms_used", []), r.get("terms_used"))
    s, r = chat("ami age ki bolechilam?", cid)
    check("'ami age ki bolechilam?' memory route, no RAG", r.get("route") == "memory" and not r.get("rag_used"), r.get("response"))

    s, r = chat("Forplay ki?")
    check("typo 'Forplay' retrieves term-foreplay", "term-foreplay" in r.get("terms_used", []), r.get("terms_used"))

    s, r = chat("What is this platform's exact refund policy?")
    srcs = [x["source_filename"] for x in r.get("sources", [])]
    check("knowledge question: no .metadata.json source", s == 200 and not any(x.endswith(".metadata.json") for x in srcs), srcs)

    # --- owner terminology edits are live (no restart / reindex) ---
    tid = None
    try:
        s, t = call(api, "POST", "/owner/terminology", {"term": TEST_TERM, "definition": "A made-up smoke-test word meaning a folded paper moon.",
                                                         "category": "general", "aliases": ["moon fold"]})
        tid = t.get("id") if isinstance(t, dict) else None
        check("owner create term", s == 200 and tid, tid)
        s, r = chat(f"{TEST_TERM} mane ki?")
        check("new term used by chat immediately", tid in r.get("terms_used", []), r.get("terms_used"))
        s, t = call(api, "PUT", f"/owner/terminology/{tid}", {"term": TEST_TERM, "definition": "Edited: a smoke-test word for a sleepy cat pose.",
                                                              "category": "general", "aliases": ["moon fold"]})
        check("owner edit term", s == 200 and "Edited" in t.get("definition", ""), s)
        s, lst = call(api, "GET", f"/owner/terminology?q={TEST_TERM}")
        check("owner search finds the edited term", s == 200 and any(x["id"] == tid and "Edited" in x["definition"] for x in lst.get("terms", [])), s)
        s, lk = call(api, "GET", f"/owner/terminology/lookup?message={urllib.request.quote('moon fold mane ki?')}")
        check("owner test/lookup tool matches alias", s == 200 and any(m["id"] == tid for m in lk.get("matches", [])), lk)
        s, r = chat(f"{TEST_TERM} mane ki?")
        check("edited term still retrieved by chat without restart", tid in r.get("terms_used", []), r.get("terms_used"))
        quality.append({"observation": "reply paraphrases the EDITED definition (sleepy cat)",
                        "met": "cat" in r.get("response", "").lower(), "reply": r.get("response")})
    finally:
        if tid:
            s, _ = call(api, "DELETE", f"/owner/terminology/{tid}?confirm=true")
            check("owner delete test term", s == 200, s)

    # --- CSV / XLSX import (preview + commit + cleanup) ---
    s, tpl = call(api, "GET", "/owner/terminology/template.csv")
    check("CSV template download", s == 200 and b"term" in tpl, s)
    s, xl = call(api, "GET", "/owner/terminology/template.xlsx")
    check("XLSX template download", s == 200 and xl[:2] == b"PK", s)
    csv_body = ("term,definition,category,language\r\nSmokeimport Testword,Temporary smoke-test import row.,general,en\r\n").encode()
    raw, ctype = multipart("file", "smoke.csv", csv_body)
    s, pv = call(api, "POST", "/owner/terminology/import/preview", raw=raw, ctype=ctype)
    check("CSV import preview", s == 200, json.dumps(pv)[:200] if isinstance(pv, dict) else pv)
    raw, ctype = multipart("file", "smoke.csv", csv_body)
    s, cm = call(api, "POST", "/owner/terminology/import", raw=raw, ctype=ctype)
    check("CSV import commit", s == 200, json.dumps(cm)[:200] if isinstance(cm, dict) else cm)
    s, lst = call(api, "GET", "/owner/terminology?q=Smokeimport")
    for x in (lst.get("terms", []) if isinstance(lst, dict) else []):
        call(api, "DELETE", f"/owner/terminology/{x['id']}?confirm=true")
    raw, ctype = multipart("file", "template.xlsx", xl)
    s, pv = call(api, "POST", "/owner/terminology/import/preview", raw=raw, ctype=ctype)
    check("XLSX import preview (template)", s == 200, json.dumps(pv)[:200] if isinstance(pv, dict) else pv)

    # --- reset ---
    s, rs = call(api, "POST", "/conversation/reset", {"conversation_id": cid})
    check("POST /conversation/reset", s == 200 and rs.get("reset") is True, rs)
    s, r = chat("ami ki color bolechilam?", cid)
    check("after reset, memory has no blue", r.get("route") == "memory" and "blue" not in r.get("response", "").lower(), r.get("response"))

    # --- static pages through the web server ---
    for page in ("/", "/index.html", "/teach.html", "/knowledge.html", "/app.js", "/terminology.js", "/knowledge.js", "/teach.js", "/config.js"):
        s, body = call(args.web, "GET", page)
        check(f"web {page}", s == 200 and len(body) > 100, s)
    s, tax = call(api, "GET", "/owner/teach/taxonomy")
    check("teach taxonomy API", s == 200, s)
    s, docs = call(api, "GET", "/owner/knowledge/documents")
    check("knowledge documents API (no .metadata.json listed)", s == 200 and not any(
        str(d.get("filename", "")).endswith(".metadata.json") for d in (docs.get("documents", []) if isinstance(docs, dict) else [])), s)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    passed = sum(c["pass"] for c in checks)
    args.out.write_text(json.dumps({"passed": passed, "total": len(checks), "checks": checks,
                                    "quality_observations": quality, "chats": chats},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(checks)} checks passed -> {args.out}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
