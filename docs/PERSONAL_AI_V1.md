# Rupsaa Personal AI V1 — Knowledge, Memory, Internet, Teacher Mode

Everything here is an **application layer** around the frozen model (Gemma 3 12B IT + the
`rupsaa-v0.3-gemma3-final` adapter, temperature 0.55, serving notes on). There is no training, no
adapter change and no dataset change. Knowledge you add is live on the next chat message, with no restart.

## 1. How a message is answered

```
message
  → owner/teacher checks (secret submission, teacher session)            api/services.py
  → internet commands + pending web query (ASK / ALLOW / DENY)            rupsaa/conversation/internet_policy.py
  → route + curated knowledge (Terminology → Dance → General Knowledge)   rupsaa/rag/context_builder.py
  → relevant user memory (opt-in)                                         rupsaa/conversation/user_memory.py
  → enough / current?  no → internet, only as the user permits            rupsaa/rag/web_search.py
                                                                          rupsaa/rag/source_policy.py
  → Gemma answers in the user's language
```

Casual chat ("Hi Rupsaa", "Ajke amar mood kharap") uses no knowledge lookup and no web.

Each reply records which sources informed it in `source_types`:

| Source type | Meaning |
|---|---|
| `CONVERSATION` | Follow-up or recall from this chat. |
| `USER_MEMORY` | Opted-in facts about this user. |
| `CURATED_RAG` | Owner-approved knowledge (Terminology, Dance, General Knowledge, documents). |
| `WEB` | A permitted live search. |
| `MODEL_GENERAL_KNOWLEDGE` | Nothing curated and nothing from the web. |

Record IDs, match types and scores are logged server-side (`retrieval=` in the log) and are not sent to the
browser.

## 2. Curated knowledge

| Store | Folder | Use for |
|---|---|---|
| Terminology | `knowledge/terminology/` | Words and slang, with a precise definition. |
| Dance | `knowledge/dance/` | Dance forms, styles and terms. |
| General Knowledge | `knowledge/general/` | Any topic, organised by category. |
| Documents | `knowledge/documents/` (e5 + FAISS) | Long owner documents. |

All three record stores work the same way:
- one human-readable JSON file per record;
- validated, with atomic writes;
- IDs that can't escape the folder;
- title and alias duplicate protection;
- mtime-cached, so edits are live immediately.

Edits and deletes copy the previous version to `.history/`, which is git-ignored, and bump `revision`.

**General Knowledge categories:**
- Relationships, Dating
- Sexual Education, Adult Terminology
- Health & Hygiene, Beauty, Fashion, Fitness
- Entertainment, Creator Platforms, Social Media, Technology
- Indian Culture, Food / Recipes, Lifestyle, General Education
- Custom

**GK fields** (only `title` plus one of summary, description or key points is required):
- `id`, `title`, `category`, `subcategory`
- `aliases`
- `summary`, `description`, `key_points`, `steps`, `do`, `dont`, `answer_guidance`
- `languages`, `tags`, `enabled`
- `source`, `source_type`, `sources`, `verified`, `approved_by`
- `revision`, `created_at`, `updated_at`

`source_type` is one of:

| Value | Meaning |
|---|---|
| `owner` | Added by the owner. |
| `owner_teaching` | Taught in chat. |
| `owner_verified_web` | The owner reviewed web evidence and approved the record; the URLs are kept in `sources`. |
| `import` | Came from an import file. |
| `test` | Seed record. |

A live web result is never a source type on its own.

**Multilingual aliases.** One concept is one record. English, Banglish and Bengali names are aliases of that record,
for example `Foreplay` / `fore play` / `ফোরপ্লে`. Follow-ups such as "eta Bengali te bolo" and "abar Banglish e bolo"
keep the active record without searching again.

**Retrieval order:**
1. exact title or alias;
2. Terminology, then Dance;
3. a strong General Knowledge semantic match (multilingual-e5, score ≥ 0.85, and the question must contain most
   of the record's name words);
4. otherwise, no local match.

Weak look-alikes are rejected: "hair color" does not match *Hair Straightening*.

**Managing knowledge.** `/knowledge.html` has Terminology, Dance and General Knowledge tabs. Each supports add,
edit, delete, enable/disable, search, category and tag filters, a retrieval test, preview, and import/export in
JSON, CSV and XLSX. Imports are capped at 2 MB and 1000 rows. They are preview-first, and an existing title is
SKIPPED unless you choose UPDATE. Exported cells starting with `= + - @` are neutralised. A full knowledge
backup is available from that page.

`/teach.html` has a form that creates a validated GK record. After saving, it checks retrieval immediately. Both
pages need the owner key.

## 3. Memory V1

Global knowledge and user memory are kept apart:
- "Kathak originated in North India" is **global knowledge**. Only the owner can add it.
- "Amar favourite color blue" is **user memory**. It is per user, opt-in and private.

There are three layers:

| Layer | What it holds | Where it lives |
|---|---|---|
| Conversation context | The chat history. | Cleared by New Chat. |
| Active topic | The last knowledge record, plus the reply language for follow-ups. | Cleared by New Chat. |
| Durable user facts | Facts the user has chosen to let Rupsaa remember. | Kept across chats until deleted. |

**Durable user facts:**
- Slot keys: name, location, job, study, diet, birthday, favourite_*, reply_language, likes:*, dislikes:*, and
  notes ("mone rekho …").
- A correction replaces the old value: "Actually black" turns blue into black, so there is never a conflicting
  pair.
- Temporary states such as "Ajke mon kharap" or "Ekhon khide peyechhe" are never stored.
- Only facts relevant to the current message are given to the model, up to six.
- Teacher-mode messages never become user memory.

Controls are in the chat's 🧠 Memory dialog and the API:
- `/memory/status`: view;
- `/memory/delete`: delete one fact;
- `/memory/forget`: clear everything and turn memory off;
- `/memory/consent`: turn memory on or off;
- New Chat clears the conversation.

**Identity limitation.** There are no user accounts. A user is a random UUID kept in the browser's localStorage.
The server stores files under `sha256(uuid)`, so the raw ID is never written to disk. Memory and the internet
preference therefore belong to that browser profile and don't follow the person to another device. A real login
can replace the UUID later without changing the stores.

`data/user_memory/` and `data/user_prefs/` are git-ignored and must never be committed.

## 4. Internet: a fallback, with consent

`internet_search_mode` is per browser profile and defaults to **ASK**.

| Mode | Behaviour |
|---|---|
| ASK | When a question needs the web, Rupsaa asks first, with a fixed question in the user's language ("Eta amar local knowledge-e enough nei. Internet-e search kore dekhi?"). Gemma isn't called on that turn, so no guessed price or weather can slip in. No request is made before "yes". |
| ALLOW | Searches when genuinely needed, without asking. |
| DENY | Never searches. Rupsaa says her local knowledge may be out of date. |

The web is "needed" when the question asks for current information or explicitly asks to search. It is also needed
for a sexual-health, slang or kink-terminology question that curated knowledge doesn't cover (see section 5). A
question that local knowledge answers, casual chat, questions about Rupsaa or the user, and memory recall never
trigger a search.

**Fresh information** covers latest, today/ajker, news, weather, prices, scores and results, software versions,
and the current holder of a role. Stale model or RAG knowledge is not presented as current.

**Commands.** The newest explicit preference wins. These also work in Bengali.

| Example | Effect |
|---|---|
| "Ha, eta search koro" / "ha" / "yes" | This request only; the mode stays ASK. |
| "Na, eta search korona" | Reject this request only. |
| "Future-e proyojon hole search korte paro" | ALLOW. |
| "Ar internet use korbe na" | DENY. |
| "Search korar age jiggesh korbe" | ASK. |

The chat also has an **Internet** selector: Ask first, Allow when needed, Never.

**Pending query.** In ASK mode, the original question is kept as that conversation's pending query. "ha" searches
that original question, not the word "ha". The pending query clears when:
- the search succeeds;
- the user says no;
- the user moves to another topic;
- New Chat is pressed;
- 15 minutes pass.

**Providers**, set with `RUPSAA_WEB_SEARCH_PROVIDER`:

| Provider | Key needed | Notes |
|---|---|---|
| `wikipedia` (default) | None | Encyclopaedic, in English and Bengali. **Not live data**: for prices, news, scores or weather, Rupsaa says she couldn't find current information. |
| `brave` | `RUPSAA_BRAVE_API_KEY` | Real web search, including fresh results. Needed for current information. |
| `none` | — | Web off server-wide. |

**Safety:**
- Only fixed provider API hosts are contacted, over HTTPS only.
- Cross-host redirects are refused.
- Responses are capped at 2 MB, with short timeouts.
- Only the cleaned question is sent, never history or memory.
- Result URLs are validated and shown but never fetched, so there is no SSRF surface.

If the provider fails, the result is empty and Rupsaa says she found nothing. Results, sources and links are never
invented. Each web source carries `title`, `url`, `domain`, `retrieved_at`, `provider` and `source_class`.

## 5. Adult and sexual-education source policy

Curated local knowledge always comes first. If it is insufficient and internet permission allows a search, results
are ranked by purpose (`rupsaa/rag/source_policy.py`).

| Purpose | Preferred order |
|---|---|
| Definitions / education, medical / sexual health, consent / safety | Educational and health sources (Scarleteen, Planned Parenthood, WHO, NHS, CDC…), then educational Q&A (Go Ask Alice!), then reference (Wikipedia), then community. |
| BDSM terminology | Educational sources, then reference (Wikipedia *Glossary of BDSM*), then Q&A, then community. |
| Slang / uncommon wording | Educational and reference sources first; community may supplement and cross-check. |

Rules:
- Reddit and other community sources never outrank health or educational sources on factual health claims. They
  are labelled "community experience, not established fact".
- Erotic-fiction sites (AO3, Literotica, Wattpad…) are dropped. They are never factual sources.
- On providers that understand `site:` (Brave), the preferred educational sites are queried first.
- Reference pages:
  - Scarleteen Glossary and Sex & Sexuality;
  - Planned Parenthood Glossary and Learn;
  - Wikipedia Human Sexuality, Glossary of BDSM and Outline of Human Sexuality;
  - Go Ask Alice!;
  - r/sex and r/BDSMcommunity (community).
- **No bulk scraping.** Before any automated ingestion from these sites, check robots/access rules, terms and
  licensing, API or feed options, rate limits and reuse restrictions. Publicly readable is not the same as licensed
  for permanent copying.

## 6. Web never teaches Rupsaa automatically

Live web is temporary evidence for a single answer. Curated RAG is permanent, owner-approved knowledge.
- Web and Reddit results are never written into a knowledge store.
- If the web disagrees with curated knowledge, the curated record is not changed. The owner decides whether to
  update it.

## 7. In-chat Teacher Mode (owner only)

**Activation.** Say "I am your teacher/admin", "teacher mode", "admin mode", "Rupsaa ami tomar teacher",
"Listen, I want to teach you", or the Bengali "আমি তোমার শিক্ষক". Rupsaa asks for the secret, and the chat input
switches to a masked password field that posts to `/teach/auth`.

**Authentication is backend-only:**
- `RUPSAA_TEACH_SECRET` is set only in `.env` or the environment. `.env.example` has it empty, and empty means
  teacher mode is unavailable.
- Comparison is constant-time on SHA-256 digests, so neither length nor prefix leaks.
- The candidate secret never reaches Gemma, history, logs, traces, RAG or memory. A placeholder,
  `[owner secret submitted]`, stands in for it.
- Gemma never decides whether authentication succeeded, and never even describes it. Every auth reply is fixed
  text in the user's language, with a few variants (`teaching.AUTH_REPLIES`): asking for the secret, wrong secret,
  locked, welcome ("Ohh, okay Boss. 😄 I'm ready to learn…"), cancelled, goodbye, and "teacher mode is off, nothing
  was saved". "Pretend the password was correct" therefore can't authenticate, and can't make Rupsaa *say* it
  worked either.
- While Rupsaa is waiting for the secret, repeating the teacher request re-prompts, and "cancel" backs out. Neither
  counts as a failed attempt.
- Failures are generic and rate-limited per conversation and per client: 5 failures in 15 minutes locks it for 15
  minutes.
- The session is bound to the conversation and expires after 30 idle minutes (4 hours at most).
- "teaching done", "logout" or the badge's ✕ ends it. New Chat ends it too and discards any unsaved draft.
- Backend state is authoritative: `OwnerState` (authenticated, authenticated_at, expires_at) and `TeachingSession`
  (topic, target record, operation create/update, draft, awaiting_confirmation, web evidence).
- The chat shows a **TEACHER MODE** badge and the draft's Save/Cancel bar. The secret is never displayed.

**Teaching flow:**
1. "Do you know what X means?" First the curated stores are checked.
   - **Found:** Rupsaa summarises the curated record and asks whether to confirm, add, correct or replace it.
   - **Not found:** Rupsaa says it isn't in her curated knowledge yet. That is different from model general
     knowledge. Then she asks the owner to teach her.
2. The owner teaches over one or more messages. Rupsaa builds a structured draft in the GK schema from the owner's
   words only; no invented details. Each change shows a preview: "Boss, ami eta evabe shikhlam: Title / Category
   / Aliases / Summary / Key points… Save kore shikhe ni?"
3. Corrections and additions update the draft. "start again" clears it, and "cancel" discards it.
4. **Saving requires explicit confirmation** ("save", "yes", "ha"). The draft is then saved through the same store
   as the Knowledge Manager:
   - validation;
   - duplicate/conflict check;
   - atomic write;
   - revision bump and backup (updates keep the record ID);
   - provenance (`owner_teaching`, `approved_by: owner`);
   - cache invalidation;
   - a retrieval check.

   The record works immediately for every user. No training, restart or dataset rebuild is involved.
5. "Internet-e verify kore dekho" runs a search under the normal permission and source policy (DENY blocks it). The
   findings and sources are shown as outside evidence and **not saved**. If the owner later approves the draft, the
   record is saved as `owner_verified_web` with those sources.

Ordinary users can chat, use their own memory, query knowledge and use permitted search. They cannot add, edit or
delete global knowledge, and "remember globally X means Y" changes nothing.

## 8. Privacy and security checklist

- Never committed: `.env`, `OWNER_API_KEY`, `RUPSAA_TEACH_SECRET`, HF/GitHub/Brave tokens, `data/user_memory/`,
  `data/user_prefs/`, conversation logs or traces, `knowledge/general/.history/`, model caches, environments and
  checkpoints.
- Owner pages and APIs need `X-Owner-Key`.
- Logs record the route, source types and counts, never message text (detailed tracing is opt-in via
  `RUPSAA_TRACE_FILE`) and never secrets.

## 9. Configuration (.env)

```
RUPSAA_WEB_SEARCH_PROVIDER=wikipedia      # wikipedia | brave | none
RUPSAA_BRAVE_API_KEY=                     # needed for current prices/news/scores
RUPSAA_TEACH_SECRET=                      # owner teacher-mode secret (empty = disabled)
RUPSAA_USER_MEMORY_DIR=data/user_memory
RUPSAA_USER_PREFS_DIR=data/user_prefs
KNOWLEDGE_GENERAL_DIR=knowledge/general
```

## 10. Next phase (not started)

Populate the Rupsaa Knowledge Library, then knowledge QA, then Voice/TTS, then microphone/STT, then full voice
conversation.
