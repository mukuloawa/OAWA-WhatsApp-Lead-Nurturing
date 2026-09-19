"""End-to-end proof that the Appendix E simulator machinery itself works
correctly — full multi-turn conversation, real pipeline, real
assertion evaluation — using a scripted engine instead of the real
Claude API (which this environment has no access to). This is what
actually exercises sim/runner.py and sim/assertions.py, independent of
whether a live ANTHROPIC_API_KEY is ever supplied.
"""

from __future__ import annotations

from nurture.sim.assertions import evaluate_assertions
from nurture.sim.runner import run_scenario
from nurture.worker.engine_interface import EngineDecision


def _scripted_s1_like_engine(stub_engine_factory, webinar_link: str):
    """Mimics S1's expected trajectory: basics -> problem_ask ->
    diagnosis (x3) -> invited -> confirmed, matching S1's 6 lead_turns.

    Link injection (DESIGN.md Section 9.3) happens inside ClaudeEngine
    itself, not the pipeline (DESIGN.md Section 4 scopes all of Section
    9 to engine/) — this raw stub bypasses ClaudeEngine entirely, so it
    must supply the already-injected real link directly, the way
    ClaudeEngine's output would look after injection."""
    script = [
        EngineDecision(
            reply="Got it, and how many years in business?",
            stage="basics",
            extracted={"aum": "6 crore"},
            escalate=False,
        ),
        EngineDecision(
            reply="What's the one thing bothering you most right now?",
            stage="problem_ask",
            extracted={"years_in_business": "3 years"},
            escalate=False,
        ),
        EngineDecision(
            reply="How long has this been going on?",
            stage="diagnosis",
            extracted={"problem_category": "lead_gen"},
            escalate=False,
        ),
        EngineDecision(
            reply="What have you tried so far?",
            stage="diagnosis",
            extracted={},
            escalate=False,
        ),
        EngineDecision(
            reply=f"Come join us Saturday! {webinar_link} Will you join?",
            stage="invited",
            extracted={},
            escalate=False,
        ),
        EngineDecision(
            reply="Great, see you Saturday!",
            stage="confirmed",
            extracted={},
            escalate=False,
        ),
    ]
    calls = {"n": 0}

    def decide(**_kwargs):
        decision = script[calls["n"]]
        calls["n"] += 1
        return decision

    return stub_engine_factory(decide)


async def test_simulator_runs_a_full_scripted_conversation_and_assertions_pass(
    stub_engine_factory, valid_settings_kwargs
):
    scenario = {
        "id": "SIM-TEST-1",
        "name": "Scripted end-to-end smoke test",
        "contact": {"first_name": "Rahul", "city": "Pune"},
        "lead_turns": [
            "around 6 crore abhi",
            "3 saal ho gaye",
            "leads nahi aa rahe yaar",
            "Instagram try kiya tha but kuch nahi hua",
            "honestly zero. sab referral se hi hai",
            "haan definitely coming",
        ],
        "assertions": {
            "every_turn": ["max_one_question", "no_url", "max_chars_900"],
            "final_stage": "confirmed",
            "extracted_includes": {"problem_category": "lead_gen"},
            "link_sent_exactly_once": True,
            "max_diagnosis_turns": 3,
        },
    }

    from nurture.settings import Settings

    settings = Settings(_env_file=None, **valid_settings_kwargs)
    engine = _scripted_s1_like_engine(stub_engine_factory, settings.webinar_link)

    result = await run_scenario(scenario, engine=engine, settings=settings)

    assert result.passed, result.failures
    assert len(result.transcript) == 6
    assert result.transcript[-1].outcome.stage_after == "confirmed"


async def test_simulator_stops_early_at_a_terminal_stage(stub_engine_factory, valid_settings_kwargs):
    """If the bot reaches a terminal stage early, remaining lead_turns
    are skipped (DESIGN.md Appendix E)."""
    decisions = [
        EngineDecision(reply="What's your AUM?", stage="basics", extracted={}, escalate=False),
        EngineDecision(
            reply="", stage="escalated", extracted={}, escalate=True, escalation_reason="abusive"
        ),
    ]
    calls = {"n": 0}

    def decide(**_kwargs):
        d = decisions[min(calls["n"], len(decisions) - 1)]
        calls["n"] += 1
        return d

    scenario = {
        "id": "SIM-TEST-2",
        "name": "Early termination",
        "contact": {"first_name": "Test", "city": "Pune"},
        "lead_turns": ["6 crore", "you are all idiots", "this should never be sent"],
        "assertions": {"final_stage": "escalated"},
    }

    from nurture.settings import Settings

    settings = Settings(_env_file=None, **valid_settings_kwargs)
    engine = stub_engine_factory(decide)

    result = await run_scenario(scenario, engine=engine, settings=settings)

    assert result.passed, result.failures
    assert len(result.transcript) == 2  # third lead_turn was skipped
    assert result.skipped_lead_turns == 1


def test_evaluate_assertions_reports_specific_failures():
    from dataclasses import dataclass

    from nurture.ghl.models import Contact
    from nurture.worker.pipeline import PipelineOutcome

    @dataclass
    class FakeTurn:
        outcome: PipelineOutcome

    transcript = [
        FakeTurn(
            outcome=PipelineOutcome(
                status="processed",
                reply_text="What's your AUM? And years in business?",  # two '?' — violates max_one_question
                stage_after="basics",
            )
        )
    ]
    contact = Contact(id="c1", first_name="X", city=None, tags={"wa-stage-2"}, fields={})

    failures = evaluate_assertions(
        {"every_turn": ["max_one_question"], "final_stage": "confirmed"},
        transcript=transcript,
        final_contact=contact,
        webinar_link="https://example.com",
    )

    assert any("max_one_question" in f for f in failures)
    assert any("final_stage" in f for f in failures)
