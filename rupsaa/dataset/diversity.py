"""Corpus-level lexical diversity / catchphrase-concentration gate.

Why this exists (V0.1 post-mortem, see
data/production/reports/rupsaa_v0.2_preparation/): the V0.1 corpus was
declared training-ready with "honestly" in 863/1129 training replies. Every
existing check was per-conversation (voice_audit.py) or limited to a small
pet-name/emoji watchlist (repetition.py), and the voice audit even *rewarded*
"honestly"/"actually" as personality markers. Nothing looked at how
concentrated the corpus's voice was as a whole — which is exactly what a
LoRA learns.

This module measures, over all assistant replies:
  * watchlist catchphrase document frequency (honestly, actually, fair call…)
  * auto-detected lexical concentration: any non-function-word n-gram (1–3)
    that appears in an outsized share of replies, watchlisted or not
  * opening concentration (first word / first two words)
  * response-skeleton concentration (sentence-shape template)
  * the same ratios inside each language group (phrase ↔ language correlation)
  * synthetic-vs-other source correlation (synthetic catchphrases)

and returns BLOCK / WARN issues. `DiversityReport.training_ready` is False if
any BLOCK issue exists; scripts/dataset_audit.py exits non-zero and
scripts/dataset_export.py refuses to export in that case.

Words are never banned: a phrase only fails when its *share of the corpus*
exceeds a threshold set from what natural conversation looks like (see
configs/dataset_production.yaml `diversity`). Thresholds are ratios over
assistant replies, not per-reply rules.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

from rupsaa.dataset.schema import ConversationRecord

# Latin words, Bengali words (incl. combining marks), apostrophe contractions.
_TOKEN_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[ঀ-৿]+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+")

# Function words (English / Banglish / Bengali) excluded from the
# auto-detected lexical-concentration check — "the"/"na"/"এটা" being common
# is language, not a catchphrase. Openings are still checked for ALL words.
FUNCTION_WORDS = frozenset(
    """
    a an the and or but if so of to in on at for with from by as is are was were be been being am
    it its it's that that's this these those there here what which who whom whose when where why how
    i i'm i'd i'll i've me my mine you you're you'd you'll your yours he she him her they them their we us our
    do does did don't doesn't didn't not no yes can can't could would should will won't just than then
    too very more most some any all about into out up down over again also only even still
    have has had having get got make made go going like know think want need really
    ami tumi tui apni amar tomar tor apnar amake tomake ke ki na e ar o je jodi tahole kintu ba
    eta sheta seta oita eita ekta ek ekhon tobe to hoy hobe hoye hote kore kora korte koro korbo
    theke jonno sathe moto niye diye ache achi acho nai nei chilo chhilo mane bole bolo shob sob
    ta te tai ra der er re ke go ei oi shei sei
    এটা সেটা ওটা এই সেই ও আর না কি কী যে যদি তাহলে কিন্তু বা এক একটা এখন তো হয় হবে হয়ে হতে
    করে করা করতে করো থেকে জন্য সাথে মতো নিয়ে দিয়ে আছে আছি নেই ছিল মানে বলে সব আমি তুমি তুই
    আপনি আমার তোমার তোর আমাকে তোমাকে কে
    """.split()
)

DEFAULT_WATCHLIST = [
    "honestly", "actually", "genuinely", "basically", "obviously", "literally",
    "fair call", "fair enough", "not gonna lie", "to be fair", "sotti bolte", "সত্যি বলতে",
    "baby", "babe", "jaan", "jaanu", "sona", "sweetheart", "cutie", "hehe", "haha",
]


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _phrase_pattern(phrase: str) -> re.Pattern:
    # Custom boundaries: \b is unreliable next to Bengali combining marks.
    return re.compile(
        r"(?<![A-Za-zঀ-৿])" + re.escape(phrase.lower()) + r"(?![A-Za-zঀ-৿])"
    )


def contains_phrase(text: str, phrase: str) -> bool:
    return bool(_phrase_pattern(phrase).search(text.lower()))


def opening(text: str, n: int) -> str:
    return " ".join(tokenize(text)[:n])


def skeleton(text: str, watchlist: list[str]) -> str:
    """Sentence-shape template of a reply, e.g. "F-|Q": each sentence →
    'F' (opens with a watchlisted filler) / 'S', plus '-' if it contains a
    dash aside, 'Q' if it's a question. Captures repeated response
    structures ("Filler X - Y. Follow-up?") independent of wording."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()] or [text]
    shapes = []
    for s in sentences[:4]:
        first = opening(s, 1)
        shape = "F" if first and any(first == w.split()[0] for w in watchlist) else "S"
        if re.search(r"\s[-–—]\s", s):
            shape += "-"
        if s.rstrip().endswith("?"):
            shape += "Q"
        shapes.append(shape)
    if len(sentences) > 4:
        shapes.append("+")
    return "|".join(shapes)


@dataclass
class Reply:
    record_id: str
    language: str
    category: str
    source_type: str
    text: str


def collect_replies(records: list[ConversationRecord]) -> list[Reply]:
    return [
        Reply(r.id, r.language, r.category, r.source_type, m["content"])
        for r in records
        for m in r.messages
        if m.get("role") == "assistant"
    ]


@dataclass
class DiversityIssue:
    severity: str  # "block" | "warn"
    kind: str  # catchphrase | lexical_concentration | opening | opening_bigram | skeleton | synthetic_catchphrase
    scope: str  # "corpus" | "language:<x>" | "source:<x>"
    key: str
    count: int
    total: int
    threshold: float

    @property
    def ratio(self) -> float:
        return round(self.count / self.total, 4) if self.total else 0.0

    def describe(self) -> str:
        return (
            f"[{self.severity.upper()}] {self.kind} {self.key!r} in {self.count}/{self.total} "
            f"replies ({self.ratio:.1%}) — {self.scope}, threshold {self.threshold:.0%}"
        )


@dataclass
class DiversityReport:
    total_replies: int
    issues: list[DiversityIssue]
    phrase_rates: dict  # scope -> {phrase: ratio}
    top_openings: list[tuple[str, int]]
    top_opening_bigrams: list[tuple[str, int]]
    top_ngrams: list[tuple[str, int]]
    top_skeletons: list[tuple[str, int]]
    gated: bool  # False when the corpus is too small for ratio checks to block
    notes: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[DiversityIssue]:
        return [i for i in self.issues if i.severity == "block"]

    @property
    def warnings(self) -> list[DiversityIssue]:
        return [i for i in self.issues if i.severity == "warn"]

    @property
    def training_ready(self) -> bool:
        return not self.blocking

    def overused_phrases(self) -> set[str]:
        """Phrases/words with a BLOCK-level concentration anywhere — per-record
        audits must not reward these as 'personality'."""
        return {i.key for i in self.blocking if i.kind in ("catchphrase", "lexical_concentration", "synthetic_catchphrase")}

    def overused_openings(self) -> set[str]:
        return {i.key for i in self.issues if i.kind == "opening"}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["training_ready"] = self.training_ready
        d["issues"] = [{**asdict(i), "ratio": i.ratio} for i in self.issues]
        return d


DEFAULT_THRESHOLDS = {
    "min_replies_to_gate": 30,  # below this, ratio checks only warn
    "min_group_replies": 50,  # language/source groups smaller than this aren't gated
    "catchphrase_warn": 0.04,
    "catchphrase_block": 0.08,
    "ngram_warn": {1: 0.10, 2: 0.03, 3: 0.02},
    "ngram_block": {1: 0.20, 2: 0.06, 3: 0.04},
    "opening_warn": 0.08,
    "opening_block": 0.15,
    "opening_bigram_warn": 0.03,
    "opening_bigram_block": 0.06,
    "skeleton_warn": 0.15,
    "skeleton_block": 0.30,
    "synthetic_ratio_warn": 3.0,  # synthetic rate ≥ this × other-source rate
}


def _merge_thresholds(overrides: dict | None) -> dict:
    t = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_THRESHOLDS.items()}
    for k, v in (overrides or {}).items():
        if isinstance(v, dict):
            t[k] = {int(kk): vv for kk, vv in v.items()}
        else:
            t[k] = v
    return t


def _severity(ratio: float, warn: float, block: float, gated: bool) -> str | None:
    if ratio > block:
        return "block" if gated else "warn"
    if ratio > warn:
        return "warn"
    return None


def analyze_corpus(
    records: list[ConversationRecord],
    watchlist: list[str] | None = None,
    thresholds: dict | None = None,
) -> DiversityReport:
    watchlist = [w.lower() for w in (watchlist or DEFAULT_WATCHLIST)]
    t = _merge_thresholds(thresholds)
    replies = collect_replies(records)
    total = len(replies)
    corpus_gated = total >= t["min_replies_to_gate"]
    issues: list[DiversityIssue] = []
    notes: list[str] = []
    if not corpus_gated:
        notes.append(f"only {total} replies (< {t['min_replies_to_gate']}): ratio checks reported as warnings only")

    def check_phrases(group: list[Reply], scope: str, gated: bool) -> dict:
        rates = {}
        n = len(group)
        for phrase in watchlist:
            count = sum(1 for r in group if contains_phrase(r.text, phrase))
            if not count:
                continue
            rates[phrase] = round(count / n, 4)
            sev = _severity(count / n, t["catchphrase_warn"], t["catchphrase_block"], gated)
            if sev:
                issues.append(DiversityIssue(sev, "catchphrase", scope, phrase, count, n,
                                             t["catchphrase_block"] if sev == "block" else t["catchphrase_warn"]))
        return rates

    phrase_rates = {"corpus": check_phrases(replies, "corpus", corpus_gated)} if total else {}

    # Per-language groups: phrase ↔ language correlation (e.g. an English
    # filler saturating Bengali-script replies).
    by_lang: dict[str, list[Reply]] = defaultdict(list)
    by_source: dict[str, list[Reply]] = defaultdict(list)
    for r in replies:
        by_lang[r.language].append(r)
        by_source[r.source_type].append(r)
    for lang, group in sorted(by_lang.items()):
        gated = corpus_gated and len(group) >= t["min_group_replies"]
        phrase_rates[f"language:{lang}"] = check_phrases(group, f"language:{lang}", gated)
    for src, group in sorted(by_source.items()):
        n = len(group)
        phrase_rates[f"source:{src}"] = {
            p: round(sum(1 for r in group if contains_phrase(r.text, p)) / n, 4) for p in watchlist
            if any(contains_phrase(r.text, p) for r in group)
        }

    # Synthetic catchphrases: much more frequent in synthetic replies than elsewhere.
    synthetic = by_source.get("synthetic_curated", [])
    others = [r for r in replies if r.source_type != "synthetic_curated"]
    if len(synthetic) >= t["min_group_replies"] and others:
        for phrase in watchlist:
            s_rate = sum(1 for r in synthetic if contains_phrase(r.text, phrase)) / len(synthetic)
            o_rate = sum(1 for r in others if contains_phrase(r.text, phrase)) / len(others)
            if s_rate > t["catchphrase_warn"] and s_rate >= t["synthetic_ratio_warn"] * max(o_rate, 0.005):
                issues.append(DiversityIssue("warn", "synthetic_catchphrase", "source:synthetic_curated", phrase,
                                             round(s_rate * len(synthetic)), len(synthetic), t["catchphrase_warn"]))

    # Auto-detected lexical concentration (not limited to the watchlist).
    ngram_df: dict[int, Counter] = {1: Counter(), 2: Counter(), 3: Counter()}
    for r in replies:
        toks = tokenize(r.text)
        for n in (1, 2, 3):
            grams = set()
            for i in range(len(toks) - n + 1):
                gram = toks[i:i + n]
                if all(g in FUNCTION_WORDS for g in gram):
                    continue
                grams.add(" ".join(gram))
            ngram_df[n].update(grams)
    watch_set = set(watchlist)
    for n in (1, 2, 3):
        for gram, count in ngram_df[n].most_common(50):
            if gram in watch_set:
                continue  # already reported as a catchphrase
            sev = _severity(count / total, t["ngram_warn"][n], t["ngram_block"][n], corpus_gated) if total else None
            if sev:
                issues.append(DiversityIssue(sev, "lexical_concentration", "corpus", gram, count, total,
                                             t["ngram_block"][n] if sev == "block" else t["ngram_warn"][n]))

    # Openings and skeletons.
    openings = Counter(opening(r.text, 1) for r in replies if r.text.strip())
    openings2 = Counter(opening(r.text, 2) for r in replies if len(tokenize(r.text)) >= 2)
    skeletons = Counter(skeleton(r.text, watchlist) for r in replies)
    for key, count in openings.most_common(10):
        sev = _severity(count / total, t["opening_warn"], t["opening_block"], corpus_gated)
        if sev:
            issues.append(DiversityIssue(sev, "opening", "corpus", key, count, total,
                                         t["opening_block"] if sev == "block" else t["opening_warn"]))
    for key, count in openings2.most_common(10):
        sev = _severity(count / total, t["opening_bigram_warn"], t["opening_bigram_block"], corpus_gated)
        if sev:
            issues.append(DiversityIssue(sev, "opening_bigram", "corpus", key, count, total,
                                         t["opening_bigram_block"] if sev == "block" else t["opening_bigram_warn"]))
    for key, count in skeletons.most_common(5):
        sev = _severity(count / total, t["skeleton_warn"], t["skeleton_block"], corpus_gated)
        if sev:
            issues.append(DiversityIssue(sev, "skeleton", "corpus", key, count, total,
                                         t["skeleton_block"] if sev == "block" else t["skeleton_warn"]))

    top_ngrams = sorted(
        ((g, c) for n in (1, 2, 3) for g, c in ngram_df[n].most_common(15)), key=lambda x: -x[1]
    )[:30]
    return DiversityReport(
        total_replies=total,
        issues=sorted(issues, key=lambda i: (i.severity != "block", -i.ratio)),
        phrase_rates=phrase_rates,
        top_openings=openings.most_common(15),
        top_opening_bigrams=openings2.most_common(15),
        top_ngrams=top_ngrams,
        top_skeletons=skeletons.most_common(10),
        gated=corpus_gated,
        notes=notes,
    )


def analyze_with_config(records: list[ConversationRecord]) -> DiversityReport:
    """analyze_corpus using configs/dataset_production.yaml `diversity`."""
    from rupsaa.dataset.config import load_dataset_config

    cfg = load_dataset_config().get("diversity", {})
    return analyze_corpus(records, cfg.get("watchlist"), cfg.get("thresholds"))
