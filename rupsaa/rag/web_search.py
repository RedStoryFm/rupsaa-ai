"""Web knowledge — used ONLY when the user switches "Internet" on for the current conversation.

Order of knowledge (owner decision): owner records (terminology, dance) and owner documents first; the web is a
fallback for general-knowledge QUESTIONS that the owner knowledge does not answer. Sources are returned to the UI.

Privacy / safety:
  - only a cleaned version of the current question is sent (never chat history, never user memory);
  - fixed provider endpoints (no URLs from users or from results are fetched), short timeouts, small result caps;
  - results are wrapped as UNTRUSTED reference text: the model is told to use facts only and ignore instructions.

Provider: Wikipedia (no key, general knowledge, English + Bengali editions). RUPSAA_WEB_SEARCH_PROVIDER=none
disables web access server-wide.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_BN = "ঀ-৿"
USER_AGENT = "RupsaaBot/1.0 (conversational assistant; general-knowledge lookup)"
MAX_RESULTS = 2
MAX_EXTRACT_CHARS = 450  # short: the model paraphrases long English extracts into weaker Banglish

# Question words / fillers that carry no search meaning (Banglish, Bengali, English).
_STOP = {
    # Banglish
    "ki", "kii", "ke", "kake", "kar", "kobe", "kokhon", "kothay", "kothae", "kothakar", "keno", "kivabe", "kibhabe",
    "koto", "kon", "konta", "kemon", "mane", "bolo", "bol", "bolte", "paro", "parbe", "janao", "jano", "jante", "chai",
    "amake", "ektu", "ta", "ti", "er", "e", "te", "r", "ar", "o", "hoy", "hoyechilo", "chilo", "ache", "achhe", "theke",
    "somporke", "shomporke", "niye", "please", "pls", "ekta", "jinish", "jinis", "bujhao", "bojhao", "tell", "about",
    "chilen", "chilo", "hoyechilo", "korechilen", "korechilo", "koren", "kore", "korte", "hobe", "hoyeche", "thake",
    "thaken", "gechen", "boro", "choto", "lomba", "uchu", "beshi", "kom", "naki", "bolun", "holo", "hocche", "jonmo",
    # English
    "what", "who", "whom", "whose", "when", "where", "why", "how", "is", "are", "was", "were", "the", "a", "an", "of",
    "do", "does", "did", "can", "you", "me", "please", "tell", "explain", "in", "on", "to",
    # Bengali
    "কী", "কি", "কে", "কাকে", "কার", "কবে", "কখন", "কোথায়", "কোথাকার", "কেন", "কীভাবে", "কিভাবে", "কত", "কোন", "কেমন",
    "মানে", "বলো", "বল", "বলতে", "পারো", "আমাকে", "একটু", "টা", "টি", "এর", "সম্পর্কে", "নিয়ে", "হয়", "ছিল", "আছে",
    "ছিলেন", "করেছিলেন", "হয়েছিল", "বড়", "ছোট", "কতটা", "নাকি", "হলো",
}
_QUESTION_RE = re.compile(
    rf"\?|？|^\s*(what|who|whom|whose|when|where|why|how|which|is|are|was|were|do|does|did|can|could|tell me|explain)\b"
    rf"|(?<![A-Za-z{_BN}])(ki|ke|kake|kar|kobe|kokhon|kothay|kothakar|keno|kivabe|kibhabe|koto|kon|mane ki)(?![A-Za-z{_BN}])"
    r"|(কী|কি|কে|কবে|কখন|কোথায়|কোথাকার|কেন|কীভাবে|কিভাবে|কত|কোন)",
    re.IGNORECASE,
)


@dataclass
class WebResult:
    title: str
    url: str
    extract: str
    provider: str = "wikipedia"


def is_question(message: str) -> bool:
    return bool(_QUESTION_RE.search(message.strip()))


def clean_query(message: str, term_candidate: str | None = None) -> str:
    """Content words of the question — what a search engine should see."""
    if term_candidate:
        return term_candidate.strip()[:120]
    words = re.findall(rf"[A-Za-z0-9{_BN}'\-]+", message)
    kept = [w for w in words if w.lower() not in _STOP]
    return " ".join(kept)[:120].strip()


# Questions about Rupsaa or about the user are conversation, not web look-ups.
_PERSONAL_RE = re.compile(
    rf"(?<![A-Za-z{_BN}])(tumi|tomar|tomake|tui|tor|toke|apni|apnar|ami|amar|amake|amra|you|your|yours|yourself|i|my|me|"
    rf"mine|we|our)(?![A-Za-z{_BN}])|তুমি|তোমার|তোমাকে|তুই|তোর|আপনি|আপনার|আমি|আমার|আমাকে|আমরা",
    re.IGNORECASE,
)


def should_search(*, allow_internet: bool, route: str, message: str, owner_knowledge_found: bool,
                  smalltalk: bool = False) -> bool:
    """Web only for real general-knowledge questions that owner knowledge did not answer; never for greetings/chat,
    questions about Rupsaa or the user, memory questions or follow-ups."""
    if not allow_internet or owner_knowledge_found or smalltalk:
        return False
    if route not in ("general", "knowledge", "terminology", "casual"):  # short questions ("Taj Mahal kothay?") route casual
        return False
    if _PERSONAL_RE.search(message):
        return False
    return is_question(message) and bool(clean_query(message))


class WikipediaProvider:
    name = "wikipedia"

    def __init__(self, timeout: float = 6.0, cache_seconds: int = 3600):
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, list[WebResult]]] = {}

    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 — fixed https endpoints only
            return json.loads(r.read(2_000_000).decode("utf-8"))

    def _matching_titles(self, base: str, query: str) -> list[str]:
        """Search the full query, then progressively shorter prefixes; keep only titles sharing a word with the
        query actually searched (Wikipedia full-text search otherwise returns loosely related pages)."""
        words = query.split()
        for n in range(len(words), 0, -1):
            q = " ".join(words[:n])
            api = f"{base}/w/api.php?" + urllib.parse.urlencode(
                {"action": "query", "list": "search", "srsearch": q, "srlimit": MAX_RESULTS + 1, "format": "json"})
            try:
                titles = [x["title"] for x in self._get(api).get("query", {}).get("search", [])]
            except Exception as e:  # network/timeout/parse: web knowledge is optional, chat continues without it
                logger.warning("web search failed: %s", type(e).__name__)
                return []
            keys = {w.lower() for w in words[:n] if len(w) > 2}
            good = [t for t in titles if keys & {w.lower() for w in re.findall(rf"[A-Za-z0-9{_BN}]+", t)}]
            exact = [t for t in good if t.lower() == q.lower()]
            if exact:  # "Taj Mahal" -> the Taj Mahal page only, not "Taj Mahal (musician)"
                return exact[:1]
            if good:
                return good[:MAX_RESULTS]
        return []

    def search(self, query: str) -> list[WebResult]:
        query = query.strip()
        if not query:
            return []
        hit = self._cache.get(query)
        if hit and time.time() - hit[0] < self.cache_seconds:
            return hit[1]
        langs = ["bn", "en"] if re.search(f"[{_BN}]", query) else ["en"]
        results: list[WebResult] = []
        for lang in langs:
            base = f"https://{lang}.wikipedia.org"
            titles = self._matching_titles(base, query)
            for title in titles[:MAX_RESULTS]:
                slug = urllib.parse.quote(title.replace(" ", "_"), safe="")
                try:
                    data = self._get(f"{base}/api/rest_v1/page/summary/{slug}")
                except Exception as e:  # noqa: BLE001
                    logger.warning("web summary failed: %s", type(e).__name__)
                    continue
                extract = (data.get("extract") or "").strip()
                if extract and data.get("type") != "disambiguation":
                    url = (data.get("content_urls", {}).get("desktop", {}) or {}).get("page") or f"{base}/wiki/{slug}"
                    results.append(WebResult(title=data.get("title", title), url=url, extract=extract[:MAX_EXTRACT_CHARS]))
            if results:
                break
        self._cache[query] = (time.time(), results)
        return results


def get_provider():
    from rupsaa.config import get_settings

    s = get_settings()
    if (s.web_search_provider or "").lower() in ("", "none", "off", "disabled"):
        return None
    if s.web_search_provider.lower() == "wikipedia":
        return WikipediaProvider(timeout=s.web_search_timeout)
    raise ValueError(f"unknown RUPSAA_WEB_SEARCH_PROVIDER {s.web_search_provider!r} (use wikipedia or none)")


def format_web_context(results: list[WebResult]) -> str | None:
    if not results:
        return None
    return "\n\n".join(f"[{i}] {r.title} — {r.url}\n{r.extract}" for i, r in enumerate(results, 1))
