"""Trusted source routing for web evidence — who gets believed for what.

Applied to live web results only (local curated knowledge is always consulted first and never overridden by the
web). Every result gets a source class from its domain; results are then ordered by the question's PURPOSE:

  definitions / education   → educational & health sources first, then reference
  medical / sexual health   → health & educational sources first; community never outranks them
  consent / safety          → educational & health sources
  BDSM terminology          → educational, then reference (Wikipedia glossary), community last
  slang / uncommon wording  → educational & reference first; community may supplement and cross-check

Community posts (Reddit) are labelled as community experience, not fact. Erotic-fiction sites are never used as
factual sources (dropped). Nothing here crawls or ingests these sites — it only ranks what a permitted, one-off
search returned. Bulk ingestion would first need each site's robots rules, terms/licence, API options and rate
limits checked: publicly readable is not the same as licensed for permanent copying.
"""

from __future__ import annotations

import re

HEALTH_EDU, EDU_QA, REFERENCE, COMMUNITY, FICTION, OTHER = (
    "educational_health", "educational_qa", "reference", "community", "fiction", "other")

_DOMAINS = {
    HEALTH_EDU: ("scarleteen.com", "plannedparenthood.org", "who.int", "nhs.uk", "cdc.gov", "medlineplus.gov",
                 "mayoclinic.org", "nih.gov", "unfpa.org"),
    EDU_QA: ("goaskalice.columbia.edu",),
    REFERENCE: ("wikipedia.org",),
    COMMUNITY: ("reddit.com", "quora.com"),
    FICTION: ("archiveofourown.org", "literotica.com", "wattpad.com", "fanfiction.net", "asstr.org"),
}
# Curated starting points per purpose (documentation + site-restricted queries on providers that support them).
PREFERRED_SITES = {
    "health": ("plannedparenthood.org", "scarleteen.com", "goaskalice.columbia.edu"),
    "consent_safety": ("scarleteen.com", "plannedparenthood.org", "goaskalice.columbia.edu"),
    "education": ("scarleteen.com", "plannedparenthood.org", "goaskalice.columbia.edu"),
    "bdsm": ("scarleteen.com", "en.wikipedia.org"),
    "slang": ("scarleteen.com", "en.wikipedia.org"),
}
REFERENCE_PAGES = {
    "Scarleteen Glossary": "https://www.scarleteen.com/read/glossary",
    "Scarleteen Sex & Sexuality": "https://www.scarleteen.com/read/sex-sexuality",
    "Planned Parenthood Glossary": "https://www.plannedparenthood.org/learn/glossary",
    "Planned Parenthood Learn": "https://www.plannedparenthood.org/learn",
    "Wikipedia Human Sexuality": "https://en.wikipedia.org/wiki/Human_sexuality",
    "Wikipedia Glossary of BDSM": "https://en.wikipedia.org/wiki/Glossary_of_BDSM",
    "Wikipedia Outline of Human Sexuality": "https://en.wikipedia.org/wiki/Outline_of_human_sexuality",
    "Go Ask Alice! (Columbia)": "https://goaskalice.columbia.edu/",
    "r/sex (community)": "https://www.reddit.com/r/sex/",
    "r/BDSMcommunity (community)": "https://www.reddit.com/r/BDSMcommunity/",
}
_ORDER = {
    "health": [HEALTH_EDU, EDU_QA, REFERENCE, OTHER, COMMUNITY],
    "consent_safety": [HEALTH_EDU, EDU_QA, REFERENCE, OTHER, COMMUNITY],
    "education": [HEALTH_EDU, EDU_QA, REFERENCE, OTHER, COMMUNITY],
    "bdsm": [HEALTH_EDU, REFERENCE, EDU_QA, OTHER, COMMUNITY],
    "slang": [HEALTH_EDU, REFERENCE, EDU_QA, COMMUNITY, OTHER],
}
# Purposes where, if curated knowledge has nothing, a permitted web look-up beats a model guess.
AUTHORITATIVE_TOPICS = ("health", "slang", "bdsm")
LABELS = {HEALTH_EDU: "educational/health source", EDU_QA: "educational Q&A", REFERENCE: "reference",
          COMMUNITY: "community discussion — personal experience/opinion, not established fact", OTHER: "web"}

_BN = "ঀ-৿"
_B, _E = rf"(?<![A-Za-z{_BN}])", rf"(?![A-Za-z{_BN}])"
_TOPICS = [  # first match wins: the most safety-relevant purpose is checked first
    ("health", re.compile(
        rf"{_B}(sti|std|hiv|hpv|herpes|syphilis|gonorrh?oea|chlamydia|infection|condom|contracepti\w*|birth\s*control|"
        rf"pregnan\w*|periods?|menstrua\w*|ovulat\w*|ipill|morning[\s-]after\s+pill|emergency\s*contraception|erection|"
        rf"erectile|lubricant|lube|painful\s+sex|vaginal\s+(?:bleeding|discharge|itch\w*)|sti\s+test\w*|safe\s*sex|"
        rf"vaginismus|ejaculat\w*|libido|garbho){_E}|কনডম|গর্ভ|পিরিয়ড|সংক্রমণ|যৌনরোগ", re.I)),
    ("consent_safety", re.compile(
        rf"{_B}(consent|safe\s*word|safeword|boundar\w*|coerc\w*|abuse|assault|harass\w*|rape|no\s+means\s+no|"
        rf"aftercare|hard\s+limits?|soft\s+limits?|sommoti|anumoti){_E}|সম্মতি|অনুমতি", re.I)),
    ("bdsm", re.compile(
        rf"{_B}(bdsm|bondage|domme|dominant|submissive|kink\w*|fetish\w*|spanking|impact\s*play|"
        rf"shibari|rope\s*play|sadis\w*|masochis\w*|power\s*exchange|edging|praise\s*kink|degradation\s*kink){_E}", re.I)),
    ("slang", re.compile(rf"{_B}(slang|meaning\s+of|full\s*form|what\s+does\s+\S+\s+stand\s+for|abbreviation|emoji){_E}",
                         re.I)),
    ("education", re.compile(
        rf"{_B}(sex\w*|sexual\w*|foreplay|orgasm\w*|masturbat\w*|kiss\w*|intimacy|intimate|oral|anal|arous\w*|"
        rf"puberty|anatomy|clitoris|vulva|vagina|penis|g[\s-]?spot|virginity|porn\w*|nude\w*|sexting|asexual|"
        rf"lgbt\w*|gay|lesbian|bisexual|queer|transgender|chumu|joun\w*){_E}|যৌন|চুমু|সেক্স", re.I)),
]


def classify_domain(domain: str) -> str:
    d = (domain or "").lower().rstrip(".")
    for cls, roots in _DOMAINS.items():
        if any(d == r or d.endswith("." + r) for r in roots):
            return cls
    return OTHER


def adult_topic(message: str, category: str | None = None) -> str | None:
    """Purpose of an adult / sexual-education question, or None for everything else."""
    for name, pat in _TOPICS:
        if pat.search(message or ""):
            return name
    if category in ("Sexual Education", "Adult Terminology"):
        return "education"
    return None


def rank(results: list, topic: str | None) -> list:
    """Drop fiction sources (never factual), tag every result with its source class, and order by purpose.
    Non-adult questions keep the provider's order (only fiction is dropped)."""
    kept = []
    for r in results:
        cls = classify_domain(getattr(r, "domain", ""))
        if cls == FICTION:
            continue
        r.source_class = cls
        kept.append(r)
    if not topic:
        return kept
    order = _ORDER.get(topic, _ORDER["education"])
    kept.sort(key=lambda r: order.index(r.source_class) if r.source_class in order else len(order))  # stable
    return kept


def site_query(query: str, topic: str | None) -> str | None:
    """Site-restricted variant of the query for providers that understand `site:` (e.g. Brave)."""
    sites = PREFERRED_SITES.get(topic or "")
    if not sites:
        return None
    return f"{query} (" + " OR ".join(f"site:{s}" for s in sites) + ")"
