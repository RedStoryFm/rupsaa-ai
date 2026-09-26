# Rupsaa release checklist

## MUST HAVE before public launch

1. [ ] **Owner-approved adapter.** V0.2.1 evaluated (post-training report + owner live chat) and explicitly
   approved; its `adapter_model.safetensors` SHA-256 recorded.
2. [ ] **`.env` production values:** `RUPSAA_ENV=production`, `RUPSAA_ADAPTER_PATH`, `RUPSAA_ADAPTER_SHA256`,
   a fresh random `OWNER_API_KEY` (≥ 24 chars), `CORS_ORIGINS` = the public origin. Not committed.
3. [ ] **Config check passes:** `bash scripts/start_rupsaa_production.sh --check` (no training on the GPU).
4. [ ] **Start + ready:** production launcher running; `curl -sf <host>/api/ready` returns 200.
5. [ ] **Smoke test passes:** `OWNER_API_KEY=… python scripts/production_smoke.py --base <host>/api
   --expect-adapter <name> --expect-prompt v0.2`.
6. [ ] **Knowledge backup taken** (`bash scripts/backup_knowledge.sh`) and copied off the server.
7. [ ] **Always-on host decided:** Studio kept running (soft launch, Lightning URL) — or GPU VM + Caddy
   HTTPS for a custom domain (docs/PRODUCTION_DEPLOYMENT.md §6).
8. [ ] **Rollback target known:** previous adapter directory + SHA written down (currently `adapters/rupsaa-v0.2`,
   `c7ca6184…a410559`).

## CAN DO after launch

- Custom domain + HTTPS (if the soft launch runs on the Lightning URL first)
- Durable conversation history (Redis/Postgres via `ConversationStore`); user accounts
- Serve static files from Caddy instead of `web/dev_server.py`; reply streaming
- Uptime monitoring / alerting on `/api/ready`; log shipping; daily automated knowledge backups
- Rate limits in the reverse proxy if more than one API process is ever run
- Owner-page UX (key entry once per session is intentional for now)
- Native-speaker review of the 21 Bengali-script name spellings added for dance retrieval

## Every release (adapter change)

candidate → evaluation → **owner approval** → set adapter + SHA in `.env` → stop → start → `/ready` →
smoke test → live. Rollback = previous adapter + SHA → stop → start → `/ready` → smoke test.
Never promote automatically; never delete the previous adapter until the new one is stable.
