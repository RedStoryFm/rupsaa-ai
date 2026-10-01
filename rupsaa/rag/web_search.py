"""Web evidence for Rupsaa — providers behind one interface, used only through the internet permission policy
(rupsaa/conversation/internet_policy.py: ASK / ALLOW / DENY) and never written into curated knowledge.

    WebSearchProvider.search(query, fresh=False) -> list[WebResult]   (title, url, domain, snippet, retrieved_at)
    normalize_sources(results)                  -> [{"title","url","domain","retrieved_at","provider"}]

Providers:
  wikipedia (default, no key)  — encyclopaedic facts in English/Bengali; NOT a source for current prices/news.
  brave     (RUPSAA_BRAVE_API_KEY) — general web search, suitable for current information.
  none      — web access off server-wide.

Security: only fixed provider API hosts are ever contacted (host allow-list, HTTPS only, redirects to other hosts
refused, response size capped, short timeouts). Result URLs are only validated and displayed — never fetched — so
there is no SSRF surface. Only the cleaned question is sent; never chat history or user memory. Nothing is ever
fabricated: when a provider fails, the result is simply empty.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_BN = "ঀ-৿"
USER_AGENT = "RupsaaBot/1.0 (conversational assistant; general-knowledge lookup)"
MAX_RESULTS = 3
MAX_EXTRACT_CHARS = 450  # short: the model paraphrases long English extracts into weaker Banglish
MAX_RESPONSE_BYTES = 2_000_000

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
    # look-up / freshness fillers
    "search", "koro", "dekho", "google", "internet", "online", "check", "verify", "ekhon", "ajker", "aj", "ajke", "now",
    "dam", "taka",
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
    domain: str = ""
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    source_class: str = "other"  # rupsaa.rag.source_policy class (educational_health, reference, community, …)

    def __post_init__(self):
        if not self.domain:
            self.domain = urllib.parse.urlparse(self.url).hostname or ""


def is_question(message: str) -> bool:
    return bool(_QUESTION_RE.search(message.strip()))


def clean_query(message: str, term_candidate: str | None = None) -> str:
    """Content words of the question — what a search engine should see."""
    words = re.findall(rf"[A-Za-z0-9{_BN}'\-]+", term_candidate or message)
    kept = [w for w in words if w.lower() not in _STOP]
    return " ".join(kept)[:120].strip() or (term_candidate or "").strip()[:120]


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


def safe_url(url: str) -> bool:
    """Display-only URLs from results: http(s), a real host name, no credentials, no local/internal hosts."""
    try:
        u = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or not host or u.username or u.password or "." not in host:
        return False
    if host in ("localhost",) or host.endswith((".local", ".internal")) or re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host):
        return False
    return True


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).hostname != urllib.parse.urlparse(req.full_url).hostname:
            raise urllib.error.HTTPError(newurl, code, "cross-host redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class WebSearchProvider:
    """Base: subclasses set name, allowed_hosts, fresh_capable and implement search()."""

    name = "base"
    allowed_hosts: tuple[str, ...] = ()
    fresh_capable = False
    supports_site_filter = False  # understands `site:` operators in queries

    def __init__(self, timeout: float = 6.0, cache_seconds: int = 900):
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, list[WebResult]]] = {}
        self._opener = urllib.request.build_opener(_SameHostRedirects())

    def _get(self, url: str, headers: dict | None = None) -> dict:
        u = urllib.parse.urlparse(url)
        if u.scheme != "https" or u.hostname not in self.allowed_hosts:
            raise ValueError(f"host not allowed: {u.hostname}")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
        with self._opener.open(req, timeout=self.timeout) as r:  # noqa: S310 — allow-listed https hosts only
            return json.loads(r.read(MAX_RESPONSE_BYTES).decode("utf-8"))

    def search(self, query: str, fresh: bool = False) -> list[WebResult]:  # pragma: no cover - interface
        raise NotImplementedError


class WikipediaProvider(WebSearchProvider):
    name = "wikipedia"
    allowed_hosts = ("en.wikipedia.org", "bn.wikipedia.org")
    fresh_capable = False

    def __init__(self, timeout: float = 6.0, cache_seconds: int = 3600):
        super().__init__(timeout, cache_seconds)

    def _matching_titles(self, base: str, query: str) -> list[str]:
        """Search the full query, then progressively shorter prefixes; keep only titles sharing a word with the
        query actually searched (Wikipedia full-text search otherwise returns loosely related pages)."""
        words = query.split()
        for n in range(len(words), 0, -1):
            q = " ".join(words[:n])
            api = f"{base}/w/api.php?" + urllib.parse.urlencode(
                {"action": "query", "list": "search", "srsearch": q, "srlimit": MAX_RESULTS, "format": "json"})
            try:
                titles = [x["title"] for x in self._get(api).get("query", {}).get("search", [])]
            except Exception as e:  # network/timeout/parse: web evidence is optional
                logger.warning("web search failed: %s", type(e).__name__)
                return []
            keys = {w.lower() for w in words[:n] if len(w) > 2}
            good = [t for t in titles if keys & {w.lower() for w in re.findall(rf"[A-Za-z0-9{_BN}]+", t)}]
            exact = [t for t in good if t.lower() == q.lower()]
            if exact:  # "Taj Mahal" -> the Taj Mahal page only, not "Taj Mahal (musician)"
                return exact[:1]
            if good:
                return good[:2]
        return []

    def search(self, query: str, fresh: bool = False) -> list[WebResult]:
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
            for title in self._matching_titles(base, query):
                slug = urllib.parse.quote(title.replace(" ", "_"), safe="")
                try:
                    data = self._get(f"{base}/api/rest_v1/page/summary/{slug}")
                except Exception as e:  # noqa: BLE001
                    logger.warning("web summary failed: %s", type(e).__name__)
                    continue
                extract = (data.get("extract") or "").strip()
                url = (data.get("content_urls", {}).get("desktop", {}) or {}).get("page") or f"{base}/wiki/{slug}"
                if extract and data.get("type") != "disambiguation" and safe_url(url):
                    results.append(WebResult(title=data.get("title", title), url=url, extract=extract[:MAX_EXTRACT_CHARS],
                                             provider=self.name))
            if results:
                break
        self._cache[query] = (time.time(), results)
        return results


class BraveSearchProvider(WebSearchProvider):
    """Brave Search API (https://api.search.brave.com) — needs RUPSAA_BRAVE_API_KEY. Uses result snippets only."""

    name = "brave"
    allowed_hosts = ("api.search.brave.com",)
    fresh_capable = True
    supports_site_filter = True

    def __init__(self, api_key: str, timeout: float = 6.0):
        super().__init__(timeout, cache_seconds=600)
        if not api_key:
            raise ValueError("RUPSAA_BRAVE_API_KEY is required for the brave provider")
        self._key = api_key

    def search(self, query: str, fresh: bool = False) -> list[WebResult]:
        query = query.strip()
        if not query:
            return []
        params = {"q": query, "count": 5, "safesearch": "moderate"}
        if fresh:
            params["freshness"] = "pw"  # past week
        try:
            data = self._get("https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(params),
                             headers={"X-Subscription-Token": self._key})
        except Exception as e:  # noqa: BLE001 — never fabricate on failure
            logger.warning("brave search failed: %s", type(e).__name__)
            return []
        out = []
        for item in (data.get("web", {}) or {}).get("results", [])[:MAX_RESULTS]:
            url, title = item.get("url", ""), re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
            snippet = re.sub(r"<[^>]+>", "", item.get("description", "")).strip()
            if title and snippet and safe_url(url):
                out.append(WebResult(title=title, url=url, extract=snippet[:MAX_EXTRACT_CHARS], provider=self.name))
        return out


def get_provider():
    from rupsaa.config import get_settings

    s = get_settings()
    name = (s.web_search_provider or "").lower()
    if name in ("", "none", "off", "disabled"):
        return None
    if name == "wikipedia":
        return WikipediaProvider(timeout=s.web_search_timeout)
    if name == "brave":
        return BraveSearchProvider(api_key=s.brave_api_key or "", timeout=s.web_search_timeout)
    raise ValueError(f"unknown RUPSAA_WEB_SEARCH_PROVIDER {s.web_search_provider!r} (use wikipedia, brave or none)")


def search_with_policy(provider: "WebSearchProvider", query: str, *, fresh: bool = False,
                       topic: str | None = None) -> list[WebResult]:
    """Provider search + trusted source routing (rupsaa/rag/source_policy.py). For adult / sexual-education
    questions on providers that understand `site:`, the preferred educational sources are queried first."""
    from rupsaa.rag import source_policy

    results: list[WebResult] = []
    sq = source_policy.site_query(query, topic) if getattr(provider, "supports_site_filter", False) else None
    if sq:
        results = provider.search(sq, fresh=fresh)
    if len(results) < MAX_RESULTS:
        seen = {r.url for r in results}
        results += [r for r in provider.search(query, fresh=fresh) if r.url not in seen]
    return source_policy.rank(results, topic)[:MAX_RESULTS]


def normalize_sources(results: list[WebResult]) -> list[dict]:
    return [{"title": r.title, "url": r.url, "domain": r.domain, "retrieved_at": r.retrieved_at, "provider": r.provider,
             "source_class": r.source_class} for r in results if safe_url(r.url)]


def format_web_context(results: list[WebResult], *, fresh: bool = False, fresh_capable: bool = True) -> str | None:
    if not results:
        return None
    from rupsaa.rag.source_policy import COMMUNITY, LABELS

    lines = [f"[{i}] {r.title} — {r.domain} ({LABELS.get(r.source_class, 'web')}; retrieved {r.retrieved_at})\n{r.extract}"
             for i, r in enumerate(results, 1)]
    if any(r.source_class == COMMUNITY for r in results):
        lines.append("Note: community posts describe people's experiences and slang usage — use them only as that, "
                     "never as medical or factual authority; educational/health sources win where they disagree.")
    if fresh and not fresh_capable:
        lines.append("Note: these are encyclopaedia summaries, not live data — they may not contain the current "
                     "value the user asked for; if they don't, say you couldn't find current information.")
    return "\n\n".join(lines)
