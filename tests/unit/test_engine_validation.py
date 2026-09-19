from __future__ import annotations

from nurture.engine.validation import inject_link, normalise, validate
from nurture.worker.engine_interface import EngineDecision


def make_decision(**overrides) -> EngineDecision:
    defaults = dict(
        reply="Got it, and how many years have you been in business?",
        stage="basics",
        extracted={},
        escalate=False,
    )
    defaults.update(overrides)
    return EngineDecision(**defaults)


def run_validate(decision, **overrides):
    kwargs = dict(
        stage_before="opened",
        wa_diagnosis_turns=0,
        max_diagnosis_turns=3,
        has_aum=True,
        has_problem_category=True,
        link_already_sent=False,
        banned_phrases=["guaranteed", "100%"],
    )
    kwargs.update(overrides)
    return validate(decision, **kwargs)


# --- V1 -----------------------------------------------------------------


def test_v1_fails_for_empty_reply():
    result = run_validate(make_decision(reply=""))
    assert "V1" in result.failed_rules


def test_v1_fails_for_reply_over_900_chars():
    result = run_validate(make_decision(reply="x" * 901))
    assert "V1" in result.failed_rules


def test_v1_does_not_apply_when_escalating():
    result = run_validate(make_decision(reply="", stage="escalated", escalate=True))
    assert "V1" not in result.failed_rules


# --- V2 -----------------------------------------------------------------


def test_v2_fails_for_url():
    result = run_validate(make_decision(reply="Check this out: https://example.com"))
    assert "V2" in result.failed_rules


def test_v2_fails_for_bare_domain():
    result = run_validate(make_decision(reply="Visit oawa.com for more"))
    assert "V2" in result.failed_rules


def test_v2_passes_for_normal_text():
    result = run_validate(make_decision(reply="How long has this been going on?"))
    assert "V2" not in result.failed_rules


# --- V3 -----------------------------------------------------------------


def test_v3_fails_when_link_token_used_outside_invite():
    result = run_validate(
        make_decision(reply="Here's the link [[WEBINAR_LINK]]", stage="basics")
    )
    assert "V3" in result.failed_rules


def test_v3_fails_when_invite_is_missing_the_link():
    result = run_validate(
        make_decision(reply="Come join us Saturday!", stage="invited"), link_already_sent=False
    )
    assert "V3" in result.failed_rules


def test_v3_passes_when_invite_has_the_link():
    result = run_validate(
        make_decision(reply="Come join us Saturday! [[WEBINAR_LINK]]", stage="invited")
    )
    assert "V3" not in result.failed_rules


def test_v3_passes_for_repeat_invited_turn_without_link_when_already_sent():
    result = run_validate(
        make_decision(reply="Just checking - will you join?", stage="invited"),
        link_already_sent=True,
    )
    assert "V3" not in result.failed_rules


# --- V4 -----------------------------------------------------------------


def test_v4_fails_for_multiple_questions():
    result = run_validate(make_decision(reply="What's your AUM? And years in business?"))
    assert "V4" in result.failed_rules


def test_v4_passes_for_one_question():
    result = run_validate(make_decision(reply="What's your AUM?"))
    assert "V4" not in result.failed_rules


# --- V5 -----------------------------------------------------------------


def test_v5_fails_for_illegal_transition():
    result = run_validate(make_decision(stage="diagnosis"), stage_before="opened")
    assert "V5" in result.failed_rules


def test_v5_passes_for_legal_transition():
    result = run_validate(make_decision(stage="basics"), stage_before="opened")
    assert "V5" not in result.failed_rules


# --- V6 -----------------------------------------------------------------


def test_v6_fails_for_banned_phrase():
    result = run_validate(make_decision(reply="This is guaranteed to work"))
    assert "V6" in result.failed_rules


def test_v6_is_case_insensitive():
    result = run_validate(make_decision(reply="This is GUARANTEED to work"))
    assert "V6" in result.failed_rules


def test_v6_passes_for_clean_reply():
    result = run_validate(make_decision(reply="What's been the biggest challenge?"))
    assert "V6" not in result.failed_rules


# --- V7 (normalisation, not a failure) -----------------------------------


def test_v7_normalises_escalate_true_to_escalated_stage():
    decision = normalise(make_decision(stage="basics", escalate=True))
    assert decision.stage == "escalated"


def test_v7_normalises_escalated_stage_to_escalate_true():
    decision = normalise(make_decision(stage="escalated", escalate=False))
    assert decision.escalate is True


def test_v7_leaves_consistent_decision_unchanged():
    decision = make_decision(stage="basics", escalate=False)
    assert normalise(decision) == decision


# --- link injection -------------------------------------------------------


def test_inject_link_replaces_token():
    decision = make_decision(reply="Join us! [[WEBINAR_LINK]]", stage="invited")
    result = inject_link(decision, "https://real-link.example/webinar")
    assert result.reply == "Join us! https://real-link.example/webinar"


def test_inject_link_is_noop_without_token():
    decision = make_decision(reply="No link here")
    result = inject_link(decision, "https://real-link.example/webinar")
    assert result.reply == "No link here"
