"""Service layer wiring the FastAPI routes to Rupsaa's core engine.

The heavy model is loaded lazily (on first chat request, or explicitly via
startup) rather than at import time, so importing this module — e.g. for
unit tests — never triggers a multi-GB model download. Tests that don't
want to load the real model should override `get_service` via FastAPI's
`app.dependency_overrides` with a fake/mocked RupsaaService instead of
monkeypatching internals.
"""

from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache
from pathlib import Path

from rupsaa.conversation.language_control import directive_for
from rupsaa.conversation.manager import ConversationManager
from rupsaa.guardrails.essential_boundaries import check_text
from rupsaa.model.inference import ChatResult, RupsaaEngine
from rupsaa.personality.language import detect_language, fixed_reply_language
from rupsaa.rag.context_builder import build_turn_knowledge, memory_note as recall_note
from rupsaa.rag.dance import DanceStore
from rupsaa.rag.pipeline import RagPipeline
from rupsaa.rag.terminology import TerminologyStore
from rupsaa.conversation import internet_policy as ip
from rupsaa.conversation import user_memory as um
from rupsaa.owner import teaching
from rupsaa.rag import source_policy, web_search
from rupsaa.rag.router import classify_message, is_smalltalk

logger = logging.getLogger("rupsaa.api.services")


def _trace_turn(*, conversation_id, message, language, knowledge, history, result) -> None:
    """Opt-in per-turn trace (RUPSAA_TRACE_FILE=<path.jsonl>): exactly what the model
    received. Off by default; contains conversation text, never credentials."""
    import json
    import os
    from datetime import datetime, timezone

    path = os.getenv("RUPSAA_TRACE_FILE")
    if not path:
        return
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "user": message,
        "detected_language": language,
        "route": knowledge.route,
        "route_reason": knowledge.decision.reason,
        "term_candidate": knowledge.decision.term_candidate,
        "terms_used": knowledge.terms_used,
        "rag_sources": [s.get("source_filename") for s in knowledge.sources],
        "rag_context_attached": knowledge.retrieved_context is not None,
        "requested_language": knowledge.language,
        "history_passed": history,
        "system_prompt": getattr(result, "system_prompt", None),
        "generation": getattr(result, "generation_params", None),
        "reply": result.text,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("could not write trace to %s", path)


_CANCEL_RE = teaching._CANCEL


def _is_cancel(message: str) -> bool:
    return bool(_CANCEL_RE.search(message))


class RupsaaService:
    def __init__(self):
        self._engine: RupsaaEngine | None = None
        self._rag_pipeline: RagPipeline | None = None
        self.conversation_manager = ConversationManager()
        self._terminology: TerminologyStore | None = None
        self._dance: DanceStore | None = None
        # conversation_id -> term ids used on the previous turn (for follow-ups
        # like "এটা বাংলায় বুঝিয়ে বলো").
        self._last_terms: dict[str, list[str]] = {}
        # conversation_id -> explicit reply-language choice ("banglay bolo" etc.)
        self._language: dict[str, dict] = {}
        # One model load at a time: two simultaneous first messages must not load the 7B model twice.
        self._load_lock = threading.Lock()
        self._generate_lock = threading.Lock()
        self._preload_thread: threading.Thread | None = None
        self.load_error: str | None = None
        self._user_memory: um.UserMemoryStore | None = None
        self._web_provider = None
        self._web_provider_loaded = False

    @property
    def user_memory(self) -> um.UserMemoryStore:
        if self._user_memory is None:
            from rupsaa.config import PROJECT_ROOT, get_settings

            s = get_settings()
            d = Path(s.user_memory_dir)
            self._user_memory = um.UserMemoryStore(d if d.is_absolute() else PROJECT_ROOT / d, s.user_memory_max_facts)
        return self._user_memory

    @property
    def web_provider(self):
        if not self._web_provider_loaded:
            self._web_provider = web_search.get_provider()
            self._web_provider_loaded = True
        return self._web_provider

    @property
    def engine(self) -> RupsaaEngine:
        if self._engine is None:
            with self._load_lock:
                if self._engine is None:
                    self._engine = self._load_engine()
        return self._engine

    def _load_engine(self) -> RupsaaEngine:
        from rupsaa.config import get_settings

        settings = get_settings()
        adapter = settings.resolve_path(settings.adapter_path)
        if settings.is_production and not (adapter / "adapter_model.safetensors").is_file():
            # Production never silently falls back to the base model or another adapter.
            raise RuntimeError(f"configured adapter '{adapter.name}' not found — refusing to serve")
        started = time.monotonic()
        logger.info("Loading model: base=%s adapter=%s", settings.model_id or "configs/model.yaml", adapter.name)
        engine = RupsaaEngine.load(use_adapter=True)
        if settings.is_production and engine.loaded.adapter_path is None:
            raise RuntimeError(f"adapter '{adapter.name}' did not attach — refusing to serve the base model")
        logger.info("Model ready in %.0fs: adapter=%s prompt_version=%s", time.monotonic() - started,
                    Path(engine.loaded.adapter_path).name if engine.loaded.adapter_path else None, engine.prompt_version)
        return engine

    def start_preload(self) -> None:
        """Load the model in the background (production) so /ready turns green before real traffic."""
        if self._engine is not None or (self._preload_thread and self._preload_thread.is_alive()):
            return

        def _run() -> None:
            try:
                _ = self.engine
            except Exception as exc:  # surfaced via /ready and the logs
                self.load_error = type(exc).__name__ + ": " + str(exc)[:200]
                logger.exception("Model preload failed")

        self._preload_thread = threading.Thread(target=_run, name="rupsaa-model-preload", daemon=True)
        self._preload_thread.start()

    def readiness(self) -> dict:
        loading = bool(self._preload_thread and self._preload_thread.is_alive())
        return {"ready": self._engine is not None, "model_loading": loading, "model_error": self.load_error}

    def knowledge_status(self) -> dict:
        from rupsaa.config import get_settings

        settings = get_settings()
        index_dir = settings.resolve_path(settings.vector_store_dir)
        try:
            terms = len(self.terminology.list(include_disabled=False))
            dances = len(self.dance.list(include_disabled=False))
            ok = True
        except Exception:
            logger.exception("knowledge store unreadable")
            terms = dances = 0
            ok = False
        return {"knowledge_ok": ok, "terminology_entries": terms, "dance_entries": dances,
                "rag_index_present": index_dir.is_dir() and any(p.name != ".gitkeep" for p in index_dir.iterdir())}

    @property
    def rag_pipeline(self) -> RagPipeline:
        if self._rag_pipeline is None:
            self._rag_pipeline = RagPipeline()
        return self._rag_pipeline

    @property
    def terminology(self) -> TerminologyStore:
        if self._terminology is None:
            from rupsaa.config import PROJECT_ROOT, get_settings

            self._terminology = TerminologyStore(PROJECT_ROOT / get_settings().knowledge_terminology_dir)
        return self._terminology

    @property
    def dance(self) -> DanceStore:
        if self._dance is None:
            from rupsaa.config import PROJECT_ROOT, get_settings

            self._dance = DanceStore(PROJECT_ROOT / get_settings().knowledge_dance_dir)
        return self._dance

    def is_model_loaded(self) -> bool:
        return self._engine is not None

    # ------------------------------------------------------------------------------------------------ stores
    @property
    def general(self):
        if getattr(self, "_general", None) is None:
            from rupsaa.config import PROJECT_ROOT, get_settings
            from rupsaa.rag.general_knowledge import GeneralKnowledgeStore

            d = Path(get_settings().knowledge_general_dir)
            self._general = GeneralKnowledgeStore(d if d.is_absolute() else PROJECT_ROOT / d)
        return self._general

    @property
    def prefs(self) -> ip.PreferenceStore:
        if getattr(self, "_prefs", None) is None:
            from rupsaa.config import PROJECT_ROOT, get_settings

            d = Path(get_settings().user_prefs_dir)
            self._prefs = ip.PreferenceStore(d if d.is_absolute() else PROJECT_ROOT / d)
        return self._prefs

    def _owner_state(self, cid: str) -> teaching.OwnerState:
        if not hasattr(self, "_owner"):
            self._owner, self._owner_failures, self._teach_ended = {}, teaching.FailureLimiter(), set()
        return self._owner.setdefault(cid, teaching.OwnerState())

    def internet_mode(self, user_id: str | None, conversation_id: str | None) -> str:
        return self.prefs.get(user_id if um.valid_user_id(user_id) else None, conversation_id)

    def set_internet_mode(self, user_id: str | None, conversation_id: str | None, mode: str) -> str:
        return self.prefs.set(user_id if um.valid_user_id(user_id) else None, conversation_id, mode)

    # ------------------------------------------------------------------------------------------------ chat
    def chat(
        self,
        *,
        message: str,
        conversation_id: str | None,
        use_rag: bool,
        temperature: float | None,
        top_p: float | None,
        max_new_tokens: int | None,
        user_id: str | None = None,
        client_key: str | None = None,
        secret_submission: bool = False,
        allow_internet: bool | None = None,  # legacy per-request switch: True == ALLOW for this request
    ) -> dict:
        """Source decision pipeline (docs/KNOWLEDGE_MEMORY_INTERNET.md):
        owner auth/teaching → internet preference commands → route + local knowledge (terminology, dance, general,
        documents) → relevant user memory → internet need (freshness, ASK/ALLOW/DENY, pending query) → model."""
        started = time.monotonic()
        from rupsaa.config import get_settings

        settings = get_settings()
        cap = settings.max_new_tokens_cap
        if max_new_tokens is not None:
            max_new_tokens = min(max_new_tokens, cap)
        uid = user_id if um.valid_user_id(user_id) else None
        conversation = self.conversation_manager.get_or_create(conversation_id)
        cid = conversation.conversation_id
        owner = self._owner_state(cid)
        now = time.time()
        if owner.expired(now):
            self._owner[cid] = owner = teaching.OwnerState()
            self._teach_ended.add(cid)

        # --- 1. owner authentication (backend-only; the candidate secret never reaches the model/history/logs) ----
        # Every auth reply is fixed text (teaching.AUTH_REPLIES): Gemma neither decides nor describes the outcome.
        fixed_lang = fixed_reply_language(message)
        if owner.awaiting_secret and not secret_submission and _is_cancel(message):
            owner.awaiting_secret = False  # the user changed their mind: not a failed attempt
            return self._finish(message, conversation, teaching.auth_reply("cancelled", owner.language), owner,
                                route="owner_auth")
        elif owner.awaiting_secret and not secret_submission and teaching.is_teacher_request(message):
            owner.awaiting_secret = False  # asking again re-prompts below instead of counting as a wrong secret
        elif owner.awaiting_secret or secret_submission:
            return self._handle_secret(message, conversation, owner, client_key, uid, temperature, top_p, max_new_tokens,
                                       started)

        boundary = check_text(message)
        language = detect_language(message)
        if not boundary.allowed:
            from rupsaa.guardrails.essential_boundaries import REFUSAL_MESSAGE

            return {"response": REFUSAL_MESSAGE, "conversation_id": cid, "language": language, "rag_used": False,
                    "sources": [], "blocked": True}

        notes: list[str] = []
        extra_flags: dict = {}
        turn: dict = {}  # per-turn facts from the teaching handler (e.g. a curated record was shown)
        if owner.authenticated:
            owner.last_active = now
            handled = self._handle_teaching(message, conversation, owner, uid, notes, turn)
            if handled is not None:  # deterministic teaching reply (draft preview / save result / goodbye)
                return self._finish(message, conversation, handled, owner)
        elif teaching.is_teacher_request(message):
            if not settings.teach_secret:
                return self._finish(message, conversation, teaching.auth_reply("unavailable", fixed_lang), owner,
                                    route="owner_auth")
            owner.awaiting_secret, owner.language = True, fixed_lang
            return self._finish(message, conversation, teaching.auth_reply("ask", fixed_lang), owner,
                                route="owner_auth", owner_auth_requested=True)
        elif teaching.is_save_request(message) and cid in self._teach_ended:
            return self._finish(message, conversation, teaching.auth_reply("not_saved", fixed_lang), owner)
        elif teaching.is_save_request(message):
            notes.append("Teacher mode is NOT active in this chat, so nothing can be saved to Rupsaa's knowledge. Don't "
                         "say you are saving or learning anything; if they want to teach you, they need teacher mode.")

        # --- 2. internet preference commands / pending query ----------------------------------------------------
        mode = ip.ALLOW if allow_internet else self.internet_mode(uid, cid)
        pending = self._pending.get(cid) if hasattr(self, "_pending") else None
        if not hasattr(self, "_pending"):
            self._pending = {}
        if pending and now - pending["at"] > ip.PENDING_TTL_SECONDS:
            self._pending.pop(cid, None)
            pending = None
        command = ip.detect_command(message, has_pending=bool(pending))
        web_query = None  # query to search this turn (pending or current)
        if command in ("allow", "deny", "ask"):
            mode = self.set_internet_mode(uid, cid, {"allow": ip.ALLOW, "deny": ip.DENY, "ask": ip.ASK}[command])
            ack = {ip.ALLOW: "The user now allows you to search the internet when needed. In a few words in the user's "
                             "language, confirm you'll search when a question needs it.",
                   ip.DENY: "The user asked you not to use the internet any more. In a few words in the user's language, "
                            "confirm you won't search the internet from now on (they can turn it back on any time).",
                   ip.ASK: "The user wants you to ask before any internet search. In a few words in the user's language, "
                           "confirm you'll ask first before searching."}[mode]
            if mode == ip.ALLOW and pending:
                ack = ("The user now allows internet search. Confirm that in a few words, then answer their earlier "
                       "question from the web results below.")
            notes.append(ack)
            if mode == ip.ALLOW and pending:
                web_query = pending["query"]
            if mode != ip.ALLOW:
                self._pending.pop(cid, None)
        elif command == "approve_once" and pending:
            web_query = pending["query"]
        elif command == "reject_once" and pending:
            self._pending.pop(cid, None)
            notes.append(f"The user decided not to search the internet for their earlier question "
                         f"(\"{pending['query'][:200]}\"). Accept that lightly; if you answer from what you know, say "
                         "it may not be current.")
        elif pending and command is None:
            self._pending.pop(cid, None)  # a new topic abandons the pending look-up

        # --- 3. route + local knowledge ---------------------------------------------------------------------------
        knowledge_message = web_query or message
        knowledge = build_turn_knowledge(
            knowledge_message,
            use_rag=use_rag,
            rag_query=lambda q, strict=False: self.rag_pipeline.query(q, strict=strict),
            terminology=self.terminology,
            previous_terms=self._last_terms.get(cid),
            history_messages=len(conversation.messages),
            history_truncated=conversation.dropped_messages > 0,
            history=conversation.messages,
            language_state=self._language.get(cid),
            dance=self.dance,
            general=self.general,
        )
        logger.info("route=%s terms=%s docs=%d lang=%s retrieval=%s", knowledge.route, knowledge.terms_used,
                    len(knowledge.sources), knowledge.language,
                    [(r.get("record_id"), r.get("match"), r.get("score")) for r in knowledge.retrieval])
        retrieved_context, sources = knowledge.retrieved_context, knowledge.sources

        # --- 4. relevant user memory (opt-in, separate from global knowledge) --------------------------------------
        memory_enabled, memory_saved, memory_used = None, 0, False
        if uid and not owner.authenticated:
            store = self.user_memory
            if um.is_forget_request(message):
                was_on = store.get(uid).consent
                store.forget(uid)
                memory_enabled = False
                if was_on:
                    notes.append(um.memory_note(um.UserMemory(), forgotten=True))
            else:
                memory_saved = len(store.remember(uid, um.extract_facts(message)))
                mem = store.get(uid)
                memory_enabled = mem.consent
                note = um.memory_note(mem, message, recall=um.is_recall_request(message))
                if note:
                    notes.append(note)
                    memory_used = bool(um.relevant_facts(mem, message, recall_all=um.is_recall_request(message)))
                    if knowledge.route == "memory" and um.relevant_facts(mem, message):
                        knowledge.conversation_note = recall_note(
                            conversation.messages, len(conversation.messages), conversation.dropped_messages > 0,
                            question=message, long_term=True)

        # --- 5. internet: only when needed, only as permitted ------------------------------------------------------
        web_context, web_sources, provider, ask_reply = None, [], self.web_provider, None
        local_found = bool(knowledge.terms_used or retrieved_context)
        if web_query is None and not owner.authenticated and command is None:  # a permission command is not a query
            personal = bool(web_search._PERSONAL_RE.search(message))
            question = web_search.is_question(message)
            authoritative = source_policy.adult_topic(message) in source_policy.AUTHORITATIVE_TOPICS
            if ip.needs_web(message=message, route=knowledge.route, smalltalk=is_smalltalk(message), personal=personal,
                            local_found=local_found, question=question, authoritative_topic=authoritative) \
                    and not um.is_recall_request(message):
                if provider is None or mode == ip.DENY:
                    notes.append("This question needs current/online information, but internet search is "
                                 + ("switched off by the user" if mode == ip.DENY else "not available on this server")
                                 + ". Say naturally that your local knowledge isn't enough or may be out of date — "
                                 "don't present a guess as current fact, and don't pressure them to enable it.")
                elif mode == ip.ASK:
                    self._pending[cid] = {"query": message, "at": now}
                    # Fixed wording: the model must not answer (or guess) before the user allows a search.
                    ask_reply = ip.permission_question(message, knowledge.language)
                    extra_flags["internet_permission_requested"] = True
                else:
                    web_query = message
        if web_query is not None and provider is not None:
            fresh = ip.is_fresh(web_query)
            results = web_search.search_with_policy(
                provider, web_search.clean_query(web_query, classify_message(web_query).term_candidate), fresh=fresh,
                topic=source_policy.adult_topic(web_query))
            self._pending.pop(cid, None)
            if results:
                web_context = web_search.format_web_context(results, fresh=fresh, fresh_capable=provider.fresh_capable)
                web_sources = web_search.normalize_sources(results)
                if command in ("approve_once", "allow"):
                    notes.append(f"The user approved the search for their earlier question: \"{web_query[:200]}\". "
                                 "Answer THAT question now from the web results.")
            else:
                notes.append(f"You searched the internet for \"{web_query[:200]}\" but found nothing usable. Say so "
                             "honestly; do not invent an answer, sources or links.")
            logger.info("web lookup: provider=%s results=%d fresh=%s", provider.name, len(results), fresh)  # no query text

        conversation_note = "\n\n".join(x for x in (*notes, knowledge.conversation_note) if x) or None
        history_before = [{"role": m.role, "content": m.content} for m in conversation.messages]
        engine = self.engine
        if ask_reply is not None:
            result = ChatResult(text=ask_reply, blocked=False)
        else:
            with self._generate_lock:  # one generation at a time on the single GPU; others wait their turn
                result = engine.chat(
                    history=conversation.messages,
                    user_message=message,
                    retrieved_context=retrieved_context,
                    terminology_context=knowledge.terminology_context,
                    conversation_note=conversation_note,
                    language_directive=directive_for(knowledge.language_state if knowledge.language else None),
                    dance_context=knowledge.dance_context,
                    web_context=web_context,
                    general_context=knowledge.general_context,
                    generation_overrides={"temperature": temperature, "top_p": top_p, "max_new_tokens": max_new_tokens},
                )

        if not result.blocked:
            self.conversation_manager.append_turn(conversation, message, result.text)
            if knowledge.terms_used:
                self._last_terms[cid] = knowledge.terms_used
            elif knowledge.route not in ("followup", "memory"):
                self._last_terms.pop(cid, None)
            if knowledge.language_state:
                self._language[cid] = knowledge.language_state
            else:
                self._language.pop(cid, None)
            self._prune_side_state()

        curated = bool(knowledge.terms_used or retrieved_context or knowledge.general_context or turn.get("curated"))
        source_types = [name for name, used in (
            ("CONVERSATION", knowledge.route in ("followup", "memory") and bool(history_before)),
            ("USER_MEMORY", memory_used),
            ("CURATED_RAG", curated),
            ("WEB", bool(web_sources)),
            ("MODEL_GENERAL_KNOWLEDGE", not curated and not web_sources),
        ) if used]
        _trace_turn(conversation_id=cid, message=message, language=language, knowledge=knowledge,
                    history=history_before, result=result)
        # Operational log line: no message text (verbose tracing is opt-in via RUPSAA_TRACE_FILE).
        logger.info("chat done route=%s sources=%s lang=%s reply_lang=%s terms=%d docs=%d web=%d chars_in=%d "
                    "tokens_out=%s latency_ms=%d",
                    knowledge.route, "+".join(source_types), language, knowledge.language, len(knowledge.terms_used), len(sources),
                    len(web_sources), len(message), getattr(result, "completion_tokens", None),
                    (time.monotonic() - started) * 1000)
        return {
            "response": result.text,
            "conversation_id": cid,
            "language": language,
            "rag_used": retrieved_context is not None,
            "sources": sources,
            "blocked": result.blocked,
            "route": knowledge.route,
            "terms_used": knowledge.terms_used,
            "response_language": knowledge.language,
            "web_sources": web_sources,
            "source_types": source_types,
            "memory_enabled": memory_enabled,
            "memory_saved": memory_saved,
            "internet_mode": mode,
            "pending_search": cid in self._pending,
            **extra_flags,
            **owner.to_public(),
        }

    # ------------------------------------------------------------------------------------------------ owner mode
    def _handle_secret(self, candidate, conversation, owner, client_key, uid, temperature, top_p, max_new_tokens, started):
        from rupsaa.config import get_settings

        cid = conversation.conversation_id
        keys = (f"conv:{cid}", f"client:{client_key}" if client_key else None)
        limiter = self._owner_failures
        owner.awaiting_secret = False
        if limiter.locked(*keys):
            outcome = "locked"
        elif teaching.verify_secret(candidate, get_settings().teach_secret):
            limiter.reset(*keys)
            now = time.time()
            owner.authenticated, owner.authenticated_at, owner.last_active = True, now, now
            owner.session = teaching.TeachingSession()
            self._teach_ended.discard(cid)
            outcome = "authenticated"
        else:
            limiter.fail(*keys)
            outcome = "failed"
        logger.info("owner auth: %s", outcome)  # never the candidate
        # The model is not called at all: the history records only the placeholder and the fixed reply.
        return self._finish(teaching.SECRET_PLACEHOLDER, conversation, teaching.auth_reply(outcome, owner.language), owner,
                            route="owner_auth", owner_auth=outcome)

    def _handle_teaching(self, message, conversation, owner, uid, notes, turn=None) -> str | None:
        """Authenticated owner turn. Returns a deterministic reply text, or None after adding a note for the model."""
        s = owner.session
        stores = {"general": self.general, "terminology": self.terminology, "dance": self.dance}
        if teaching._EXIT.search(message):
            owner.authenticated, owner.awaiting_secret = False, False  # clear the live state object in place
            owner.session = teaching.TeachingSession()
            self._teach_ended.add(conversation.conversation_id)
            return teaching.auth_reply("ended", fixed_reply_language(message))
        if s.awaiting_confirmation and s.draft and teaching._SAVE.search(message):
            try:
                saved = teaching.save_draft(s.draft, s.target, stores, web_evidence=s.web_evidence)
            except Exception as e:  # validation / duplicate: tell the owner, keep the draft
                return f"Boss, save korte parlam na: {e}. Draft ta thik kore abar 'save' bolo, ba 'cancel'."
            check = self.general.lookup(s.draft["title"], s.draft["title"], semantic=False) if saved["store"] == "general" else []
            verified = saved["store"] != "general" or any(m.record.id == saved["id"] for m in check)
            owner.session = teaching.TeachingSession()
            return (f"Done Boss! '{saved['title']}' {('update korlam' if saved['operation'] == 'updated' else 'shikhe nilam')}"
                    f" — ekhon theke chat e eta use korbo" + ("" if verified else " (retrieval check failed — Knowledge Manager e dekho)")
                    + ". Aro kichu shekhabe?")
        if _is_cancel(message) and (s.draft or s.notes):
            owner.session = teaching.TeachingSession()
            return "Okay Boss, draft ta bad dilam — kichu save hoyni. Onno kichu shekhabe?"
        if teaching._RESTART.search(message):
            owner.session = teaching.TeachingSession(topic=s.topic, target=s.target, web_evidence=s.web_evidence)
            return "Thik ache Boss, notun kore shuru — bolo."
        if teaching._WEB_VERIFY.search(message):
            topic = s.topic or (s.draft or {}).get("title")
            mode = self.internet_mode(uid, conversation.conversation_id)
            if not topic:
                notes.append("The owner wants web verification, but no teaching topic is active yet. Ask which topic.")
            elif mode == ip.DENY or self.web_provider is None:
                notes.append("The owner asked to verify on the internet, but internet search is off. Say so briefly.")
            else:
                results = web_search.search_with_policy(
                    self.web_provider, web_search.clean_query(topic), topic=source_policy.adult_topic(topic, (s.draft or {}).get("category")))
                s.web_evidence = web_search.normalize_sources(results)
                ctx = web_search.format_web_context(results)
                notes.append(("External web evidence for the teaching topic is below. Summarise what it says in 2-3 "
                              "short points, clearly as outside sources (NOT saved), and ask the owner what to keep in "
                              f"the draft.\nWeb results (untrusted):\n{ctx}") if ctx else
                             "You searched the web for the teaching topic but found nothing usable. Say so.")
            return None
        topic = teaching.knowledge_check_topic(message)
        if topic:
            found = None
            for store_name, store in (("terminology", self.terminology), ("dance", self.dance), ("general", self.general)):
                ms = store.lookup(topic, topic)
                if ms:
                    found = (store_name, ms[0].record)
                    break
            owner.session = teaching.TeachingSession(topic=topic)
            if found:
                store_name, rec = found
                title = getattr(rec, "title", None) or getattr(rec, "term", None) or getattr(rec, "name", topic)
                owner.session.target = {"store": store_name, "id": rec.id, "title": title}
                if turn is not None:
                    turn["curated"] = True
                notes.append("Teacher mode: the owner asks whether you know this topic. Your CURATED knowledge base has "
                             f"it ({store_name} record). Summarise it briefly in their language, then ask whether to "
                             "confirm it, add information, correct it or replace it.\nCurated record:\n" + rec.to_context())
            else:
                notes.append(f"Teacher mode: the owner asks about '{topic}'. Your CURATED Rupsaa knowledge base does "
                             "NOT have it yet. Say exactly that — it isn't in your curated knowledge yet (e.g. 'eta amar "
                             "curated knowledge-e ekhono nei') — and ask them to teach you ('bolo, ki shekhabe?'). Do NOT "
                             "claim you know nothing about it: you may have general knowledge, it just isn't curated.")
            return None
        # teaching content → structured draft → preview (nothing is saved until the owner confirms)
        s.notes.append(message.strip())
        existing = None
        if s.target:
            rec = stores[s.target["store"]].get(s.target["id"])
            existing = {"title": s.target["title"], "category": getattr(rec, "category", ""),
                        "summary": getattr(rec, "summary", "") or getattr(rec, "definition", ""),
                        "description": getattr(rec, "description", "") or getattr(rec, "details", ""),
                        "aliases": list(getattr(rec, "aliases", []))}
        s.draft = teaching.build_draft(s.topic, s.notes, existing, structurer=self._structurer)
        s.awaiting_confirmation = True
        return teaching.format_preview(s.draft, update=bool(s.target))

    def _structurer(self, system: str, user: str) -> str:
        with self._generate_lock:
            return self.engine.complete(system, user)

    def _finish(self, message, conversation, text, owner, route="teaching", **extra) -> dict:
        """Fixed (non-model) reply for teacher/auth turns: recorded in history, no knowledge or web involved."""
        self.conversation_manager.append_turn(conversation, message, text)
        return {"response": text, "conversation_id": conversation.conversation_id,
                "language": "mixed" if message == teaching.SECRET_PLACEHOLDER else detect_language(message),
                "rag_used": False, "sources": [], "blocked": False, "route": route, "terms_used": [], "web_sources": [],
                "memory_enabled": None, "memory_saved": 0, **extra, **owner.to_public()}

    def teach_logout(self, conversation_id: str) -> None:
        if hasattr(self, "_owner") and self._owner.pop(conversation_id, None) is not None:
            self._teach_ended.add(conversation_id)

    def teach_cancel(self, conversation_id: str) -> None:
        if hasattr(self, "_owner") and conversation_id in self._owner:
            self._owner[conversation_id].session = teaching.TeachingSession()

    def _prune_side_state(self) -> None:
        """Per-conversation follow-up/language state lives only as long as its conversation."""
        limit = getattr(self.conversation_manager.store, "max_conversations", 5000)
        if len(self._last_terms) + len(self._language) > 2 * limit:
            for side in (self._last_terms, self._language):
                for cid in [c for c in side if self.conversation_manager.store.get(c) is None]:
                    side.pop(cid, None)

    def reindex(self) -> int:
        self._rag_pipeline = RagPipeline()
        return self._rag_pipeline.ingest()

    def reset_conversation(self, conversation_id: str) -> None:
        """New chat: conversation context, active topic, pending web query and teaching draft are cleared.
        Durable internet preference and opted-in user memory stay (they belong to the browser profile)."""
        self.conversation_manager.reset(conversation_id)
        self._last_terms.pop(conversation_id, None)
        self._language.pop(conversation_id, None)
        getattr(self, "_pending", {}).pop(conversation_id, None)
        getattr(self, "_owner", {}).pop(conversation_id, None)
        getattr(self, "_teach_ended", set()).discard(conversation_id)

    def model_info(self) -> dict:
        info = self._model_info()
        from rupsaa.config import get_settings

        if get_settings().is_production:
            # Never publish server filesystem layout: adapter NAMES only.
            for key in ("adapter_path", "configured_adapter_path"):
                if info.get(key):
                    info[key] = Path(info[key]).name
            if info.get("base_model_id") and Path(info["base_model_id"]).is_absolute():
                info["base_model_id"] = Path(info["base_model_id"]).name
        info["environment"] = "production" if get_settings().is_production else "development"
        info["adapter_name"] = Path(info["adapter_path"]).name if info.get("adapter_path") else None
        return info

    def _model_info(self) -> dict:
        from rupsaa.config import get_settings

        settings = get_settings()
        configured = settings.resolve_path(settings.adapter_path)
        from rupsaa.personality.system_prompt import resolve_prompt_version

        adapter_info = {
            "configured_adapter_path": str(configured),
            "configured_adapter_exists": (configured / "adapter_config.json").is_file(),
        }
        if self._engine is None:
            from rupsaa.config import load_model_config

            return {
                "base_model_id": load_model_config()["base_model_id"],
                "adapter_path": None,
                "quantized": False,
                "device": "not loaded yet",
                "adapter_loaded": False,
                "prompt_version": resolve_prompt_version(str(configured), settings.prompt_version),
                **adapter_info,
            }
        loaded = self._engine.loaded
        return {
            "base_model_id": loaded.base_model_id,
            "adapter_path": loaded.adapter_path,
            "quantized": loaded.quantized,
            "device": str(next(loaded.model.parameters()).device),
            "adapter_loaded": loaded.adapter_path is not None,
            "prompt_version": self._engine.prompt_version,
            **adapter_info,
        }


@lru_cache
def get_service() -> RupsaaService:
    return RupsaaService()
