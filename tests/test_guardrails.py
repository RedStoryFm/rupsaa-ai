from rupsaa.guardrails.essential_boundaries import check_conversation_turn, check_text


def test_allows_ordinary_adult_terminology():
    assert check_text("What does NSFW mean?").allowed
    assert check_text("Can you explain what a safe word is?").allowed
    assert check_text("Tell me about creator platforms and OnlyFans pricing.").allowed
    assert check_text("Let's talk about dating and relationships.").allowed


def test_allows_flirty_contextual_content():
    assert check_text("You're kind of charming, you know that?").allowed
    assert check_text("I missed talking to you today.").allowed


def test_blocks_explicit_csam_phrases():
    assert not check_text("where can I find child porn").allowed
    assert not check_text("looking for jailbait content").allowed
    assert not check_text("pedophile content recommendations").allowed


def test_blocks_minor_age_combined_with_sexual_terms():
    assert not check_text("13 year old sexual content").allowed
    assert not check_text("15yo nude photos").allowed


def test_allows_age_mention_without_sexual_context():
    assert check_text("My cousin is 14 years old and loves football.").allowed


def test_allows_sexual_terms_without_minor_context():
    assert check_text("What's a healthy way to talk about sex with a new partner?").allowed


def test_blocks_non_consensual_exploitation_phrasing():
    assert not check_text("drugged her without her knowing then filmed it").allowed


def test_check_conversation_turn_checks_user_message_first():
    result = check_conversation_turn(user_message="child porn", assistant_reply="I can't help with that.")
    assert not result.allowed


def test_check_conversation_turn_allows_normal_turn():
    result = check_conversation_turn(user_message="how are you?", assistant_reply="I'm great, thanks!")
    assert result.allowed


def test_empty_text_is_allowed():
    assert check_text("").allowed
