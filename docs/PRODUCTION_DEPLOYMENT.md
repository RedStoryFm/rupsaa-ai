# Rupsaa — production deployment

The shortest safe path from an **owner-approved adapter** to a **live Rupsaa**. Nothing here promotes
an adapter automatically; owner approval is required at step 3.

## 1. What actually runs (current architecture)

```
Browser (web/index.html · app.js · owner pages teach.html / knowledge.html)
   │  relative "api/*" calls (web/config.js) — works behind any prefix / domain
   ▼
web/dev_server.py  :WEB_PORT (5500)   static files + reverse proxy /api/* → API (adds X-Forwarded-For)
   ▼
FastAPI api/main.py  127.0.0.1:API_PORT (8000)
   │  middleware: body-size limit · CORS · rate limit on /chat · owner key on /owner/* and /rag/reindex
   ▼
api/services.py  RupsaaService.chat
   ├─ essential boundary check (rupsaa/guardrails) — refuses before the model is called
   ├─ conversation history  rupsaa/conversation/manager.py (in-memory, server-issued ids, bounded)
   ├─ router  rupsaa/rag/router.py → memory | followup | terminology | knowledge | casual | general
   ├─ language control  rupsaa/conversation/language_control.py ("banglay bolo" → directive)
   ├─ terminology  knowledge/terminology/*.json   (rupsaa/rag/terminology.py)
   ├─ dance knowledge  knowledge/dance/*.json      (rupsaa/rag/dance.py, 60 owner records)
   ├─ documents RAG  knowledge/documents + FAISS index knowledge/index (strict relevance)
   ├─ system prompt  rupsaa/personality/system_prompt.py (V02_SYSTEM_PROMPT + reference blocks)
   └─ model  rupsaa/model/inference.py → Qwen2.5-7B-Instruct 4-bit NF4 + LoRA adapter (PEFT, not merged)
         one generation at a time (GPU lock), run off the event loop
```

Launch pieces: `scripts/start_rupsaa_production.sh` (validate → start), `scripts/stop_rupsaa_production.sh`,
`scripts/check_production_config.py`, `scripts/production_smoke.py`, `scripts/backup_knowledge.sh` /
`restore_knowledge.sh`.

### Status

| | component |
|---|---|
| **READY** | chat pipeline, router, language control, terminology + dance retrieval (60/60), owner CRUD/import with preview, health/readiness, model switching by env var, fail-closed production config, owner-key auth (constant-time), rate limiting, request/upload limits, path-traversal protection, server-issued conversation ids, error responses without tracebacks, smoke test, backup/restore |
| **NEEDS PRODUCTION CONFIG** | `.env`: `RUPSAA_ENV=production`, `OWNER_API_KEY`, `RUPSAA_ADAPTER_PATH` (+ `RUPSAA_ADAPTER_SHA256`), `CORS_ORIGINS` = your domain |
| **BLOCKING PUBLIC LAUNCH** | (1) an owner-approved adapter (V0.2.1 after evaluation); (2) always-on hosting + HTTPS for a custom domain (see §6) |
| **OPTIONAL POST-LAUNCH** | durable conversation storage (Redis/Postgres), serving static files from the reverse proxy instead of `dev_server.py`, multi-GPU/queue scaling, streaming replies, uptime monitoring/alerts, per-user accounts |

## 2. Configuration (`.env`, never committed)

Start from `.env.example`. Production minimum:

```
RUPSAA_ENV=production
RUPSAA_MODEL_PATH=Qwen/Qwen2.5-7B-Instruct
RUPSAA_ADAPTER_PATH=adapters/rupsaa-v0.2.1          # the approved adapter
RUPSAA_ADAPTER_SHA256=<sha256 of adapter_model.safetensors from the evaluation report>
OWNER_API_KEY=<python -c "import secrets; print(secrets.token_urlsafe(32))">
CORS_ORIGINS=https://your-domain.example
LOG_LEVEL=INFO
```

`RUPSAA_ENV=production` changes behaviour: the server **refuses to start** without a ≥24-character owner
key, an existing adapter, or with `CORS_ORIGINS=*`; the model preloads at startup (`/ready` = 503 until
loaded, `/chat` answers 503 "starting up" meanwhile); chat is rate-limited (20/min per client, 120/min
total — `RUPSAA_RATE_LIMIT_PER_MINUTE`, `RUPSAA_RATE_LIMIT_GLOBAL_PER_MINUTE`, `0` = off); `/model/info`
shows adapter **names** only; owner tools answer 503 if the key is missing (fail closed). The launcher
binds the API to 127.0.0.1 so only the web port is public. Development (default) keeps the old
behaviour: lazy load, no limits, owner tools open with a warning when no key is set.

## 3. Fresh / restarted server → live (exact sequence)

```bash
cd /teamspace/studios/this_studio/rupsaa-ai            # or your server's checkout
git pull --ff-only                                     # code only; never `git checkout .`/`reset --hard` (see §8)
bash setup_rupsaa.sh                                   # first time on a new machine only
# approved adapter present? (never promote without the owner's explicit approval)
ls adapters/rupsaa-v0.2.1/adapter_model.safetensors
sha256sum adapters/rupsaa-v0.2.1/adapter_model.safetensors   # must equal the evaluation report
nano .env                                              # §2 values; RUPSAA_ADAPTER_PATH + RUPSAA_ADAPTER_SHA256
bash scripts/start_rupsaa_production.sh --check        # all checks must pass (GPU free, ports free, key, adapter)
bash scripts/start_rupsaa_production.sh                # foreground; or run inside tmux / systemd (§6)
# second terminal:
until curl -sf localhost:5500/api/ready; do sleep 10; done     # model loaded (≈1–2 min)
OWNER_API_KEY=... python scripts/production_smoke.py --base http://127.0.0.1:5500/api \
    --expect-adapter rupsaa-v0.2.1 --expect-prompt v0.2 --out smoke.json
# SMOKE TEST PASSED → open the public URL, send one message yourself → live
```

Never start the app while a training job is using the GPU: the check refuses when less than 9 GB is free
(a 7B 4-bit model plus generation needs ~6–8 GB; loading it next to training can crash both).

## 4. Adapter promotion and rollback

**Promotion:** candidate adapter → evaluation report (loss, generation review, smoke/live checks) →
**owner approval** → set `RUPSAA_ADAPTER_PATH` + `RUPSAA_ADAPTER_SHA256` in `.env` → `stop` → `start`
→ `/ready` → `production_smoke.py --expect-adapter <name>` → live. Future versions (v0.3, …) are the
same two lines; no code changes. The prompt version is inferred from the adapter name (`rupsaa-v0.2*`
→ v0.2) or pinned with `RUPSAA_PROMPT_VERSION`.

**Rollback:** new adapter misbehaves → put the previous known-good values back in `.env`
(e.g. `RUPSAA_ADAPTER_PATH=adapters/rupsaa-v0.2`, its SHA) → `bash scripts/stop_rupsaa_production.sh`
→ `bash scripts/start_rupsaa_production.sh` → `/ready` → smoke test. Keep every released adapter
directory; never delete the previous one until the new one has been live and stable. Adapters are also
published under `release/` + Hugging Face (`scripts/fetch_adapter.py` restores them).

The server never silently substitutes another adapter: a missing/unattached adapter or a hash
mismatch stops startup with an error.

## 5. Security summary

- **Owner endpoints:** every write and data read under `/owner/*` plus `/rag/reindex` requires
  `X-Owner-Key` (constant-time compare); only static metadata/templates are public. In production an
  unset key disables them (503). The key is typed into the owner pages by the owner (kept for the tab
  session only) — it is never part of any served file.
- **Public API:** chat message ≤ 8,000 chars (frontend `maxlength` too); request body ≤ 64 KB
  (uploads ≤ 2 MB, their own validation: type, rows, cell length, formulas as text); `max_new_tokens`
  capped (1024); malformed JSON → 422; unexpected errors → generic 500 (stack traces only in the logs);
  CORS restricted to `CORS_ORIGINS` and headers `Content-Type`, `X-Owner-Key`.
- **Rate limiting:** in-process sliding window per client (real IP via the local proxy's
  `X-Forwarded-For`, trusted only from loopback) + a global cap as a backstop. One process = one limiter;
  if you ever run several API processes, put the limit in the reverse proxy instead.
- **Path traversal:** term/dance ids are regex-validated; document filenames must resolve inside
  `knowledge/documents`; restore only extracts the knowledge directories.

## 6. Hosting, domain and HTTPS

**Lightning Studio (current)** is an interactive development machine: it can sleep/stop, its public URL
is a Lightning port-forwarding link, and GPU time is billed while it runs. It is fine for a **soft
launch** (keep the Studio running, share the forwarded URL of port 5500), but it is not a permanent public
host: there is no custom-domain TLS termination under your control. (Check Lightning's current docs for
any managed-deployment / custom-domain feature before migrating; that could remove the step below.)

**Recommended minimum for a custom domain** — one GPU VM (NVIDIA L4 / A10G, ≥ 24 GB, Ubuntu) running
this same repository, nothing else changes:

```
DNS  rupsaa.example.com  A → VM public IP
VM   Caddy :443 (automatic Let's Encrypt HTTPS)  →  127.0.0.1:5500  web/dev_server.py (static + /api proxy)
                                                  →  127.0.0.1:8000  FastAPI + model (same process, GPU)
     firewall: allow 80/443 only (5500 and 8000 are never public)
```

`/etc/caddy/Caddyfile`:
```
rupsaa.example.com {
    encode gzip
    reverse_proxy 127.0.0.1:5500 {
        transport http { read_timeout 300s }
    }
}
```

Run the app as a service (`systemd`, `Restart=on-failure`, `ExecStart=/path/to/rupsaa-ai/scripts/start_rupsaa_production.sh`,
`ExecStop=.../stop_rupsaa_production.sh`, `User=` a non-root user). Set `CORS_ORIGINS=https://rupsaa.example.com`.
Migration = clone the repo, `setup_rupsaa.sh` (downloads the adapter from Hugging Face), copy `.env`, restore
the latest knowledge backup (§7), start. Buying the domain and creating the DNS record are owner actions.

## 7. Data: what persists

| data | where | survives restart | backup |
|---|---|---|---|
| terminology (owner edits) | `knowledge/terminology/*.json` | yes (files, live reads) | `scripts/backup_knowledge.sh` |
| dance knowledge (60 + edits) | `knowledge/dance/*.json` | yes | same |
| documents | `knowledge/documents/` (+ rebuildable index `knowledge/index/`) | yes | same (index: `scripts/ingest_knowledge.py`) |
| Teach Rupsaa examples | `data/production/drafts/` | yes | same |
| **conversations** | **process memory** | **no — a restart clears all chats** | none (by design for launch) |

Backups: `bash scripts/backup_knowledge.sh` → `backups/rupsaa-knowledge-<UTC>.tar.gz` (+ `.sha256`); copy
it off the server. Restore: `bash scripts/restore_knowledge.sh <archive> --yes` (takes a safety backup first).
Take a backup before every deployment/update and daily while the owner is editing.

**Conversation memory:** session-scoped only. Ids are random UUIDs issued by the server (a client-chosen id
is never adopted, so users cannot collide or read each other's history); each conversation keeps its last
20 messages; at most 5,000 conversations, idle ones dropped after 6 h (`RUPSAA_MAX_CONVERSATIONS`,
`RUPSAA_CONVERSATION_IDLE_MINUTES`). There is **no durable long-term memory** — a restart or deploy starts
everyone fresh. Durable storage is a post-launch item (`ConversationStore` interface is ready for it).

## 8. Operations

- Logs: startup (env, adapter, prompt version, limits), model load time, one line per chat
  (`route`, languages, term/doc counts, input length, output tokens, latency) — **no message text**.
  Full per-turn traces including user text only with `RUPSAA_TRACE_FILE` (debugging; never in production).
  Owner key and tokens are never logged.
- Health: `GET /api/health` (process + model + knowledge counts + index present, always 200),
  `GET /api/ready` (200 only when the model can answer — use this before sending traffic),
  `GET /api/model/info` (base model, adapter name, prompt version, loaded status, device).
- Updating code: `git pull --ff-only` only. Owner edits live in tracked directories (`knowledge/…`,
  `data/production/drafts`); `git checkout .`, `git reset --hard` or `git clean` would discard them —
  back up first, and commit owner knowledge periodically if you want it versioned.
