"""V0.2.2 runtime blockers from the rescue diagnosis — live owner stores, no model."""

import pytest

from rupsaa.config import PROJECT_ROOT
from rupsaa.rag.context_builder import build_turn_knowledge
from rupsaa.rag.dance import DanceStore
from rupsaa.rag.terminology import TerminologyStore

TERMS = TerminologyStore(PROJECT_ROOT / "knowledge/terminology")
DANCE = DanceStore(PROJECT_ROOT / "knowledge/dance")


def attached(msg, prev=None, history=0):
    return build_turn_knowledge(msg, use_rag=False, rag_query=None, terminology=TERMS, dance=DANCE,
                                previous_terms=prev, history_messages=history)


@pytest.mark.parametrize("msg,want", [
    ("stripping ki jinish?", "term-strip_stripping"), ("consent ki jinish?", "term-consent"),
    ("cumbia kon desher?", "dance-cumbia"), ("mambo kon desher dance?", "dance-mambo"),
    ("মাম্বো কোথাকার নাচ?", "dance-mambo"), ("মাম্বো নাচ কী?", "dance-mambo"), ("জুক নাচ কোথাকার?", "dance-zouk"),
    ("কুম্বিয়া কোন দেশের নাচ?", "dance-cumbia"), ("হাউস ডান্স কী?", "dance-house_dance"),
    ("Strip mane ki?", "term-strip_stripping"), ("Kathak kothakar dance?", "dance-kathak"),
])
def test_known_gaps_now_attach(msg, want):
    assert want in attached(msg).terms_used


def test_every_dance_has_a_bengali_alias():
    import re
    assert all(any(re.search("[ঀ-৿]", a) for a in d.aliases) for d in DANCE.list())


@pytest.mark.parametrize("msg,lang", [
    ("বাংলায়", "bn"), ("বাংলায় বলো", "bn"), ("এবার বাংলায়", "bn"), ("এটা বাংলা হরফে লেখো", "bn"),
    ("আরও সহজ করে", None), ("আরও সহজ করে বলো", None), ("simple kore", None), ("aro simple kore bolo", None),
    ("simpler", None), ("ek line e bolo", None), ("aro shohoj kore", None), ("bangla horofe likho", "bn"),
    ("এটা বাংলায় সহজ করে বুঝিয়ে বলো", "bn"), ("banglay simple kore bujhiye bolo", "bn"),
])
def test_immediate_followups_carry_the_previous_record(msg, lang):
    k = attached(msg, prev=["dance-mambo"], history=2)
    assert k.route == "followup" and k.terms_used == ["dance-mambo"] and k.language == lang


@pytest.mark.parametrize("msg", [
    "breaking news er origin ki?", "polka dots bhalo lage", "polka dot er origin ki?", "house price koto?",
    "locking a door", "popping a balloon", "strip whitespace in python", "how to strip a string",
    "tap water khawa safe?", "the tap is leaking", "everyone has a breaking point", "কাল ব্রেকিং নিউজ দেখলাম",
    "আমার বাসা ওয়াকিং ডিসট্যান্সে", "মাম্বো জাম্বো কথা বোলো না", "ami ekta simple manush", "আমি বাংলায় কথা বলতে ভালোবাসি",
])
def test_false_positive_protection(msg):
    k = attached(msg)
    assert k.terms_used == [] and k.route != "followup"
